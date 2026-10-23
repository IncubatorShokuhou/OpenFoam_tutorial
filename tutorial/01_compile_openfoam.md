# 第 1 课：下载并编译 OpenFOAM v14

“安装别人写好的软件”像买成品家具；“从源码编译”像拿木板和图纸自己造家具。源码是人能读
的 C/C++ 文件，编译器把它翻译成 CPU 能执行的程序。我们选择源码编译，是为了让版本、
编译器和 MPI 都能复现，而不是让初学者手工处理每个库。

## 编译链条先看懂

```text
GitHub 源码压缩包
    │ curl 下载、tar 解包
    ▼
ThirdParty-14 ──► Scotch / PT-Scotch / Zoltan（并行网格分区）
    │
    ▼
OpenFOAM-14 的 C++ 源码
    │ GCC + wmake
    ├──► lib/*.so（许多功能库）
    └──► bin/foamRun、blockMesh、checkMesh、snappyHexMesh ...
```

GCC 负责翻译源码；`wmake` 负责安排哪些文件先编译、怎样链接；OpenMPI 让多个进程通信；
Scotch 把网格切成负载尽量均衡的子域。它们不是四套 CFD 软件，而是不同工种。

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

`-j 8` 表示最多同时安排 8 个编译任务，不是以后模拟固定使用 8 核。并行度越高，内存和文件
系统压力越大。笔记本先用 4；服务器可用 8～32。脚本可重复运行，已完成目标通常不会重编。

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

更完整的生成结构：

```text
local/OpenFOAM-14/
├── applications/                    # 求解模块与工具源码
├── src/                             # 基础库源码
├── tutorials/                       # 官方算例模板
├── etc/bashrc                       # 环境入口
└── platforms/linux64GccDPInt32Opt/
    ├── bin/                         # 编译出的命令
    └── lib/                         # 运行时动态库
```

目录名 `linux64GccDPInt32Opt` 可拆成：64 位 Linux、GCC、双精度浮点、32 位网格标签、优化
构建。换编译选项可能生成另一个平台目录，不要硬编码它的全名，环境脚本会选择正确路径。

## 装载环境并验收

```bash
source ./env.sh
echo "$WM_PROJECT_VERSION"       # 应输出 14
which foamRun                    # 应指向本仓库 local/ 下
foamVersion                     # 应显示 OpenFOAM-14
./run_cavity.sh                 # 最终应输出 Success
```

`source` 很重要：环境脚本要修改当前 shell 的 `PATH` 和动态库路径，作为子进程执行
`./env.sh` 无法把这些修改带回当前终端。

可以把 `PATH` 想成终端的“电话簿”。输入 `blockMesh` 时，shell 按 `PATH` 从前到后寻找
同名程序。`source ./env.sh` 是把本仓库的 OpenFOAM `bin` 加入当前电话簿。

## 常见失败

- `command not found`：依赖未安装，或新终端忘记 `source ./env.sh`。
- 编译进程被杀：通常是并行度太大；用 `-j 4` 重跑，已完成部分会复用。
- 磁盘满：检查 `df -h .`；源码和编译产物需要数 GB。
- MPI 混用：`which mpirun` 与 `which mpicc` 应来自同一套系统安装。

定位失败时先读日志末尾，而不是从第一行警告开始猜：

```bash
tail -80 logs/thirdparty-build.log
tail -80 logs/openfoam-build.log
df -h .
free -h
```

## 费曼检查

1. GCC、wmake、OpenMPI、Scotch 各做什么？
2. `-j 8` 为什么不等于模拟时固定用 8 个 MPI 进程？
3. 为什么每个新终端都要 `source ./env.sh`？
4. 哪个目录是源码，哪个目录装着最终可执行命令？
5. 编译末尾没有报错，为什么还要跑方腔流验收？
