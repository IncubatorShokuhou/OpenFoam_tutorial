# 第 2 课：把第一个方腔流从输入跑到结果

这一课像做化学实验：先认清实验台，再逐步操作，并在每步检查留下了什么。不要一上来只运行
总脚本；先看总流程，再把三条核心命令手动做一遍。

## 2.1 实验目标

我们要回答一个具体问题：边长 0.1 m 的方盒里，上壁以 1 m/s 向右运动，10 s 后流体怎样流？

预测再计算：靠近上壁的速度应最大；由于右墙挡住流体，流线会向下弯；盒内应出现大旋涡。
先写下预测，计算结束再比较。这是科学计算，不是“点运行看有没有报错”。

## 2.2 让脚本准备一个可随时丢弃的工作副本

在仓库根目录：

```bash
source ./env.sh
./run_cavity.sh
```

脚本不会修改官方源码里的教学案例。它把官方案例复制到 `work/cavity/`，再运行：

```text
官方只读模板
local/OpenFOAM-14/tutorials/incompressibleFluid/cavity/
          │ cp -a
          ▼
可修改的实验副本
work/cavity/
          │
          ├─ blockMesh  ──► constant/polyMesh/
          ├─ checkMesh  ──► log.checkMesh
          └─ foamRun    ──► 0.5/ 1/ 1.5/ ... 10/
```

成功时末尾必须同时看到 `End` 和 `Success`。只有 `blockMesh` 成功不代表求解成功。

## 2.3 第一步：`blockMesh` 把一只大盒子切成小盒子

总脚本跑完后，进入算例目录并重新执行网格命令：

```bash
cd work/cavity
blockMesh | tee log.blockMesh.manual
```

命令的输入是 `system/blockMeshDict`，输出是 `constant/polyMesh/`。关键输出：

```text
boundingBox: (0 0 0) (0.1 0.1 0.01)
nCells: 400
patch 0 ... name: movingWall
patch 1 ... name: fixedWalls
patch 2 ... name: frontAndBack
End
```

逐句翻译：计算域从 `(0,0,0)` 到 `(0.1,0.1,0.01)` m；共有 `20×20×1=400` 个 cell；
边界被分成运动上壁、静止墙、二维前后面三组。patch 是一组使用同一种边界规则的网格面。

看看生成的网格数据结构：

```text
constant/polyMesh/
├── points       # 所有网格顶点的坐标
├── faces        # 每个网格面由哪些 point 组成
├── owner        # 每个 face 归属哪个 cell
├── neighbour    # 内部 face 另一侧是哪个 cell
└── boundary     # 哪些 face 属于 movingWall 等 patch
```

这五份表合起来，才能重建网格。OpenFOAM 不为每个六面体重复保存八个坐标，而是用编号连接
points、faces 和 cells，减少重复。

## 2.4 第二步：`checkMesh` 做网格体检

```bash
checkMesh | tee log.checkMesh.manual
```

寻找：

```text
hexahedra: 400
Mesh non-orthogonality Max: 0 average: 0
Max skewness = ... OK
Mesh OK.
```

`Mesh OK` 表示通过程序的质量检查，不表示网格一定足够精细。体检正常的人也未必能跑马拉松；
同样，拓扑正确的粗网格未必能解析细小涡旋。

## 2.5 第三步：`foamRun` 推进时间

```bash
foamRun | tee log.foamRun.manual
```

`system/controlDict` 中有 `solver incompressibleFluid;`，因此 `foamRun` 加载不可压缩流体求解
模块。典型一个时间步：

```text
Time = 0.005s
smoothSolver: Solving for Ux, Initial residual = 1, Final residual = ...
GAMG: Solving for p, Initial residual = 1, Final residual = ...
time step continuity errors: ...
```

人话解释：程序先把时间从 0 推到 0.005 s，然后迭代求 x 方向速度和压力。residual 是“这次
代数方程还差多少没满足”的指标，通常应随迭代下降。它不是与实验真值的误差。

`deltaT=0.005`、`endTime=10`，所以共推进约 2000 步；`writeInterval=100` 表示每 100 步
写一次，即每 0.5 s 留一个快照。

## 2.6 结果目录究竟新增了什么

```text
work/cavity/
├── 0/                 # 你给的初值和边界条件
├── 0.5/               # 程序算出的 t=0.5 s 快照
├── 1/
├── ...
├── 10/                # 程序算出的最终快照
│   ├── U              # 速度场
│   ├── p              # 运动压力场
│   ├── k              # 湍动能
│   ├── epsilon        # 湍动能耗散率
│   ├── nut            # 湍流运动黏度
│   └── phi            # 穿过网格面的体积通量
├── constant/
├── system/
├── log.blockMesh
├── log.checkMesh
└── log.foamRun
```

用命令确认，而不是凭教程相信：

```bash
foamListTimes
tail -5 log.foamRun
grep -E 'Mesh OK|FOAM FATAL' log.checkMesh
```

## 2.7 看真实结果

![方腔流真实计算结果](images/cavity_result.png)

- A 图每个小方格是一个控制体，红线是运动上壁；
- B 图颜色是速度大小，白线沿速度方向弯曲。中心出现顺时针涡，符合运行前的预测；
- C 图是运动压力，不是 Pa，单位为 m²/s²。不可压缩 OpenFOAM 常把静压除以密度。

绘图的完整复现步骤在[第 6 课](06_python_visualization.md)。

## 费曼检查

1. `blockMesh` 的输入和输出各是什么？
2. `Mesh OK` 为什么不等于结果一定准确？
3. `0/` 与 `10/` 的本质区别是什么？
4. 2000 个时间步为什么只有约 20 个输出时间目录？
5. residual 为什么不能叫“与真实实验的误差”？
