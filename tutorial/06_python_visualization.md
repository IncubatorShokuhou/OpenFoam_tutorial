# 第 6 课：把真实 OpenFOAM 结果画成速度、流线和压力图

这一课回答三个问题：数值藏在哪里？怎样变成通用数据？颜色和流线究竟表示什么？

![方腔流真实计算结果](images/cavity_result.png)

## 6.1 为什么这里不用 Cartopy

Cartopy 的专长是把经纬度放到地图投影上。方腔流坐标是局部直角坐标 `(x,y,z)`，单位是 m，
没有经纬度、海岸线或地图投影，因此强行使用 Cartopy 会混淆概念。

工具应按坐标选择：

| 数据 | 坐标 | 合适工具 |
|---|---|---|
| 方腔流、风洞、建筑绕流 | 局部 x/y/z，单位 m | ParaView、PyVista、Matplotlib |
| 原始 DEM 下载范围 | 经度/纬度，单位 ° | Cartopy、QGIS、Rasterio |
| 投影后的 DEM 和 OpenFOAM 地形 | 局部 Easting/Northing，单位 m | QGIS、Matplotlib、ParaView |

Cartopy 会在第 5 课的“下载数据位置核对”阶段发挥作用；进入 OpenFOAM 前必须投影到米。

## 6.2 为什么先转 VTK

OpenFOAM 原生字段分散在 `10/U`、`10/p` 等文件里，网格拓扑在 `constant/polyMesh/`。
VTK 是可视化工具常用的通用格式，能把网格和字段放到同一数据集中：

```text
constant/polyMesh/ + 10/U + 10/p + ...
                    │ foamToVTK
                    ▼
work/cavity/VTK/cavity_2000.vtk
                    │ plot_cavity.py
                    ▼
PNG：网格 + 箭头 + 流线 + 压力
```

`2000` 是时间步索引，不是物理时间 2000 s；文件内部和日志表明它对应 `t=10 s`。

## 6.3 建立只服务于画图的 Python 环境

在仓库根目录：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-post.txt
```

编译 OpenFOAM 不需要 Matplotlib；求解 OpenFOAM 也不需要 Python。把后处理依赖放进 `.venv`
是为了不污染系统 Python。

## 6.4 导出最后时刻

环境装好后，最简单的办法是一条命令完成导出和绘图：

```bash
./plot_cavity.sh
```

下面把脚本内部的两步拆开学习。

```bash
source ./env.sh
foamToVTK -ascii -case work/cavity -latestTime \
    | tee work/cavity/log.foamToVTK
```

选项逐个解释：

- `-case work/cavity`：指定算例；
- `-latestTime`：只导出最大时间 `10`，而不是所有快照；
- `-ascii`：输出可读文本，方便本课 Python 脚本直接解析；生产大数据时二进制更小更快。

成功摘要接近：

```text
Time: 10
volScalarFields : p nut k epsilon
volVectorFields : U
Original cells:400 points:882
End
```

检查文件：

```bash
find work/cavity/VTK -type f -maxdepth 2 -print
head -n 8 work/cavity/VTK/cavity_2000.vtk
```

VTK 的关键数据结构：

```text
DATASET UNSTRUCTURED_GRID
├── POINTS 882                 # 882 个顶点坐标
├── CELLS 400                  # 400 个 cell 由哪些 point 组成
├── CELL_TYPES 400             # 每个 cell 的 VTK 几何类型
├── CELL_DATA 400
│   ├── U[400,3]               # 每个 cell 的三分量速度
│   └── p[400,1]               # 每个 cell 的运动压力
└── POINT_DATA 882             # 插值到顶点的数据，便于平滑显示
```

## 6.5 运行可复现绘图脚本

```bash
.venv/bin/python tools/plot_cavity.py \
    work/cavity/VTK/cavity_2000.vtk \
    --output work/cavity/cavity_result.png

file work/cavity/cavity_result.png
```

本仓库实际输出：

```text
cells=400, points=882, speed=[0.0015856, 0.251305] m/s; wrote ...
PNG image data, 2700 x 846, 8-bit/color RGBA
```

注意最大 cell 中心速度约 0.251 m/s，小于上壁的 1 m/s。并不矛盾：壁面速度定义在边界，
图中统计的是 cell 中心；最靠近壁面的中心仍与壁面有半个网格间距。

## 6.6 三幅子图逐像素解释

### A：网格与速度箭头

小方格来自真实 `POINTS/CELLS` 网格。箭头方向是 `(Ux,Uy)`，颜色和长度表示速度大小。
为避免 400 支箭头互相遮挡，脚本只画部分箭头；这只是显示抽样，不会减少求解网格。

### B：速度颜色和流线

颜色由 `|U|=sqrt(Ux²+Uy²)` 计算。流线是在某一瞬间处处沿速度方向的曲线，不是一颗真实
水滴随时间走过的轨迹。白线中心闭合，说明存在主涡；右上方高速区来自运动上壁带动流体。

### C：运动压力

填色和黑色等值线来自 `p`。绘图在离散 cell 中心间做三角插值，所以颜色看起来连续；这
没有增加新的 OpenFOAM 分辨率。定量分析应回到原始 cell 数据，而不是从 PNG 取颜色。

## 6.7 用 ParaView 交互查看

有桌面环境时：

```bash
paraFoam -case work/cavity
```

点击 **Apply**，将 Coloring 选成 `U`，Representation 选 `Surface With Edges`。想看速度
箭头可添加 Glyph filter，想看切面可添加 Slice。服务器无桌面时，可以把 VTK 文件复制到
本机，用 ParaView 打开；PNG 脚本则适合批处理和回归对比。

## 费曼检查

1. 为什么方腔流不需要 Cartopy？
2. `foamToVTK` 把哪些分散数据组合起来？
3. 流线为什么不等于粒子轨迹？
4. 为什么连续色斑不代表网格突然变细？
5. 上壁速度 1 m/s，而 cell 中心最大值约 0.251 m/s，为什么不冲突？
