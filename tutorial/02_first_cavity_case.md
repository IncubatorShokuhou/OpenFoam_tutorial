# 第 2 课：运行第一个方腔流算例

方腔流是一个装满不可压缩黏性流体的二维方盒。顶部壁面水平运动，拖动内部流体形成涡旋。
它足够小，适合验证“网格—求解—结果”整条链路。

## 一条命令运行

```bash
source ./env.sh
./run_cavity.sh
```

脚本依次执行：

1. 从 `$FOAM_TUTORIALS/incompressibleFluid/cavity` 复制官方算例到 `work/cavity`；
2. `blockMesh` 根据 `system/blockMeshDict` 生成六面体网格；
3. `checkMesh` 检查网格，并要求日志包含 `Mesh OK`；
4. `foamRun` 读取 `controlDict` 选择求解模块并推进时间。

## 手工重走一遍

```bash
cd work/cavity
blockMesh
checkMesh
foamRun
```

成功后会出现 `0.5/`、`1/` 等时间目录。可以检查最后几行：

```bash
tail -20 log.foamRun
foamListTimes
```

日志中的 `Courant Number` 衡量一个时间步内流体跨越网格的程度；`Solving for Ux` 等行中的
residual 是线性方程残差。第一次学习先确认没有 `FOAM FATAL ERROR` 且最终出现 `End`。

重跑前不要随意删除原始 `0/`。最简单的干净重跑方式是再次执行仓库根目录的
`./run_cavity.sh`，脚本会重建整个工作副本。
