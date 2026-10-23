# 第 3 课：看懂 `0/constant/system`

进入 `work/cavity`：

```bash
cd work/cavity
find 0 constant system -maxdepth 2 -type f | sort
```

## `0/`：初始场与边界条件

- `U` 是速度矢量场，量纲为 m/s；顶部 `movingWall` 给定运动速度。
- `p` 是运动压力（压力除以密度），不可压缩求解中常见量纲为 m²/s²。

文件中的 `internalField` 是域内初值，`boundaryField` 按 patch 名指定边界条件。patch 名必须
与网格边界中的名字一致。

## `constant/`：在整个计算期间基本不变的东西

- `physicalProperties` 描述黏度等物性。
- `momentumTransport` 选择层流或湍流模型。
- `polyMesh/` 由 `blockMesh` 生成，不建议手改。

## `system/`：怎样计算

- `controlDict`：求解模块、起止时间、时间步、写出频率。
- `blockMeshDict`：几何顶点、网格数和边界 patch。
- `fvSchemes`：梯度、散度、拉普拉斯项如何离散。
- `fvSolution`：线性求解器、容差与算法控制。

## 安全的小实验

先备份工作算例，然后把 `controlDict` 的结束时间改短：

```bash
cp -a work/cavity work/cavity_experiment
foamDictionary work/cavity_experiment/system/controlDict -entry endTime -set 0.2
foamRun -case work/cavity_experiment
```

`foamDictionary` 比用文本替换可靠，因为它理解 OpenFOAM 字典结构。
