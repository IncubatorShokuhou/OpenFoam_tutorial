# 五个可以直接跑的景山算例

网格都是第 5 课那一块 Copernicus 裁剪：水平 720 m × 480 m，24 × 16 × 12，共 4608 个六面体。DEM 栅格不放进这些目录，`./Allrun` 需要时再裁公开 COG。每个目录的 `DATA_SOURCE` 写来源和日期，也写位置和许可。

| 目录 | 驱动数据 | 求解时间 | 对应课 |
|---|---|---|---|
| [jingshan_openmeteo](jingshan_openmeteo/README.md) | Open-Meteo ICON 加 ZBAA，真实小表 | 0 到 360 s | 第 5 课、第 6 课 |
| [era5](era5/README.md) | 标明合成的 ERA5 形状 NetCDF | 0 到 120 s | 第 7 课 |
| [gfs](gfs/README.md) | NOAA GFS 0.25°，2025-01-15 00Z，已解码的真实柱 | 0 到 120 s | 第 8 课 |
| [wrfout](wrfout/README.md) | 标明合成的 wrfout | 0 到 120 s | 第 9 课 |
| [csv_obs](csv_obs/README.md) | 由景山表改写的观测宽表示例 | 0 到 120 s | 第 10 课 |

在仓库根目录先 `source ./env.sh`。进入某个目录后执行 `./Allrun`。成功时最后一行是 `Success:`，求解日志里有单独一行 `End`。`./Allclean` 删掉时间目录和 VTK，也删日志。`0/` 和网格留着，`inputs/` 也留着。
