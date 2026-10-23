# 第 4 课：并行运行与 ParaView

## 并行的四步

```bash
source ./env.sh
NP=4 ./run_cavity_parallel.sh
```

脚本执行：

```text
blockMesh -> decomposePar -> mpirun foamRun -parallel -> reconstructPar
```

`decomposePar` 产生 `processor0/` 等子域；MPI 每个 rank 计算一个子域；`reconstructPar`
把分散结果重构成普通时间目录。进程数必须与 `numberOfSubdomains` 一致，脚本会自动修改。

方腔算例太小，并行反而可能更慢；它只用于学习流程。真正的大网格才会受益。

## 可视化

本机已安装 ParaView 时：

```bash
paraFoam -case work/cavity
```

如果 `paraFoam` 找不到 ParaView，可直接生成标记文件：

```bash
touch work/cavity/cavity.foam
paraview work/cavity/cavity.foam
```

在 ParaView 中点击 **Apply**，选择 `U`，用 Slice 查看中间截面，再用 Glyph 或 Stream Tracer
查看速度方向。远程服务器通常没有图形桌面，可把算例重构结果复制到本机 ParaView 打开，或用
ParaView 的 client/server 模式。
