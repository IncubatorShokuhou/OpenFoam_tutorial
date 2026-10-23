#!/usr/bin/env python3
"""Fetch the Jingshan boundary tables without an API key.

Pressure levels, 10 m wind, 100 m wind and 2 m temperature come from the
Open-Meteo Historical Forecast API, model ``icon_global``. Checked on
2026-10-23, the ERA5 archive at archive-api.open-meteo.com accepts the same
pressure-level names and returns null, so this script does not pretend those
nulls are ERA5. ERA5 on that archive does return surface soil temperature,
2 m temperature and 10 m wind; those three drive the bulk heat flux.

NOAA/IEM ASOS at ZBAA supplies the surface wind when speed and direction are
both present. ZBAA temperature is warmer than this ICON column and would make
the lowest layer unstable in Boussinesq, so it is stored and not written into
``T``. Vertical velocity is absent from this API, so ``w_ms`` is 0. The CDS
script ``tools/fetch_era5_boundary.py`` remains the path that downloads ERA5
omega and sensible-heat flux.

The solver clock maps one real hour onto 10 s. ``time_s`` 0, 10 and 20 are
2025-01-15 00:00Z, 01:00Z and 02:00Z.
"""
import argparse
import csv
import json
import math
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atmospheric_case import (  # noqa: E402
    BULK_HEAT_CH,
    CP_AIR,
    GRAVITY,
    R_DRY,
    RHO0,
    TUTORIAL_DEM_TE,
    Z0_DIAG,
    _bracket,
    bulk_sensible_heat,
    diagnose_k_epsilon,
    ensure_tutorial_dem,
    potential_temperature,
    read_dem,
    specific_humidity,
    wind_components,
    write_heatflux_csv,
    write_landcover_csv,
    write_profile_csv,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tutorial" / "data"
FORECAST_API = "https://historical-forecast-api.open-meteo.com/v1/forecast"
ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"
IEM_API = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
WORLDCOVER_URL = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
    "ESA_WorldCover_10m_2021_v200_N39E114_Map.tif"
)
MODEL = "icon_global"
WEATHER_DATE = "2025-01-15"
# Requested points. ICON snaps them to its own grid; the saved lat/lon is the
# grid cell the API returns, not the request.
REQUEST_LATS = (39.90, 39.96)
REQUEST_LONS = (116.39, 116.39)
HOURS = ("2025-01-15T00:00", "2025-01-15T01:00", "2025-01-15T02:00")
CLOCK = (0.0, 10.0, 20.0)
PRESSURE_LEVELS = (1000, 975, 950)
KNOT_TO_MS = 0.514444
Z0_BY_CLASS = {
    10: (0.15, "tree"),
    20: (0.08, "shrub"),
    30: (0.03, "grass"),
    40: (0.05, "crop"),
    50: (0.20, "built"),
    60: (0.01, "bare"),
    80: (0.001, "water"),
    90: (0.05, "wetland"),
}


