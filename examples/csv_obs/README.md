# 景山网格上的观测宽表

第 10 课。`inputs/jingshan_obs_example.csv` 是填好的例子，`inputs/obs_template.csv` 是空表。`./Allrun` 检查列、换成边界 CSV，再在景山网格上积到 120 s。

## 怎么跑

```bash
source ./env.sh
python3 -m pip install -r requirements-terrain.txt
cd examples/csv_obs
./Allrun
```

换自己的表时，改 `Allrun` 里的 `--input`，并让 `--solver-times` 的个数等于不同的 UTC 时刻。`--epsg` 必须自己给。

## 预期

4608 个格子。`Mesh OK`，单独一行 `End`。这台机器上 `ExecutionTime` 是 1.43 s。t = 120 的图上风速 0.38 到 7.34 m/s，位温 252.7 到 276.5 K，比湿 0.628 到 1.35 g/kg。位温两头比入口柱宽，`bounding k` 在 t = 36 曾裁到约 2.5×10⁴ m²/s²。t = 120 时 `k` 的裁剪上限回到 6.43 m²/s²，求解仍走到 `End`。

图：`tutorial/images/csv_*.png`。

```bash
CASE_DIR=examples/csv_obs PREFIX=csv \
PROFILES=examples/csv_obs/inputs/boundary.csv \
./plot_atmospheric.sh
```
