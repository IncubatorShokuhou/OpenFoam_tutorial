# 景山网格上的 ERA5 形状样本

第 7 课。`inputs/` 里的 NetCDF 用 ERA5 的短名，文件头写明它不是 CDS 下载。`./Allrun` 先解码，再在景山网格上积到 120 s。

## 怎么跑

```bash
source ./env.sh
python3 -m pip install -r requirements-era5.txt -r requirements-terrain.txt
cd examples/era5
./Allrun
```

没有 CDS 密钥也能跑。样本已经在 `inputs/`。真要下载 ERA5，用第 7 课里的 `fetch_era5_boundary.py` 命令，密钥只放 `~/.cdsapirc`。

## 预期

4608 个格子，`endTime` 120，`deltaT` 2。日志有 `Mesh OK` 和单独一行 `End`。这台机器上 `ExecutionTime` 是 1.42 s。t = 120 的图上风速 0.19 到 6.27 m/s，位温 267.9 到 277.4 K，比湿 0.793 到 0.800 g/kg。

图：`tutorial/images/era5_*.png`。

```bash
CASE_DIR=examples/era5 PREFIX=era5 \
PROFILES=examples/era5/inputs/boundary.csv \
./plot_atmospheric.sh
```

`./Allclean` 删结果，留下网格、`boundaryData` 和 `inputs/`。
