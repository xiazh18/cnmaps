import os
import json
import sqlite3

import geopandas as gpd
import shapely.geometry as sgeom

DATA_DIR = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), 'data/')
DB_FILE = os.path.join(DATA_DIR, 'index.db')


class MapNotFoundError(Exception):
    pass


class MapPolygon(sgeom.MultiPolygon):
    """地图多边形类

    该是基于shapely.geometry.MultiPolygon的自定义类, 并实现了对于加号操作符的支持
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __add__(self, other):
        return self.union(other)

    def __and__(self, other):
        return self.intersection(other)

    def __sub__(self, other):
        return self.difference(other)

    def union(self, other):
        union_result = super().union(other)
        if isinstance(union_result, sgeom.Polygon):
            return MapPolygon([union_result])
        elif isinstance(union_result, sgeom.MultiPolygon):
            return MapPolygon(union_result)

    def difference(self, other):
        difference_result = super().difference(other)
        if isinstance(difference_result, sgeom.Polygon):
            return MapPolygon([difference_result])
        elif isinstance(difference_result, sgeom.MultiPolygon):
            return MapPolygon(difference_result)

    def intersection(self, other):
        intersection_result = super().intersection(other)
        if isinstance(intersection_result, sgeom.Polygon):
            return MapPolygon([intersection_result])
        elif isinstance(intersection_result, sgeom.MultiPolygon):
            return MapPolygon(intersection_result)
        else:
            return MapPolygon()

    def get_extent(self, buffer=2):
        """获取范围坐标

        参数:
            buffer (int, 可选): 外扩缓冲边缘, 单位为°, 该值越大, 所取的范围越大. 默认为 2.

        返回值:
            tuple: 坐标范围点, 该值可直接传入ax.set_extent使用
        """
        left, lower, right, upper = self.buffer(buffer).bounds
        return (left, right, lower, upper)


def read_mapjson(fp):
    """读取geojson地图边界文件

    参数:
        fp (str, 可选): geojson文件名.

    返回值:
        MapPolygon: 地图边界对象
    """
    with open(fp, encoding='utf-8') as f:
        map_json = json.load(f)

    if 'geometry' in map_json:
        geometry = map_json['geometry']
    else:
        geometry = map_json

    polygon_list = []
    if 'Polygon' in geometry['type']:
        for _coords in geometry['coordinates']:
            for coords in _coords:
                polygon_list.append(sgeom.Polygon(coords))

        return MapPolygon(polygon_list)

    elif geometry['type'] == 'MultiLineString':
        return sgeom.MultiLineString(geometry['coordinates'])


def get_adm_names(province: str = None,
                  city: str = None,
                  district: str = None,
                  level: str = None,
                  country: str = '中华人民共和国',
                  source: str = '高德'):
    """获取行政名称

    Args:
         province (str, optional): 省/自治区/直辖市/行政特区中文名, 必须为全称
                                  例如查找河北省应收入'河北省'而非'河北'. Defaults to None.
        city (str, optional): 地级市中文名, 必须为全称, 例如查找北京市应输入'北京市'而非'北京'.
                              Defaults to None.
        district (str, optional): 区/县中文名, 必须为全称. Defaults to None.
        level (str, optional): 边界等级, 目前支持的等级包括'省', '市', '区', '县'.
                               其中'省'级包括直辖市、特区等;
                               '市'级为地级市, 若为直辖市, 则名称与'省'级相同, 比如北京市的省级和市级都是'北京市';
                               '区'和'县'属于同一级别的不同表达形式.
                               Defaults to '省'.
        country (str, optional): 国家名称, 必须为全称. Defaults to '中华人民共和国'.
        source (str, optional): 数据源. Defaults to '高德'.

    Returns:
        list: 名称列表
    """
    data = get_adm_maps(province=province, city=city,
                        district=district, level=level,
                        country=country, source=source)
    if level == '国':
        names = [d['国'] for d in data]
    elif level == '省':
        names = [d['省/直辖市'] for d in data]
    elif level == '市':
        names = [d['市'] for d in data]
    elif level == '区县':
        names = [d['区/县'] for d in data]

    return names


def get_adm_maps(province: str = None,
                 city: str = None,
                 district: str = None,
                 level: str = None,
                 country: str = '中华人民共和国',
                 source: str = '高德',
                 db: str = DB_FILE,
                 engine: str = None,
                 record: str = 'all',
                 only_polygon: bool = False,
                 *args, **kwargs):
    """获取行政地图的边界对象

    Args:
        province (str, optional): 省/自治区/直辖市/行政特区中文名, 必须为全称
                                  例如查找河北省应收入'河北省'而非'河北'. Defaults to None.
        city (str, optional): 地级市中文名, 必须为全称, 例如查找北京市应输入'北京市'而非'北京'.
                              Defaults to None.
        district (str, optional): 区/县中文名, 必须为全称. Defaults to None.
        level (str, optional): 边界等级, 目前支持的等级包括'省', '市', '区', '县'.
                               其中'省'级包括直辖市、特区等;
                               '市'级为地级市, 若为直辖市, 则名称与'省'级相同, 比如北京市的省级和市级都是'北京市';
                               '区'和'县'属于同一级别的不同表达形式.
                               Defaults to '省'.
        country (str, optional): 国家名称, 必须为全称. Defaults to '中华人民共和国'.
        source (str, optional): 数据源. Defaults to '高德'.
        db (str, optional): sqlite db文件路径. Defaults to DB_FILE.
        engine (str, optional): 输出引擎, 默认为None, 输出为列表,
                                目前支持'geopandas', 若为geopandas, 则返回GeoDataFrame对象.
                                Defaults to None.

    Raises:
        ValueError: 当传入的等级

    Returns:
        gpd.GeoDataFrame | list: 根据输入参数查找到的地图边界的元信息及边界对象
    """

    con = sqlite3.connect(db)
    cur = con.cursor()

    if country:
        country_level = '国'
        country_sql = f"AND country='{country}'"
        sql = (f"SELECT id"
               f" FROM ADMINISTRATIVE"
               f" WHERE 1 {country_sql} ;")
        count = len(list(cur.execute(sql)))
        if count == 0:
            raise MapNotFoundError('未找到指定地图的边界文件')
    else:
        country_sql = ''
        country_level = None

    if province:
        province_level = '省'
        province_sql = f"AND province='{province}'"
        sql = (f"SELECT id"
               f" FROM ADMINISTRATIVE"
               f" WHERE 1 {province_sql} ;")
        count = len(list(cur.execute(sql)))
        if count == 0:
            raise MapNotFoundError('未找到指定地图的边界文件')
    else:
        province_sql = ''
        province_level = None

    if city:
        city_level = '市'
        city_sql = f"AND city='{city}'"
        sql = (f"SELECT id"
               f" FROM ADMINISTRATIVE"
               f" WHERE 1 {city_sql} ;")
        count = len(list(cur.execute(sql)))
        if count == 0:
            raise MapNotFoundError('未找到指定地图的边界文件')
    else:
        city_sql = ''
        city_level = None

    if district:
        district_level = '区县'
        district_sql = f"AND district='{district}'"
        sql = (f"SELECT id"
               f" FROM ADMINISTRATIVE"
               f" WHERE 1 {district_sql} ;")
        count = len(list(cur.execute(sql)))
        if count == 0:
            raise MapNotFoundError('未找到指定地图的边界文件')
    else:
        district_sql = ''
        district_level = None

    if source:
        source_sql = f"AND source='{source}'"
    else:
        source_sql = ''

    if not level:
        level = district_level or city_level or province_level or country_level

    if level == '国':
        level_sql = "level='国'"
        province_sql = ''
        city_sql = ''
        district_sql = ''
    elif level == '省':
        level_sql = "level='省'"
        city_sql = ''
        district_sql = ''
    elif level == '市':
        level_sql = "level='市'"
        district_sql = ''
    elif level in ['区', '县', '区县', '区/县']:
        level_sql = "level='区县'"
    else:
        raise ValueError(
            f'无法识别level等级: {level}, level参数请从"国", "省", "市", "区县"中选择')

    meta_sql = ("SELECT country, province, city, district, level, source, kind"
                " FROM ADMINISTRATIVE"
                f" WHERE {level_sql} {country_sql} {province_sql} {city_sql} {district_sql} {source_sql};")
    meta_rows = list(cur.execute(meta_sql))

    geom_sql = ("SELECT path"
                " FROM ADMINISTRATIVE"
                f" WHERE {level_sql} {country_sql} {province_sql} {city_sql} {district_sql} {source_sql};")
    gemo_rows = list(cur.execute(geom_sql))
    map_polygons = []
    for path in gemo_rows:
        mapjson = read_mapjson(os.path.join(DATA_DIR, 'geojson.min/',
                                            path[0]))

        map_polygons.append(mapjson)

    gdf = gpd.GeoDataFrame(data=meta_rows, columns=[
        '国家', '省/直辖市', '市', '区/县', '级别', '来源', '类型'])
    gdf['geometry'] = map_polygons

    if len(gdf) == 0:
        raise MapNotFoundError('未找到指定地图的边界文件')

    if record == 'all':
        if only_polygon:
            return [row.to_dict()['geometry'] for _, row in gdf.iterrows()]
        else:
            if engine == 'geopandas':
                return gdf
            elif engine is None:
                return [row.to_dict() for _, row in gdf.iterrows()]
    elif record == 'first':
        if only_polygon:
            return [row.to_dict()['geometry'] for _, row in gdf.iterrows()][0]
        else:
            if engine == 'geopandas':
                return gdf.iloc[0]
            elif engine is None:
                return [row.to_dict() for _, row in gdf.iterrows()][0]