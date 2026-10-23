# 第 1 课：下载并编译 OpenFOAM v14

## 下载了什么

安装脚本从官方 GitHub 下载两个锁定版本的归档：

- OpenFOAM：`OpenFOAM/OpenFOAM-14` 的 `20261008` 标签；
- ThirdParty：`OpenFOAM/ThirdParty-14` 的 `version-14` 标签。

前者是求解器、库、工具和官方算例；后者提供 Scotch/PT-Scotch、Zoltan 等网格分区依赖。
脚本使用系统 GCC 和 OpenMPI，不编译 ParaView。这样更快，也更适合服务器。

## 编译

```bash
./install_openfoam.sh -j 8
```

可先查看所有选项：

```bash
./install_openfoam.sh --help
```

文件位置：

```text
downloads/               下载缓存
local/OpenFOAM-14/       源码和编译出的程序/库
local/ThirdParty-14/     第三方源码和库
logs/*-build.log         完整编译日志
```

## 装载环境并验收

```bash
source ./env.sh
echo "$WM_PROJECT_VERSION"       # 应输出 14
which foamRun                    # 应指向本仓库 local/ 下
foamVersion                     # 应输出 14
./run_cavity.sh                 # 最终应输出 Success
```

`source` 很重要：环境脚本要修改当前 shell 的 `PATH` 和动态库路径，作为子进程执行
`./env.sh` 无法把这些修改带回当前终端。

## 常见失败

- `command not found`：依赖未安装，或新终端忘记 `source ./env.sh`。
- 编译进程被杀：通常是并行度太大；用 `-j 4` 重跑，已完成部分会复用。
- 磁盘满：检查 `df -h .`；源码和编译产物需要数 GB。
- MPI 混用：`which mpirun` 与 `which mpicc` 应来自同一套系统安装。
