# OpenFOAM 从零开始：编译、运行与真实地形

这套教程写给第一次接触 OpenFOAM 的读者。它使用 **OpenFOAM Foundation v14**，锁定到
补丁标签 `20261008`，先实际编译源码，再从最小方腔流算例逐步走到并行计算和真实地形。

OpenFOAM 不是一个带“新建工程”按钮的单体软件，而是一组 CFD 求解器、网格和后处理工具。
一个算例就是一棵目录；字典文件描述物理量、网格、数值格式和运行控制。

## 最短上手路径

Ubuntu 22.04/24.04/26.04 先安装系统依赖：

```bash
sudo apt update
sudo apt install build-essential flex bison git curl ca-certificates \
    openmpi-bin libopenmpi-dev zlib1g-dev libreadline-dev
```

然后运行：

```bash
git clone https://github.com/IncubatorShokuhou/OpenFoam_tutorial.git
cd OpenFoam_tutorial
./install_openfoam.sh -j 8
source ./env.sh
./run_cavity.sh
```

编译产物约占数 GB。`-j` 越大越快，但内存占用也越高；个人电脑建议从 4 或 8 开始。
每次打开新终端，都要先执行 `source ./env.sh`。

## 推荐学习顺序

| 课次 | 主题 | 学完能够回答 |
|---|---|---|
| [0](tutorial/00_openfoam_basics.md) | CFD 与 OpenFOAM | 求解器、网格、场和算例分别是什么？ |
| [1](tutorial/01_compile_openfoam.md) | 下载与编译 | 源码从哪里来，如何判断编译成功？ |
| [2](tutorial/02_first_cavity_case.md) | 第一个方腔流 | 如何从网格生成一直运行到结果？ |
| [3](tutorial/03_case_anatomy.md) | 算例目录 | `0/constant/system` 分别控制什么？ |
| [4](tutorial/04_parallel_and_paraview.md) | 并行与可视化 | 如何分区、并行求解、重构和看图？ |
| [5](tutorial/05_real_terrain.md) | 真实地形 | DEM 去哪下载、用什么格式、怎样变成 STL？ |

## 已提供的入口

- `install_openfoam.sh`：下载官方源码、编译 ThirdParty 和 OpenFOAM，可重复运行。
- `env.sh`：装载 OpenFOAM 环境，必须用 `source`。
- `run_cavity.sh`：复制官方算例、划网格、检查、串行求解。
- `run_cavity_parallel.sh`：四进程并行示范，可用 `NP=8` 修改进程数。
- `download_dem.sh`：用 OpenTopography API key 按经纬度范围下载 Copernicus GLO-30。
- `tools/dem_to_stl.py`：把已投影的 GeoTIFF DEM 转为 ASCII STL 地形表面。

源码、编译产物、下载缓存、运行结果和大型地形文件都不会提交到 Git。

## 官方来源

- OpenFOAM v14 源码：<https://github.com/OpenFOAM/OpenFOAM-14>
- ThirdParty v14：<https://github.com/OpenFOAM/ThirdParty-14>
- 官方下载说明：<https://openfoam.org/download/14-source/>
- 官方用户指南：<https://doc.cfd.direct/openfoam/user-guide-v14/>
