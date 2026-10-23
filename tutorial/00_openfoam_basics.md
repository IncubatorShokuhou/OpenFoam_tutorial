# 第 0 课：先建立一张 OpenFOAM 地图

## OpenFOAM 在做什么

CFD（计算流体力学）把连续的流体区域切成许多小控制体，在离散网格上近似求解质量、
动量、能量等守恒方程。结果不是一张图片，而是每个时间、每个网格单元上的速度、压力、
温度等“场”。ParaView 再把这些数值画出来。

OpenFOAM 中最重要的四类东西是：

- **case（算例）**：一次模拟所需的完整目录。
- **mesh（网格）**：计算域如何被切分；通常位于 `constant/polyMesh`。
- **field（场）**：例如速度 `U`、压力 `p`，初值通常位于 `0/`。
- **application（应用）**：求解器或工具。v14 常用统一入口 `foamRun`，具体求解模块由
  `system/controlDict` 中的 `solver` 选择。

一次最小工作流是：

```text
准备字典 -> blockMesh 生成网格 -> checkMesh 检查 -> foamRun 求解 -> ParaView 查看
```

## 两个容易混淆的 OpenFOAM

互联网上同时存在 OpenFOAM Foundation（版本号如 v14）和 OpenCFD/ESI（版本号如
v2412）的发行版。它们同源但目录、求解器名和字典会有差异。本教程只针对
**OpenFOAM Foundation v14**；不要无判断地混用另一发行版的命令和算例。

## 单位和坐标

OpenFOAM 默认采用 SI 一致单位：长度 m、时间 s、速度 m/s。软件不会看变量名自动替你
换算。地形尤其要避免把经纬度“度”直接当成米；必须先投影到以米为单位的局部坐标系。
