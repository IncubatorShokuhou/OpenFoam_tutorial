# 第 5 课：真实地形从哪里来，做成什么格式

## 先分清 DEM、DTM 和 DSM

- **DEM** 是高程模型的统称。
- **DTM** 尽量表示裸地，适合大气边界层或地形绕流。
- **DSM** 包含树木和建筑物顶部；城市精细风场可能需要，但不能把 30 m DSM 当成建筑模型。

常用公开来源：

- [Copernicus DEM GLO-30/GLO-90](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM)：全球覆盖，可下载 GeoTIFF/DTED，部分访问方式需注册；也有[公开 AWS COG 镜像](https://registry.opendata.aws/copernicus-dem/)；
- [NASA/USGS SRTM 1 Arc-Second Global](https://www.usgs.gov/faqs/where-can-i-get-global-elevation-data)：约 30 m，通常经 EarthExplorer/Earthdata 获取；
- [OpenTopography](https://opentopography.org/developers)：可按研究区裁剪 SRTM、NASADEM、Copernicus 等全球 DEM，也提供部分高分辨率 LiDAR；API 需要 key；
- 中国区域也可使用有明确许可的测绘/LiDAR 数据。务必保存产品名、分辨率、垂直基准和许可证。

原始数据首选 **GeoTIFF (`.tif`)**：它同时保存栅格高程、坐标参考系、像元大小和 NoData。
不要以 PNG/JPEG 作为数值高程输入，它们通常丢失真实高度和地理参考。

本仓库提供 OpenTopography 下载脚本。先在其开发者页面申请免费 API key，再按 WGS84 经纬度
边界下载一个小范围；例如北京的一小块区域：

```bash
OPENTOPOGRAPHY_API_KEY=你的key ./download_dem.sh \
    39.85 39.95 116.30 116.45 work/terrain/dem_wgs84.tif
```

不要把 key 写进脚本或提交到 Git。API 的配额、可用数据集和许可可能变化，批量下载前查看
OpenTopography 当前说明。

## 坐标系是最常见的坑

经纬度单位是“度”，OpenFOAM 几何通常以“米”工作。先用 QGIS 的“另存为”或 GDAL
投影到适合研究区的 UTM/本地投影，并裁剪范围。例如北京中部常用 UTM 50N（EPSG:32650；
跨带或大区域应另选投影）：

```bash
gdalwarp -t_srs EPSG:32650 -r bilinear -tr 30 30 \
    input_dem.tif work/terrain/dem_utm.tif
```

确认以下事项：水平单位为 m；垂直单位也为 m；NoData 洞已填补；海拔是正高还是椭球高；
范围比最终流场入口/出口略大。OpenFOAM 不会替你处理大地水准面差异。

## GeoTIFF 转 STL

建立独立 Python 环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-terrain.txt
python tools/dem_to_stl.py work/terrain/dem_utm.tif \
    work/terrain/terrain.stl --stride 2
```

`--stride 2` 每隔两个像元取一点，可显著减少三角形；先低分辨率跑通，再加密。脚本把西南角
平移到局部 `(0,0)`，保留高程并输出 ASCII STL。可用 `surfaceCheck terrain.stl` 检查表面。

STL 只保存三角形和坐标，**不保存投影、单位或材料信息**，所以应在项目说明中另记 CRS、
原点、水平/垂直单位和缩放。本脚本生成开放的地形顶面，不是水密实体；它适合在背景计算域中
作为 `snappyHexMesh` 的贴体表面。若用于 CAD 布尔运算，则需额外封闭侧壁和底面。

## 放入 OpenFOAM 的典型流程

1. 把 `terrain.stl` 放到算例的 `constant/triSurface/`。
2. 用 `blockMesh` 建一个包住地形和上方空气的背景六面体域。
3. 在 `snappyHexMeshDict` 的 `geometry` 中声明 STL，在 `refinementSurfaces` 中设置地形
   patch 和细化级别，并把 `locationInMesh` 放在明确的空气区域内。
4. 运行 `surfaceCheck`、`blockMesh`、`snappyHexMesh -overwrite`、`checkMesh`。
5. 设置地面粗糙度、入口风廓线、顶部/侧面/出口条件，再选择稳态或瞬态求解。

`snappyHexMesh` 参数与地形尺寸、最小网格尺度、坡度和算力强相关，不存在对所有 DEM 都安全
的通用字典。先用裁剪后的低分辨率地形验证坐标和内外区域，再逐级提高细化等级；每次都看
`checkMesh`，不要只看 ParaView 中“像不像”。

## 分辨率如何选

DEM 像元远小于网格不会凭空增加可信度，只会制造大量三角形。经验上先让 STL 顶点间距与
地面附近背景网格同量级，再用网格无关性试验判断是否需要加密。30 m DEM 无法解析单栋建筑；
建筑应使用有高度属性的矢量/CityGML/点云另行建模，并与地形在同一投影和高程基准下融合。
