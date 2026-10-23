# OpenFOAM v14 零基础教程：从“看不懂”到能讲给别人听

这不是命令备忘录，而是一套给大一学生准备的实验课。默认你只会在 Linux 终端中输入命令，
不知道 CFD、有限体积法、边界条件或 OpenFOAM 是什么。

我们采用费曼学习法。每一课都重复六个动作：

1. **先用日常语言讲**：不靠术语也能知道它在做什么；
2. **再看一张图**：把文件、物理世界和计算步骤对应起来；
3. **打开真实文件**：不把配置文件当黑盒；
4. **亲手运行**：每条命令都说明输入、输出和成功标志；
5. **看真实结果**：图片由本仓库实际算出的数据生成；
6. **合上教程复述**：答不出“为什么”，就回到对应小节。

![从物理问题到图片的 OpenFOAM 工作流](tutorial/images/openfoam_workflow.svg)

## 你最终会完成什么

先模拟一个边长 0.1 m 的方盒。盒子装满流体，上盖以 1 m/s 向右移动。上盖像手掌推水，
会带动盒内形成一个旋涡。这叫 **lid-driven cavity（顶盖驱动方腔流）**。

下面不是概念图，而是本仓库在 OpenFOAM v14 中算到 `t=10 s` 后，由 VTK 数据重新绘制的
真实结果：

![方腔流的网格、速度和压力真实结果](tutorial/images/cavity_result.png)

## 仓库目录结构

和 MPAS 教程一样，程序、教程、工具、测试与生成数据严格分开：

```text
OpenFoam_tutorial/
├── README.md                       # 你正在读的总入口
├── AGENTS.md                       # 仓库维护规则
├── install_openfoam.sh             # 下载并编译 OpenFOAM v14
├── env.sh                          # 把 OpenFOAM 命令加入当前终端环境
├── run_cavity.sh                   # 串行方腔流：网格→检查→求解
├── run_cavity_parallel.sh          # MPI 并行方腔流：分区→求解→重构
├── plot_cavity.sh                  # 导出 VTK 并生成速度/压力结果图
├── download_dem.sh                 # 按经纬度下载 Copernicus GLO-30 DEM
├── prepare_atmospheric.sh          # 景山 DEM + 气象表 → 大气算例
├── run_atmospheric.sh              # checkMesh 后用 fluid 求解
├── plot_atmospheric.sh             # 导出 VTK 并画地形风场图
├── requirements-post.txt           # 方腔流绘图依赖
├── requirements-terrain.txt        # DEM 转 STL 依赖
├── requirements-era5.txt           # ERA5：CDS 下载，或读样本 NetCDF
├── requirements-gfs.txt            # GFS：eccodes 解码 GRIB2 子集
├── requirements-wrf.txt            # wrfout：netCDF4 消错位
├── cases/atmospheric/              # 大气算例的字典模板
├── examples/                       # 五个可直接 Allrun 的景山算例
│   ├── jingshan_openmeteo/         # ICON + ZBAA，积到 360 s
│   ├── era5/                       # 标明合成的 ERA5 形状 NetCDF
│   ├── gfs/                        # 2025-01-15 00Z 的真实 GFS 柱
│   ├── wrfout/                     # 标明合成的 wrfout
│   └── csv_obs/                    # 观测宽表示例和空模板
├── tools/
│   ├── plot_cavity.py              # 读取真实 VTK，画速度/压力图
│   ├── plot_atmospheric.py         # 地形、网格、风、位温、比湿
│   ├── atmospheric_case.py         # 由 DEM 和气象表写算例
│   ├── fetch_era5_boundary.py      # CDS 或样本 NetCDF → 边界表
│   ├── fetch_gfs_boundary.py       # AWS GFS GRIB2 子集 → 边界表
│   ├── fetch_openmeteo_boundary.py # 无 key：ICON 气压层、ERA5 地面、ZBAA
│   ├── wrfout_to_boundary.py       # wrfout 消错位 → 边界表
│   ├── csv_obs_to_boundary.py      # 观测宽表 → 边界表
│   └── dem_to_stl.py               # 投影 GeoTIFF → ASCII STL
├── tests/
│   ├── test_dem_to_stl.py          # 用 2×2 小 DEM 检查 STL 转换
│   ├── test_atmospheric_case.py    # 气象表、网格和景山算例准备
│   ├── test_met_sources.py         # ERA5 样本、GFS 索引、wrfout、侧面边界
│   └── test_csv_obs.py             # 观测宽表的列检查
└── tutorial/
    ├── README.md                    # 课程导航
    ├── 00_openfoam_basics.md        # 物理、网格、场、求解器
    ├── 01_compile_openfoam.md       # 下载、编译、环境、验收
    ├── 02_first_cavity_case.md      # 第一个方腔流实验
    ├── 03_case_anatomy.md           # 逐文件读 0/constant/system
    ├── 04_parallel_and_paraview.md  # MPI 分区和 ParaView
    ├── 05_real_terrain.md           # 气象输入上限、DEM、大气算例
    ├── 06_python_visualization.md   # 大气算例和方腔流的图
    ├── 07_era5_inlet.md             # ERA5 气压层进边界
    ├── 08_gfs_inlet.md              # GFS GRIB2 进边界
    ├── 09_wrfout_inlet.md           # wrfout 消错位后进边界
    ├── 10_csv_obs_inlet.md          # 自己填的观测宽表
    └── images/                      # 教程图和真实运行结果
```