def fetch_bytes(url):
    request = urllib.request.Request(url, headers={"User-Agent": "openfoam-tutorial-fetch"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return response.read()


def fetch_json(url):
    return json.loads(fetch_bytes(url).decode("utf-8"))


def icon_url():
    hourly = [
        "temperature_2m", "relative_humidity_2m", "surface_pressure",
        "wind_speed_10m", "wind_direction_10m", "wind_speed_100m", "wind_direction_100m",
    ]
    for level in PRESSURE_LEVELS:
        hourly.extend([
            f"temperature_{level}hPa",
            f"relative_humidity_{level}hPa",
            f"wind_speed_{level}hPa",
            f"wind_direction_{level}hPa",
            f"geopotential_height_{level}hPa",
        ])
    query = urllib.parse.urlencode({
        "latitude": ",".join(str(value) for value in REQUEST_LATS),
        "longitude": ",".join(str(value) for value in REQUEST_LONS),
        "start_date": WEATHER_DATE,
        "end_date": WEATHER_DATE,
        "hourly": ",".join(hourly),
        "models": MODEL,
        "wind_speed_unit": "ms",
        "timezone": "GMT",
    })
    return f"{FORECAST_API}?{query}"


def era5_url():
    query = urllib.parse.urlencode({
        "latitude": "39.923",
        "longitude": "116.389",
        "start_date": WEATHER_DATE,
        "end_date": WEATHER_DATE,
        "hourly": ",".join([
            "temperature_2m", "wind_speed_10m", "soil_temperature_0_to_7cm",
            "shortwave_radiation", "surface_pressure",
        ]),
        "models": "era5",
        "wind_speed_unit": "ms",
        "timezone": "GMT",
    })
    return f"{ARCHIVE_API}?{query}"


def iem_url():
    query = urllib.parse.urlencode({
        "station": "ZBAA",
        "data": ["tmpf", "dwpf", "relh", "drct", "sknt", "mslp", "alti"],
        "year1": "2025", "month1": "1", "day1": "15",
        "year2": "2025", "month2": "1", "day2": "15",
        "tz": "Etc/UTC",
        "format": "onlycomma",
        "latlon": "yes",
        "missing": "M",
        "trace": "T",
        "direct": "no",
        "report_type": "3",
    }, doseq=True)
    return f"{IEM_API}?{query}"


def _hour_index(hourly, stamp):
    try:
        return hourly["time"].index(stamp)
    except ValueError as exc:
        raise SystemExit(f"Open-Meteo response has no {stamp}") from exc


def _f_to_c(text):
    if text in ("", "M"):
        return None
    return (float(text) - 32.0) * 5.0 / 9.0


def parse_iem(text):
    rows = []
    payload = [line for line in text.splitlines() if line and not line.startswith("#")]
    for row in csv.DictReader(payload):
        if row.get("station") != "ZBAA":
            continue
        speed = None if row["sknt"] in ("", "M") else float(row["sknt"]) * KNOT_TO_MS
        direction = None if row["drct"] in ("", "M") else float(row["drct"])
        rows.append({
            "valid": row["valid"],
            "lon": float(row["lon"]),
            "lat": float(row["lat"]),
            "tmp_c": _f_to_c(row["tmpf"]),
            "relh": None if row["relh"] in ("", "M") else float(row["relh"]),
            "direction_deg": direction,
            "speed_ms": speed,
            "mslp": None if row["mslp"] in ("", "M") else float(row["mslp"]),
            "alti_inhg": None if row["alti"] in ("", "M") else float(row["alti"]),
        })
    if not rows:
        raise SystemExit("IEM response contained no ZBAA rows")
    return rows


def iem_for_hour(rows, stamp):
    valid = stamp.replace("T", " ")
    for row in rows:
        if row["valid"] == valid:
            return row
    raise SystemExit(f"IEM file has no ZBAA row at {valid}")


def log_scale(speed, z_from, z_to, z0=Z0_DIAG):
    return float(speed) * math.log((z_to + z0) / z0) / math.log((z_from + z0) / z0)


def _mix(levels, z_m, key):
    heights = [row["z"] for row in levels]
    lower, upper, weight = _bracket(heights, z_m)
    return (1.0 - weight) * levels[lower][key] + weight * levels[upper][key]


def column_anchors(hourly, index, elevation):
    anchors = [{
        "z": 2.0,
        "t_c": float(hourly["temperature_2m"][index]),
        "rh": float(hourly["relative_humidity_2m"][index]),
        "p_pa": float(hourly["surface_pressure"][index]) * 100.0,
        "speed": float(hourly["wind_speed_10m"][index]),
        "direction": float(hourly["wind_direction_10m"][index]),
    }]
    for level in PRESSURE_LEVELS:
        height = float(hourly[f"geopotential_height_{level}hPa"][index]) - float(elevation)
        if height <= 5.0:
            continue
        anchors.append({
            "z": height,
            "t_c": float(hourly[f"temperature_{level}hPa"][index]),
            "rh": float(hourly[f"relative_humidity_{level}hPa"][index]),
            "p_pa": float(level) * 100.0,
            "speed": float(hourly[f"wind_speed_{level}hPa"][index]),
            "direction": float(hourly[f"wind_direction_{level}hPa"][index]),
        })
    anchors.sort(key=lambda row: row["z"])
    return anchors


def insert_wind_level(anchors, z_m, speed, direction):
    row = {
        "z": float(z_m),
        "t_c": _mix(anchors, z_m, "t_c"),
        "rh": _mix(anchors, z_m, "rh"),
        "p_pa": _mix(anchors, z_m, "p_pa"),
        "speed": float(speed),
        "direction": float(direction),
    }
    anchors.append(row)
    anchors.sort(key=lambda item: item["z"])
    return anchors


def profile_from_column(station, time_s, y_m, anchors, z0=Z0_DIAG):
    """One station column. ``anchors`` use absolute temperature, and z=2 is already the 2 m wind."""
    ordered = sorted(anchors, key=lambda row: row["z"])
    if ordered[0]["z"] != 2.0:
        raise SystemExit("column must include the 2 m level")
    speeds_u = []
    speeds_v = []
    heights = []
    for row in ordered:
        u_ms, v_ms = wind_components(row["speed"], row["direction"])
        speeds_u.append(u_ms)
        speeds_v.append(v_ms)
        heights.append(row["z"])
    k_values, epsilon = diagnose_k_epsilon(speeds_u, speeds_v, heights, z0)
    rows = []
    for index, row in enumerate(ordered):
        rows.append({
            "station": station,
            "time_s": time_s,
            "y_m": y_m,
            "z_m": row["z"],
            "u_ms": speeds_u[index],
            "v_ms": speeds_v[index],
            "w_ms": 0.0,
            "T_K": potential_temperature(row["t_c"], row["p_pa"]),
            "q_kgkg": specific_humidity(row["rh"], row["t_c"], row["p_pa"]),
            "p_Pa": row["p_pa"],
            "k_m2s2": float(k_values[index]),
            "epsilon_m2s3": float(epsilon[index]),
        })
    surface = ordered[0]
    density = surface["p_pa"] / (R_DRY * (surface["t_c"] + 273.15))
    ground = dict(rows[0])
    ground["z_m"] = 0.0
    ground["p_Pa"] = surface["p_pa"] + density * GRAVITY * 2.0
    ground["epsilon_m2s3"] = epsilon_at_ground(k_values[0], z0)
    rows.insert(0, ground)
    return rows


def epsilon_at_ground(k_value, z0):
    """epsilon = ustar^3 / (kappa z0), with ustar recovered from k = ustar^2 / sqrt(Cmu)."""
    cmu = 0.09
    ustar = math.sqrt(math.sqrt(cmu) * float(k_value))
    return ustar ** 3 / (0.41 * z0)


def build_boundary(icon_items, iem_rows, y_by_station):
    if len(icon_items) != 2:
        raise SystemExit(f"Expected two ICON cells, got {len(icon_items)}")
    ordered = sorted(icon_items, key=lambda item: float(item["latitude"]))
    names = ("south_icon", "north_icon")
    rows = []
    for station, item in zip(names, ordered):
        for time_s, stamp in zip(CLOCK, HOURS):
            index = _hour_index(item["hourly"], stamp)
            anchors = column_anchors(item["hourly"], index, item["elevation"])
            observed = iem_for_hour(iem_rows, stamp)
            if observed["speed_ms"] is not None and observed["direction_deg"] is not None:
                speed_10 = observed["speed_ms"]
                direction_10 = observed["direction_deg"]
            else:
                speed_10 = float(item["hourly"]["wind_speed_10m"][index])
                direction_10 = float(item["hourly"]["wind_direction_10m"][index])
            surface = next(row for row in anchors if row["z"] == 2.0)
            surface["speed"] = speed_10
            surface["direction"] = direction_10
            insert_wind_level(anchors, 10.0, speed_10, direction_10)
            insert_wind_level(
                anchors, 100.0,
                float(item["hourly"]["wind_speed_100m"][index]),
                float(item["hourly"]["wind_direction_100m"][index]),
            )
            surface["speed"] = log_scale(speed_10, 10.0, 2.0)
            rows.extend(profile_from_column(station, time_s, y_by_station[station], anchors))
    _require_stable(rows)
    return rows


def _require_stable(rows):
    for station in {row["station"] for row in rows}:
        for time_s in CLOCK:
            column = sorted(
                (row for row in rows if row["station"] == station and row["time_s"] == time_s),
                key=lambda row: row["z_m"],
            )
            theta = [row["T_K"] for row in column]
            if any(high + 1e-6 < low for low, high in zip(theta, theta[1:])):
                raise SystemExit(f"{station} at t={time_s} has potential temperature decreasing with height")


def station_y(icon_items, origin_y):
    import rasterio.warp

    ordered = sorted(icon_items, key=lambda item: float(item["latitude"]))
    names = ("south_icon", "north_icon")
    located = {}
    for station, item in zip(names, ordered):
        easting, northing = rasterio.warp.transform(
            "EPSG:4326", "EPSG:32650", [float(item["longitude"])], [float(item["latitude"])],
        )
        located[station] = float(northing[0]) - float(origin_y)
    return located


def write_icon_raw(path, icon_items, url):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="") as stream:
        stream.write(
            "# Open-Meteo Historical Forecast API, model icon_global.\n"
            f"# URL: {url}\n"
            "# Fetched 2026-10-23. lat/lon/elevation are the grid cell the API returned.\n"
            "# Units: temperature C, wind m/s, direction degrees, geopotential height m ASL,\n"
            "# surface_pressure hPa. Pressure-level pressure is the level itself.\n"
            "# archive-api.open-meteo.com?models=era5 returns null for these pressure-level names.\n"
        )
        fields = [
            "station", "utc", "latitude", "longitude", "elevation_m", "level",
            "z_asl_m", "z_agl_m", "t_c", "rh_percent", "wind_ms", "direction_deg", "p_hpa",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        ordered = sorted(icon_items, key=lambda item: float(item["latitude"]))
        for station, item in zip(("south_icon", "north_icon"), ordered):
            hourly = item["hourly"]
            for stamp in HOURS:
                index = _hour_index(hourly, stamp)
                elevation = float(item["elevation"])
                records = [(
                    "10m", elevation + 10.0, 10.0,
                    "", "",
                    hourly["wind_speed_10m"][index], hourly["wind_direction_10m"][index],
                    hourly["surface_pressure"][index],
                ), (
                    "100m", elevation + 100.0, 100.0,
                    "", "",
                    hourly["wind_speed_100m"][index], hourly["wind_direction_100m"][index],
                    "",
                ), (
                    "2m", elevation + 2.0, 2.0,
                    hourly["temperature_2m"][index], hourly["relative_humidity_2m"][index],
                    "", "",
                    hourly["surface_pressure"][index],
                )]
                for level in PRESSURE_LEVELS:
                    z_asl = float(hourly[f"geopotential_height_{level}hPa"][index])
                    records.append((
                        f"{level}hPa", z_asl, z_asl - elevation,
                        hourly[f"temperature_{level}hPa"][index],
                        hourly[f"relative_humidity_{level}hPa"][index],
                        hourly[f"wind_speed_{level}hPa"][index],
                        hourly[f"wind_direction_{level}hPa"][index],
                        level,
                    ))
                for level, z_asl, z_agl, t_c, rh, speed, direction, pressure in records:
                    writer.writerow({
                        "station": station,
                        "utc": stamp + "Z",
                        "latitude": f"{float(item['latitude']):.5f}",
                        "longitude": f"{float(item['longitude']):.5f}",
                        "elevation_m": f"{elevation:.4g}",
                        "level": level,
                        "z_asl_m": f"{z_asl:.6g}",
                        "z_agl_m": f"{z_agl:.6g}",
                        "t_c": "" if t_c == "" else f"{float(t_c):.4g}",
                        "rh_percent": "" if rh == "" else f"{float(rh):.4g}",
                        "wind_ms": "" if speed == "" else f"{float(speed):.4g}",
                        "direction_deg": "" if direction == "" else f"{float(direction):.4g}",
                        "p_hpa": "" if pressure == "" else f"{float(pressure):.6g}",
                    })


def write_era5_raw(path, payload, url):
    hourly = payload["hourly"]
    with path.open("w", encoding="ascii", newline="") as stream:
        stream.write(
            "# Open-Meteo archive API, model era5, surface fields only.\n"
            f"# URL: {url}\n"
            f"# Returned grid cell latitude {payload['latitude']} longitude {payload['longitude']}, "
            f"elevation {payload['elevation']} m. Fetched 2026-10-23.\n"
            "# q_Wm2 = rho*cp*CH*max(U10,0.5)*(Tsoil-T2m) with rho=1.2, cp=1004.5, CH=0.002.\n"
            "# This is not ERA5 surface_sensible_heat_flux. The CDS script downloads that flux.\n"
            "# shortwave_radiation is stored so the morning sun is visible; it is not the wall flux.\n"
        )
        writer = csv.DictWriter(stream, fieldnames=(
            "utc", "t2_c", "soil_0_7cm_c", "wind10_ms", "shortwave_Wm2", "surface_pressure_hpa", "q_Wm2",
        ))
        writer.writeheader()
        for index, stamp in enumerate(hourly["time"]):
            if stamp not in HOURS:
                continue
            heat = bulk_sensible_heat(
                hourly["wind_speed_10m"][index],
                hourly["soil_temperature_0_to_7cm"][index],
                hourly["temperature_2m"][index],
            )
            writer.writerow({
                "utc": stamp + "Z",
                "t2_c": f"{float(hourly['temperature_2m'][index]):.4g}",
                "soil_0_7cm_c": f"{float(hourly['soil_temperature_0_to_7cm'][index]):.4g}",
                "wind10_ms": f"{float(hourly['wind_speed_10m'][index]):.4g}",
                "shortwave_Wm2": f"{float(hourly['shortwave_radiation'][index]):.4g}",
                "surface_pressure_hpa": f"{float(hourly['surface_pressure'][index]):.6g}",
                "q_Wm2": f"{heat:.6g}",
            })
    return [
        {"time_s": time_s, "q_Wm2": bulk_sensible_heat(
            hourly["wind_speed_10m"][hourly["time"].index(stamp)],
            hourly["soil_temperature_0_to_7cm"][hourly["time"].index(stamp)],
            hourly["temperature_2m"][hourly["time"].index(stamp)],
        )}
        for time_s, stamp in zip(CLOCK, HOURS)
    ]


def write_iem_raw(path, text, url):
    path.write_text(
        "# NOAA/IEM ASOS, station ZBAA (Beijing Capital). Fetched 2026-10-23.\n"
        f"# URL: {url}\n"
        "# tmpf and dwpf are Fahrenheit, sknt is knots, drct is degrees, alti is inHg.\n"
        "# M is missing. 2025-01-15 02:00Z has no direction, so that hour keeps ICON 10 m wind.\n"
        "# mslp is missing for the day. Altimeter is not written into p_rgh.\n"
        "# The solver uses ZBAA wind at 00:00Z and 01:00Z. Temperature stays ICON so the\n"
        "# Boussinesq column remains stable. ZBAA is about 24 km northeast of Jingshan.\n"
        + text
        + ("" if text.endswith("\n") else "\n"),
        encoding="ascii",
    )


def ensure_worldcover(path):
    path = Path(path)
    if path.is_file() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["GDAL_DISABLE_READDIR_ON_OPEN"] = "EMPTY"
    env["CPL_VSIL_CURL_ALLOWED_EXTENSIONS"] = ".tif"
    env["GDAL_HTTP_TIMEOUT"] = "120"
    subprocess.run(
        [
            "gdalwarp", "-t_srs", "EPSG:32650", "-r", "near", "-tr", "30", "30",
            "-te", *(str(value) for value in TUTORIAL_DEM_TE),
            "/vsicurl/" + WORLDCOVER_URL, str(path),
        ],
        check=True,
        env=env,
    )
    return path


def landcover_rows(dem, worldcover_path):
    cover = read_dem(worldcover_path)
    if abs(cover["origin_x"] - dem["origin_x"]) > 0.1 or abs(cover["origin_y"] - dem["origin_y"]) > 0.1:
        raise SystemExit("WorldCover origin does not match the DEM origin. Refusing to guess a shift.")
    if cover["height"].shape != dem["height"].shape:
        raise SystemExit("WorldCover grid does not match the DEM grid.")
    rows = []
    for j, y_m in enumerate(cover["y"]):
        for i, x_m in enumerate(cover["x"]):
            code = int(round(cover["height"][j, i]))
            if code not in Z0_BY_CLASS:
                raise SystemExit(f"WorldCover class {code} has no z0 in the tutorial table")
            z0_m, name = Z0_BY_CLASS[code]
            rows.append({"x_m": float(x_m), "y_m": float(y_m), "z0_m": z0_m, "cover": name})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--dem", type=Path, default=None)
    parser.add_argument("--worldcover", type=Path, default=ROOT / "work" / "terrain" / "beijing_jingshan_worldcover.tif")
    args = parser.parse_args(argv)
    icon_request = icon_url()
    era5_request = era5_url()
    iem_request = iem_url()
    icon_items = fetch_json(icon_request)
    if isinstance(icon_items, dict):
        icon_items = [icon_items]
    for item in icon_items:
        unit = item["hourly_units"].get("temperature_950hPa")
        if unit in (None, "undefined") or item["hourly"]["temperature_950hPa"][0] is None:
            raise SystemExit("ICON pressure-level temperature came back empty")
    era5_payload = fetch_json(era5_request)
    iem_text = fetch_bytes(iem_request).decode("utf-8")
    iem_rows = parse_iem(iem_text)
    dem_path = ensure_tutorial_dem() if args.dem is None else args.dem
    dem = read_dem(dem_path)
    y_by_station = station_y(icon_items, dem["origin_y"])
    boundary = build_boundary(icon_items, iem_rows, y_by_station)
    data_dir = args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    write_icon_raw(data_dir / "beijing_icon_levels.csv", icon_items, icon_request)
    heat_rows = write_era5_raw(data_dir / "beijing_era5_surface.csv", era5_payload, era5_request)
    write_iem_raw(data_dir / "beijing_iem_zbaa.csv", iem_text, iem_request)
    south = next(item for item in sorted(icon_items, key=lambda item: float(item["latitude"])))
    north = sorted(icon_items, key=lambda item: float(item["latitude"]))[-1]
    comment = (
        "# Jingshan inlet table for the tutorial solver clock.\n"
        "# Site clip: Copernicus GLO-30, EPSG:32650, "
        f"te {TUTORIAL_DEM_TE[0]} {TUTORIAL_DEM_TE[1]} {TUTORIAL_DEM_TE[2]} {TUTORIAL_DEM_TE[3]}.\n"
        "# WGS84 of that clip is about 39.921N-39.926N, 116.385E-116.394E, inside the\n"
        "# download_dem.sh box 39.85-39.95 N, 116.30-116.45 E.\n"
        f"# Upper air: Open-Meteo {FORECAST_API} model {MODEL}, fetched 2026-10-23.\n"
        f"# South cell {float(south['latitude']):.5f}N {float(south['longitude']):.5f}E "
        f"elev {south['elevation']} m, local y {y_by_station['south_icon']:.3f} m.\n"
        f"# North cell {float(north['latitude']):.5f}N {float(north['longitude']):.5f}E "
        f"elev {north['elevation']} m, local y {y_by_station['north_icon']:.3f} m.\n"
        "# time_s 0, 10, 20 map to 2025-01-15 00:00Z, 01:00Z, 02:00Z. One hour of weather\n"
        "# is 10 s of CFD. The run does not integrate those two hours.\n"
        "# T_K is dry potential temperature at 100000 Pa. z_m is metres above the ICON\n"
        "# orography, and the case looks the profile up the same way above the DEM.\n"
        "# 10 m wind at 00:00Z and 01:00Z is ZBAA (IEM ASOS), converted with 0.514444 m/s per knot.\n"
        "# 02:00Z ZBAA direction is missing, so that hour keeps ICON 10 m wind.\n"
        "# ZBAA temperature is not used: it is warmer than this column and would be unstable.\n"
        "# w_ms is 0 because this API has no vertical velocity. k and epsilon are diagnosed\n"
        f"# with z0={Z0_DIAG} m from the lowest level at or above 2 m. p_Pa is the level pressure.\n"
        f"# ICON request: {icon_request}\n"
    )
    write_profile_csv(data_dir / "beijing_boundary.csv", boundary, comment=comment)
    heat_comment = (
        "# Ground sensible-heat flux into the air, W/m2, for externalTemperature.\n"
        "# Derived from ERA5 via the Open-Meteo archive, not from ERA5 sshf.\n"
        f"# H = {RHO0} * {CP_AIR} * {BULK_HEAT_CH} * max(U10, 0.5) * (Tsoil - T2m).\n"
        "# ERA5 grid cell and inputs: beijing_era5_surface.csv. Positive heats the fluid.\n"
        "# time_s uses the same 00:00Z / 01:00Z / 02:00Z compression as beijing_boundary.csv.\n"
    )
    write_heatflux_csv(data_dir / "beijing_heatflux.csv", heat_rows, comment=heat_comment)
    worldcover = ensure_worldcover(args.worldcover)
    cover_comment = (
        "# Aerodynamic roughness for the Jingshan clip, local metres of the DEM.\n"
        "# Class is ESA WorldCover 2021 v200, tile N39E114, nearest neighbour onto the 30 m DEM.\n"
        f"# Source: {WORLDCOVER_URL}\n"
        "# z0 lookup: tree 0.15, shrub 0.08, grass 0.03, crop 0.05, built 0.20, bare 0.01,\n"
        "# water 0.001, wetland 0.05. Built-up z0 is capped at 0.20 m so Ks=20*z0 stays\n"
        "# under the first cell. A city z0 near 1 m does not fit this mesh.\n"
        "# OpenFOAM has no land-cover reader. prepare writes Ks = 20*z0 on ground faces.\n"
    )
    write_landcover_csv(
        data_dir / "beijing_landcover_z0.csv",
        landcover_rows(dem, worldcover),
        comment=cover_comment,
    )
    print(f"Wrote tutorial tables in {data_dir}")
    print(f"stations y: {y_by_station}")
    print(f"DEM origin {dem['origin_x']:.3f} {dem['origin_y']:.3f} shape {dem['height'].shape}")


if __name__ == "__main__":
    main()
