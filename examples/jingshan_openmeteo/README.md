# 景山：Open-Meteo 与 ZBAA

第 5 课和第 6 课的算例。入口和两个侧面用 `inputs/boundary.csv`。表里是 2025-01-15 凌晨三个小时的风和位温，也有比湿，以及诊断的 `k` 与 `epsilon`。地面热通量在 `inputs/heatflux.csv`。来源和许可见 `DATA_SOURCE`。

## 怎么跑

在仓库根目录：

```bash
source ./env.sh
python3 -m pip install -r requirements-terrain.txt
cd examples/jingshan_openmeteo
./Allrun
```

`./Allrun` 用 `inputs/` 重写 `0/` 和 `constant/`，也重写 `system/`。接着跑 `checkMesh` 和 `foamRun -solver fluid`。没有现成 DEM 时，脚本裁公开 Copernicus COG 到 `work/terrain/beijing_jingshan_utm.tif`。

`./Allclean` 删时间目录和 VTK，也删日志和拷进算例的 DEM。网格和 `boundaryData` 留着。

## 预期

这台机器上网格是 4608 个格子。`endTime` 360，`deltaT` 2，写出 `120/` `240/` `360/`。日志里有 `Mesh OK`，求解以单独一行的 `End` 结束。`ExecutionTime` 是 4.01 s。

`bounding k` 从 t = 2 就有。t = 76 时上限被裁到 1.26×10⁴ m²/s²。t = 360 时上限 6.85 m²/s²，积分仍然走到 `End`。

图在 `tutorial/images/atm_*.png`，第 6 课逐张解释。重画：

```bash
CASE_DIR=examples/jingshan_openmeteo \
PREFIX=atm \
PROFILES=examples/jingshan_openmeteo/inputs/boundary.csv \
./plot_atmospheric.sh
```

先有时间目录再画。`./Allclean` 之后要重新 `./Allrun`。