运行以后还会出现下面这些目录，但它们体积大、可以重新生成，所以 `.gitignore` 不提交：

```text
OpenFoam_tutorial/
├── downloads/                      # 官方源码压缩包缓存
├── local/
│   ├── OpenFOAM-14/                # OpenFOAM 源码和编译产物
│   └── ThirdParty-14/               # Scotch、Zoltan 等第三方库
├── logs/                           # 编译日志
├── .venv/                          # Python 后处理环境
└── work/
    ├── cavity/                     # 串行算例和各时刻结果
    ├── cavity_parallel/            # 并行算例、processor* 子域
    ├── terrain/                    # DEM、投影栅格和 STL
    └── atmospheric/                # 地形大气算例和各时刻结果
```

## 第一次上机：只做这五步

Ubuntu 22.04/24.04/26.04：

```bash
# 1. 安装“造程序所需的工具”。这一步只需做一次。
sudo apt update
sudo apt install build-essential flex bison git curl ca-certificates \
    openmpi-bin libopenmpi-dev zlib1g-dev libreadline-dev

# 2. 下载本教程。
git clone https://github.com/IncubatorShokuhou/OpenFoam_tutorial.git
cd OpenFoam_tutorial

# 3. 下载并编译 OpenFOAM。8 表示最多同时做 8 份编译工作。
./install_openfoam.sh -j 8

# 4. 告诉“这个终端”OpenFOAM 安装在哪里。新终端需重新执行。
source ./env.sh

# 5. 复制官方方腔算例、生成网格、检查网格并求解。
./run_cavity.sh
```

成功时最后出现：

```text
End
Success: .../work/cavity
```

不要只看命令是否返回。继续按[课程导航](tutorial/README.md)学习，直到你能解释每一步的
输入、输出和物理意义。

## 当前经过实际验证的范围

- Ubuntu 22.04、GCC 11、系统 OpenMPI 4.1；
- OpenFOAM Foundation v14，源码补丁标签 `20261008`；
- ThirdParty、OpenFOAM 全量编译；
- 400 单元方腔流串行运行；
- 4 个 MPI rank 分区、并行求解和结果重构；
- ASCII VTK 导出及 Matplotlib 真实结果图；
- 投影 GeoTIFF 到 STL 的自动测试；
- 景山 Copernicus GLO-30 裁剪，水平 720 m × 480 m，空气柱 180 m，24 × 16 × 12 共 4608 个六面体；
- `examples/jingshan_openmeteo` 上 `checkMesh` 为 `Mesh OK`，`foamRun -solver fluid` 积到 t = 360 的 `ExecutionTime` 为 4.01 s；
- 气象强迫取 2025-01-15 00:00–02:00 UTC 的 ICON 气压层、ERA5 地面量诊断的热通量和 ZBAA 地面风；
- `examples/gfs` 用 NOAA GFS 2025-01-15 00Z 的真实柱积到 120 s，`ExecutionTime` 1.45 s；
- `examples/era5` 和 `examples/wrfout` 用标明合成的样本积到 120 s，各约 1.4 s；
- `examples/csv_obs` 用由景山表改写的观测宽表积到 120 s，`ExecutionTime` 1.43 s。

官方来源：[OpenFOAM v14](https://github.com/OpenFOAM/OpenFOAM-14)、
[ThirdParty v14](https://github.com/OpenFOAM/ThirdParty-14)、
[v14 源码安装说明](https://openfoam.org/download/14-source/)。
