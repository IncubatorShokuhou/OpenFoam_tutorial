# 第 6 课：把大气算例和方腔流画出来

这一课用 `foamToVTK -ascii` 把网格和场合成一个 VTK，再用 Matplotlib 画图。大气算例的图在 `tutorial/images/atm_*.png`，由 `examples/jingshan_openmeteo` 在 t = 360 导出。第 7 课到第 10 课的图用同一脚本。ERA5 的前缀是 `era5`，GFS 是 `gfs`，wrfout 是 `wrf`，观测表是 `csv`。方腔流仍用原来的 `plot_cavity.py`，给第 2 课和第 4 课留底。

```mermaid
flowchart TD
  mesh["constant/polyMesh"] --> vtk["foamToVTK -ascii"]
  fields["120/ 240/ 360/ 里的 U T q p p_rgh"] --> vtk
  vtk --> py["tools/plot_atmospheric.py"]
  dem["dem_utm.tif"] --> py
  py --> terrain["atm_terrain.png"]
  py --> grid["atm_mesh.png"]
  py --> wind["atm_wind.png"]
  py --> temp["atm_temperature.png"]
  py --> humid["atm_humidity.png"]
  py --> prof["atm_profiles.png"]
```

坐标已经是局部米。Cartopy 用在第 5 课核对经纬度下载范围。投影之后的 DEM、STL 和 OpenFOAM 结果都不要再送进 Cartopy。

| 数据 | 坐标 | 工具 |
|---|---|---|
| 方腔、地形风场 | 局部 x y z，单位 m | ParaView、Matplotlib |
| 刚下载的 DEM | 经纬度，单位 ° | Cartopy、QGIS、Rasterio |
| 投影后的 DEM | 东、北坐标，单位 m | QGIS、Matplotlib、ParaView |

