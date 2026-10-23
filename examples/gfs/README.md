# 景山网格上的 GFS 柱

第 8 课。`inputs/boundary.csv` 来自 2025-01-15 00Z 的 GFS 0.25°，已经从 GRIB2 解码。`./Allrun` 不再访问 AWS，直接用这份 CSV 生成边界并求解。

## 怎么跑

```bash
source ./env.sh
python3 -m pip install -r requirements-terrain.txt
cd examples/gfs
./Allrun
```

要重新下载 GRIB 子集，再装 `requirements-gfs.txt`，命令在第 8 课。NOMADS 对这个历史周期返回过 HTTP 403，脚本走 AWS 的 `.idx` 字节范围。

## 预期

4608 个格子，积到 120 s。`Mesh OK`，单独一行 `End`。这台机器上 `ExecutionTime` 是 1.45 s。t = 120 的图上风速 1.13 到 7.36 m/s，位温 266.1 到 271.2 K，比湿 0.492 到 0.554 g/kg。

图：`tutorial/images/gfs_*.png`。

```bash
CASE_DIR=examples/gfs PREFIX=gfs \
PROFILES=examples/gfs/inputs/boundary.csv \
./plot_atmospheric.sh
```
