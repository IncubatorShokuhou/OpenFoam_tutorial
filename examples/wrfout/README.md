# 景山网格上的合成 wrfout

第 9 课。`inputs/wrfout_d01_synthetic.nc` 用 WRF 的变量名和错位维度，属性写明它不是预报。`./Allrun` 先消错位并投影，再写边界，然后积到 120 s。

## 怎么跑

```bash
source ./env.sh
python3 -m pip install -r requirements-wrf.txt -r requirements-terrain.txt
cd examples/wrfout
./Allrun
```

换成自己的 `wrfout` 时，仍要在命令里给 `--epsg`，以及 `--origin-x` 和 `--origin-y`。脚本不读 `MAP_PROJ`。

## 预期

4608 个格子。`Mesh OK`，单独一行 `End`。这台机器上 `ExecutionTime` 是 1.42 s。t = 120 的图上风速 0.42 到 7.39 m/s，位温 263.4 到 273.4 K，比湿 0.631 到 0.780 g/kg。

t = 22 的日志把 `k` 裁到约 2.1×10⁵ m²/s²。积分没有停，后面恢复，最后仍是 `End`。

图：`tutorial/images/wrf_*.png`。

```bash
CASE_DIR=examples/wrfout PREFIX=wrf \
PROFILES=examples/wrfout/inputs/boundary.csv \
./plot_atmospheric.sh
```