## 6.1 安装画图环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-post.txt -r requirements-terrain.txt
```

求解本身不需要这套包。`rasterio` 只为读取 `dem_utm.tif`。

## 6.2 地形和网格

`./plot_atmospheric.sh` 会先导出最新时刻，再调用 `tools/plot_atmospheric.py`。地形图直接读 GeoTIFF，不经过求解器。颜色是高程，黑线是等高线。景山主峰在局部坐标 `x ≈ 480 m`、`y ≈ 240 m`，高程约 85 m。西边界高差大约 7 m，入口面比较直。

![景山，由 Copernicus GLO-30 读出](images/atm_terrain.png)

网格图读 `constant/polyMesh/points`，按 `constant/terrainCase` 里的 `nx ny nz` 还原成结构网格，取 `y` 方向中间那一排画 x-z。近地面的格子更扁，是增长率 1.10 的结果。山坡上的竖线跟着地形走，所以格子不是正交的。`fvSchemes` 里的拉普拉斯和面法向修正用了 `limited corrected 0.5`，就是为这些斜格子。

![地形跟随网格的 x-z 截面](images/atm_mesh.png)

## 6.3 风、位温和比湿

导出命令和方腔流相同，只是算例路径不同：

```bash
source ./env.sh
foamToVTK -ascii -case work/atmospheric -latestTime
```

`-latestTime` 在默认设置下读 `360/`。日志写 `Time: 360`。内部 VTK 的文件名是 `atmospheric_180.vtk`：`deltaT` 是 2，时间步编号走到 180。`-ascii` 让 `plot_atmospheric.py` 能直接拆 POINTS、CELLS 和 CELL_DATA。这次导出的内部网格是 4608 个格子、5525 个点。`plot_atmospheric.py` 打印的范围是：

```text
cells=4608, speed=[0.3277, 6.838] m/s, T=[249.6, 277.6] K, q=[0.0006249, 0.001005] kg/kg
```

脚本在 `y` 中线附近取一层格子，用格子中心的 `x,z` 做填色。箭头是 `(Ux, Uz)` 的抽样，抽样只影响图，不改变网格。

![y 中线附近的风速](images/atm_wind.png)

速度大小是 `|U|` 的三个分量，水平风和垂直风都算进去。全场 0.33 到 6.84 m/s，平均 3.65 m/s。5% 到 95% 分位是 1.75 到 4.92 m/s。`y ≈ 255 m` 的截面上，入口一侧 `x < 63 m`、离地约 9 m 的四个格子平均风速 1.84 m/s。同一高度的入口表在 t = 360 给出的风速也是 1.85 m/s，来自 02Z。00Z 同一高度大约 3 m/s。高点 `x ≈ 480 m` 的近地面平均 2.17 m/s，比入口略快。02Z 的弱风从入口走到主峰需要大约 260 s，t = 360 时山前还留着稍早、稍强的空气。

![同一截面的位温](images/atm_temperature.png)

`T` 在这个算例里是位温。全场 249.6 到 277.6 K。5% 到 95% 分位是 264.1 到 268.7 K，平均 266.3 K。截面上入口一侧从离地约 9 m 的 265.9 K 升到 140 m 以上的 267.9 K。入口表在 t = 360、10 m 处是 266.2 K，160 m 处是 267.8 K。格子中心已经换成 02Z 的柱，不再是 00Z 写进 `0/` 的 263.2 K。地面热通量按 22 W/m² 在 8.4 m 的第一层里维持 360 s，只升温大约 0.8 K。249.6 K 和 277.6 K 这两头不是这 0.8 K 能解释的。`T0` 仍是 290 K。

![同一截面的比湿](images/atm_humidity.png)

比湿画成 g/kg，文件里的 `q` 仍是 kg/kg。全场 0.62 到 1.01 g/kg。5% 到 95% 分位是 0.65 到 0.77 g/kg，平均 0.71 g/kg。近地面大约 0.7 g/kg，往上减小，并被风带过山体。密度没有用到它。

## 6.4 剖面

![入口表、入口第一列和高点附近的剖面](images/atm_profiles.png)

纵轴是离地高度。灰线是边界表在最新时刻、`y` 取截面位置的插值。这一次最新时刻是 t = 360，也就是 02Z。蓝线是入口一侧 `x < 63 m` 的格子按离地高度平均。橙线是高程最大处附近的结果，大约在 `x = 480 m`。

灰线在 10 m 处大约是 266.2 K、1.85 m/s。蓝线在离地约 9 m 处是 265.9 K、1.84 m/s。两者已经靠在一起。360 s 足够让入口旁的格子换成边界上的空气。蓝线和灰线如果再分开，先看平流距离，再查 `constant/boundaryData/inlet`，也看日志里的 `bounding k`。

高点附近近地面是 265.1 K、2.17 m/s。140 m 以上是 268.7 K、4.28 m/s。入口表在 160 m 处是 267.8 K，水平风速大约 4.6 m/s。高层空气 360 s 里走出大约 1600 m，已经换过一整遍。近地面 1.8 m/s 走到 `x = 480 m` 大约要 260 s，山前还混着稍早的风。

第四栏是求解得到的 `p_rgh`。准备阶段把出口边界表缩放到 ±5 Pa。内部场在 t = 360 是 -83 到 54 Pa。5% 到 95% 分位是 -12 到 13 Pa，平均 3 Pa。入口一侧近地面约 5 Pa，到离地 140 m 以上约 -6 Pa。高点附近近地面约 9 Pa。位温在 266 K 附近，`T0` 是 290 K，静力残差本身有几十帕。-83 Pa 和 54 Pa 这两头和位温的两头一样，比山体绕流的动压大。`0.5*rho*U^2` 在 3.6 m/s 时大约 8 Pa。绝对气压在 `constant/pRef`，加上静力部分之后才回到 10⁵ Pa 那一档。

## 6.5 方腔流用同一套 VTK

方腔流没有地图坐标。`./plot_cavity.sh` 导出 `work/cavity` 并调用 `tools/plot_cavity.py`。

```bash
source ./env.sh
foamToVTK -ascii -case work/cavity -latestTime
```

成功时摘要接近：

```text
Time: 10
volScalarFields : p nut k epsilon
volVectorFields : U
Original cells:400 points:882
End
```

`cavity_2000.vtk` 里的 `2000` 是时间步编号。日志里的物理时间是 `t = 10 s`。

```text
DATASET UNSTRUCTURED_GRID
├── POINTS 882
├── CELLS 400
├── CELL_DATA 400
│   ├── U[400,3]
│   └── p[400,1]
└── POINT_DATA 882
```

本仓库画出的图：

![方腔流真实计算结果](images/cavity_result.png)

```text
cells=400, points=882, speed=[0.0015856, 0.251305] m/s
```

格子中心的最大速度约 0.251 m/s，上壁是 1 m/s。上壁速度定义在边界上，离壁面最近的格子中心还有半个网格。A 图是网格和部分箭头。B 图的白线是该时刻的流线，沿速度方向，不是一颗水滴的轨迹。C 图的 `p` 是运动压力，单位 m²/s²。填色在格子中心之间做了三角插值，分辨率仍是 400 个格子。

有桌面时：

```bash
paraFoam -case work/cavity
paraFoam -case work/atmospheric
```

大气算例把 Coloring 选成 `U`、`T` 或 `q`，用 Slice 切 `y` 法向的中面。服务器上没有桌面时，把 VTK 拷到本机，或直接用这里的 PNG。

## 费曼检查

1. 地形图为什么可以在 `foamRun` 之前就画？
2. 网格图里的斜线说明什么，`limited corrected` 是在处理这件事吗？
3. 比湿图上的结构如果和风速很像，能不能说明湿度改变了密度？
4. 剖面图灰线和蓝线分开时，应该先查哪一个目录？
5. `p_rgh` 只有十几帕，和 101325 Pa 的 `pRef` 为什么可以同时成立？
6. 方腔流上壁 1 m/s，格子中心最大约 0.251 m/s，差在哪里？
