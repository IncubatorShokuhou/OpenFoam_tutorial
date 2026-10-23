#!/usr/bin/env python3
"""Build the tutorial atmospheric case from a projected DEM and a met table.

The command-line default clips Copernicus GLO-30 over Jingshan, inside the
Beijing box used by ``download_dem.sh``, and reads the committed Open-Meteo
and IEM tables. ``sample_hill=True`` is only the synthetic unit-test terrain.
"""
import argparse
import csv
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CASE_TEMPLATE = ROOT / "cases" / "atmospheric"
DEFAULT_PROFILES = ROOT / "tutorial" / "data" / "beijing_boundary.csv"
DEFAULT_LANDCOVER = ROOT / "tutorial" / "data" / "beijing_landcover_z0.csv"
DEFAULT_HEATFLUX = ROOT / "tutorial" / "data" / "beijing_heatflux.csv"
# Public Copernicus GLO-30 COG. No OpenTopography key. The window is Jingshan,
# inside the download_dem.sh example box 39.85-39.95 N, 116.30-116.45 E.
TUTORIAL_DEM_URL = (
    "https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/"
    "Copernicus_DSM_COG_10_N39_00_E116_00_DEM/"
    "Copernicus_DSM_COG_10_N39_00_E116_00_DEM.tif"
)
# EPSG:32650 metres: west, south, east, north. 25 by 17 pixels of 30 m.
TUTORIAL_DEM_TE = (447420.0, 4419180.0, 448170.0, 4419690.0)
TUTORIAL_DEM = ROOT / "work" / "terrain" / "beijing_jingshan_utm.tif"

RHO0 = 1.2
GRAVITY = 9.81
P_REF = 101325.0
T_REF = 290.0
BETA = 1.0 / T_REF
KAPPA = 0.41
CMU = 0.09
Z0_LOG = 0.05
# Roughness used only when diagnosing k and epsilon from a speed profile.
Z0_DIAG = 0.10
# Hargreaves & Wright: sand-grain height used with the rough-wall function.
KS_PER_Z0 = 20.0
# Bulk transfer coefficient for the derived sensible-heat flux. Not an ERA5 field.
BULK_HEAT_CH = 0.002
CP_AIR = 1004.5
R_DRY = 287.05
SAMPLE_EPSG = 32650
SAMPLE_EASTING0 = 450000.0
SAMPLE_NORTHING0 = 4423000.0
SAMPLE_DX = 25.0
SAMPLE_NX = 20
SAMPLE_NY = 12
PRGH_LIMIT = 5.0


def foam_header(class_name, location, object_name):
    return (
        "FoamFile\n"
        "{\n"
        "    format      ascii;\n"
        f"    class       {class_name};\n"
        f"    location    \"{location}\";\n"
        f"    object      {object_name};\n"
        "}\n"
    )


def write_foam(path, class_name, location, object_name, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(foam_header(class_name, location, object_name) + "\n" + body + "\n", encoding="ascii")


def sample_hill(x, y):
    """Synthetic hill in local metres. Inlet side (small x) stays nearly flat."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    main = 28.0 * np.exp(-((x - 320.0) ** 2 + (y - 150.0) ** 2) / (2.0 * 90.0 ** 2))
    shoulder = 10.0 * np.exp(-((x - 150.0) ** 2 + (y - 70.0) ** 2) / (2.0 * 55.0 ** 2))
    return main + shoulder


def sample_log_wind(z, ustar):
    z = np.asarray(z, dtype=float)
    return ustar / KAPPA * np.log((z + Z0_LOG) / Z0_LOG)


def build_sample_profiles():
    """Two masts, three tutorial times, six heights.

    ``T_K`` is potential temperature. Boussinesq has no adiabatic lapse, so a
    stable layer is an increase of this value with height. ``p_Pa`` is a
    constant-density hydrostatic profile plus a 1 Pa-scale residual.
    ``k`` and ``epsilon`` follow the neutral ABL expressions; ERA5 does not
    carry those two fields.
    """
    times = (0.0, 10.0, 20.0)
    heights = (0.0, 5.0, 20.0, 50.0, 100.0, 160.0, 240.0)
    stations = (
        ("south_mast", 40.0, 1.0, 0.10, 0.0, 0.0),
        ("north_mast", 260.0, 0.90, 0.22, 0.25, -0.0004),
    )
    rows = []
    for time in times:
        for station, y_m, speed_scale, v_factor, t_shift, q_shift in stations:
            ustar = 0.32 * (1.0 + 0.12 * time / 20.0) * speed_scale
            k_value = ustar ** 2 / math.sqrt(CMU)
            for z_m in heights:
                u_ms = float(sample_log_wind(z_m, ustar))
                rows.append({
                    "station": station,
                    "time_s": time,
                    "y_m": y_m,
                    "z_m": z_m,
                    "u_ms": u_ms,
                    "v_ms": v_factor * u_ms,
                    "w_ms": 0.03 * math.exp(-z_m / 120.0),
                    "T_K": T_REF + 0.015 * z_m + 0.05 * (time / 20.0) + t_shift,
                    "q_kgkg": max(0.001, 0.0085 - 1.5e-5 * z_m - 0.0002 * (time / 20.0) + q_shift),
                    "p_Pa": P_REF - RHO0 * GRAVITY * z_m + 1.2 * math.sin(z_m / 70.0 + time / 20.0),
                    "k_m2s2": k_value,
                    "epsilon_m2s3": ustar ** 3 / (KAPPA * (z_m + Z0_LOG)),
                })
    return rows


PROFILE_FIELDS = (
    "station", "time_s", "y_m", "z_m", "u_ms", "v_ms", "w_ms",
    "T_K", "q_kgkg", "p_Pa", "k_m2s2", "epsilon_m2s3",
)
PROFILE_COMMENT = (
    "# SAMPLE meteorological boundary table for the tutorial clock.\n"
    "# Not an ERA5 file. time_s is 0, 10 and 20 s so a short OpenFOAM run can\n"
    "# interpolate it. T_K is potential temperature. p_Pa is hydrostatic at\n"
    "# rho=1.2 kg/m3 plus a residual of about 1 Pa. k and epsilon are diagnosed\n"
    "# from a log-law friction velocity because reanalysis does not store them.\n"
    "# Two stations share the same heights so the inlet can vary in y.\n"
)


def write_profile_csv(path, rows, comment=PROFILE_COMMENT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="") as stream:
        stream.write(comment if comment.endswith("\n") else comment + "\n")
        writer = csv.DictWriter(stream, fieldnames=PROFILE_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: row[key] if key == "station" else f"{float(row[key]):.8g}"
                for key in PROFILE_FIELDS
            })


def build_sample_landcover():
    rows = []
    for x_m in range(0, 501, 50):
        for y_m in range(0, 301, 50):
            if 200 <= x_m <= 400 and 75 <= y_m <= 225:
                z0_m, cover = 0.15, "woodland"
            elif y_m <= 50:
                z0_m, cover = 0.01, "short_grass"
            else:
                z0_m, cover = 0.03, "grass"
            rows.append({"x_m": x_m, "y_m": y_m, "z0_m": z0_m, "cover": cover})
    return rows


def write_landcover_csv(path, rows, comment=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if comment is None:
        comment = (
            "# SAMPLE aerodynamic roughness. Local metres, same origin as the\n"
            "# synthetic hill. OpenFOAM has no land-cover reader; prepare maps\n"
            "# z0_m onto ground faces as Ks = 20*z0.\n"
        )
    with path.open("w", encoding="ascii", newline="") as stream:
        stream.write(comment if comment.endswith("\n") else comment + "\n")
        writer = csv.DictWriter(stream, fieldnames=("x_m", "y_m", "z0_m", "cover"))
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "x_m": f"{row['x_m']:.8g}",
                "y_m": f"{row['y_m']:.8g}",
                "z0_m": f"{row['z0_m']:.8g}",
                "cover": row["cover"],
            })


def build_sample_heatflux():
    return [
        {"time_s": 0.0, "q_Wm2": 25.0},
        {"time_s": 10.0, "q_Wm2": 35.0},
        {"time_s": 20.0, "q_Wm2": 30.0},
    ]


def write_heatflux_csv(path, rows, comment=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if comment is None:
        comment = (
            "# SAMPLE ground sensible-heat flux into the air, W/m2.\n"
            "# Positive values heat the first cell through externalTemperature.\n"
            "# ERA5 surface_sensible_heat_flux is an accumulated energy, not this unit.\n"
        )
    with path.open("w", encoding="ascii", newline="") as stream:
        stream.write(comment if comment.endswith("\n") else comment + "\n")
        writer = csv.DictWriter(stream, fieldnames=("time_s", "q_Wm2"))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: f"{float(row[key]):.8g}" for key in ("time_s", "q_Wm2")})


def read_csv_records(path):
    lines = Path(path).read_text(encoding="ascii").splitlines()
    payload = "\n".join(line for line in lines if not line.startswith("#"))
    return list(csv.DictReader(payload.splitlines()))


def load_profiles(path):
    records = []
    for row in read_csv_records(path):
        item = {"station": row["station"]}
        for key in PROFILE_FIELDS[1:]:
            item[key] = float(row[key])
        records.append(item)
    if len({row["station"] for row in records}) < 1:
        raise ValueError(f"No stations in {path}")
    return records


def load_landcover(path):
    rows = []
    for row in read_csv_records(path):
        rows.append({
            "x_m": float(row["x_m"]),
            "y_m": float(row["y_m"]),
            "z0_m": float(row["z0_m"]),
            "cover": row["cover"],
        })
    return rows


def load_heatflux(path):
    return [
        {"time_s": float(row["time_s"]), "q_Wm2": float(row["q_Wm2"])}
        for row in read_csv_records(path)
    ]


def _bracket(sorted_values, target):
    if target <= sorted_values[0]:
        return 0, 0, 0.0
    if target >= sorted_values[-1]:
        last = len(sorted_values) - 1
        return last, last, 0.0
    upper = int(np.searchsorted(sorted_values, target))
    lower = upper - 1
    span = sorted_values[upper] - sorted_values[lower]
    weight = 0.0 if span == 0 else (target - sorted_values[lower]) / span
    return lower, upper, float(weight)


def _column_at(records, station, time_value, z_m):
    rows = [row for row in records if row["station"] == station and row["time_s"] == time_value]
    if not rows:
        raise KeyError(f"{station} has no column at t={time_value}")
    heights = sorted(row["z_m"] for row in rows)
    by_z = {row["z_m"]: row for row in rows}
    lower, upper, weight = _bracket(heights, z_m)
    sample = {}
    for key in ("u_ms", "v_ms", "w_ms", "T_K", "q_kgkg", "p_Pa", "k_m2s2", "epsilon_m2s3"):
        sample[key] = (1.0 - weight) * by_z[heights[lower]][key] + weight * by_z[heights[upper]][key]
    return rows[0]["y_m"], sample


def interpolate_profile(records, time_s, y_m, z_m):
    """Linear in time, then y, then z. Outside the table the edge value is kept.

    Height levels may differ between stations and between times, which is what
    a pressure-level geopotential does. Each column is interpolated in z on
    its own before the time and y blends.
    """
    times = sorted({row["time_s"] for row in records})
    t0, t1, wt = _bracket(times, time_s)
    stations = sorted({row["station"] for row in records})

    def blended(time_value):
        columns = []
        for station in stations:
            y_value, sample = _column_at(records, station, time_value, z_m)
            columns.append((y_value, sample))
        columns.sort(key=lambda item: item[0])
        ys = [item[0] for item in columns]
        y0, y1, wy = _bracket(ys, y_m)
        return {
            key: (1.0 - wy) * columns[y0][1][key] + wy * columns[y1][1][key]
            for key in columns[0][1]
        }

    early = blended(times[t0])
    late = blended(times[t1])
    return {key: (1.0 - wt) * early[key] + wt * late[key] for key in early}


def dynamic_pressure(pressure, height, p_ref=P_REF, rho=RHO0, gravity=GRAVITY, limit=PRGH_LIMIT):
    """Remove rho*g*z and the column-mean mismatch. Clamp the remainder.

    OpenFOAM's ``p_rgh`` on this Boussinesq setup is a small perturbation.
    A raw ERA5 pressure profile is absolute and will not match ``rho0``.
    """
    pressure = np.asarray(pressure, dtype=float)
    height = np.asarray(height, dtype=float)
    residual = pressure - (p_ref - rho * gravity * height)
    anomaly = residual - np.mean(residual)
    peak = float(np.max(np.abs(anomaly))) if anomaly.size else 0.0
    clamped = peak > limit
    if clamped and peak > 0:
        anomaly = anomaly * (limit / peak)
    return anomaly, clamped


def omega_to_w(omega_pa_s, temperature, pressure):
    """ERA5 vertical velocity is Pa/s. Convert with w = -omega / (rho g)."""
    omega_pa_s = np.asarray(omega_pa_s, dtype=float)
    temperature = np.asarray(temperature, dtype=float)
    pressure = np.asarray(pressure, dtype=float)
    rho = pressure / (R_DRY * temperature)
    return -omega_pa_s / (rho * GRAVITY)


def wind_components(speed_ms, direction_deg):
    """Meteorological direction (degrees from north, coming from) to u east, v north."""
    radians = math.radians(float(direction_deg))
    speed = float(speed_ms)
    return -speed * math.sin(radians), -speed * math.cos(radians)


def potential_temperature(temperature_c, pressure_pa, p_ref=1.0e5):
    """Dry potential temperature. ``temperature_c`` is absolute, not theta."""
    temperature_k = float(temperature_c) + 273.15
    return temperature_k * (p_ref / float(pressure_pa)) ** (R_DRY / CP_AIR)


def specific_humidity(rh_percent, temperature_c, pressure_pa):
    """Bolton saturation vapour pressure, then q = 0.622 e / (p - 0.378 e)."""
    temperature_c = float(temperature_c)
    saturation = 611.2 * math.exp(17.67 * temperature_c / (temperature_c + 243.5))
    vapour = max(0.0, min(100.0, float(rh_percent))) / 100.0 * saturation
    pressure_pa = float(pressure_pa)
    return 0.622 * vapour / (pressure_pa - 0.378 * vapour)


def bulk_sensible_heat(wind_10m, soil_c, air_2m_c, rho=RHO0, ch=BULK_HEAT_CH):
    """H = rho cp CH U10 (Tsoil - T2m), watts per square metre into the air."""
    return float(rho) * CP_AIR * float(ch) * max(float(wind_10m), 0.5) * (
        float(soil_c) - float(air_2m_c)
    )


def deaccumulate(energy, step_seconds):
    """Turn an accumulated flux (J/m2 from the run start) into W/m2."""
    energy = np.asarray(energy, dtype=float)
    if energy.shape[0] < 2:
        raise ValueError("Need at least two accumulated samples")
    watts = np.empty_like(energy)
    watts[0] = energy[0] / step_seconds
    watts[1:] = np.diff(energy) / step_seconds
    return watts


def diagnose_k_epsilon(u_ms, v_ms, z_m, z0):
    """Diagnose k and epsilon from one column. Inputs are 1-D and share an index."""
    speed = np.hypot(np.asarray(u_ms, dtype=float), np.asarray(v_ms, dtype=float))
    z_m = np.asarray(z_m, dtype=float)
    if speed.ndim != 1 or z_m.shape != speed.shape:
        raise ValueError("u, v and z must be 1-D arrays of the same length")
    if np.any(z_m + z0 <= 0):
        raise ValueError("z + z0 must be positive")
    lowest = int(np.argmin(z_m))
    ustar = KAPPA * speed[lowest] / math.log((z_m[lowest] + z0) / z0)
    k_value = np.full(speed.shape, ustar ** 2 / math.sqrt(CMU))
    epsilon = ustar ** 3 / (KAPPA * (z_m + z0))
    return k_value, epsilon


def write_sample_dem(path, nx=SAMPLE_NX, ny=SAMPLE_NY, dx=SAMPLE_DX):
    import rasterio
    from rasterio.transform import from_origin

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = nx + 1
    rows = ny + 1
    x = np.arange(cols) * dx
    y = np.arange(rows) * dx
    xx, yy = np.meshgrid(x, y)
    height = sample_hill(xx, yy).astype(np.float32)
    # Row 0 is the northern edge so the GeoTIFF is north-up.
    stored = height[::-1, :]
    west = SAMPLE_EASTING0 - 0.5 * dx
    north = SAMPLE_NORTHING0 + y[-1] + 0.5 * dx
    transform = from_origin(west, north, dx, dx)
    with rasterio.open(
        path, "w", driver="GTiff", height=rows, width=cols, count=1,
        dtype="float32", crs=f"EPSG:{SAMPLE_EPSG}", transform=transform, nodata=-9999.0,
    ) as dataset:
        dataset.write(stored, 1)
        dataset.update_tags(
            tutorial_note="SAMPLE synthetic hill for the atmospheric lesson, not a Copernicus tile",
            vertical_units="m",
        )
    return path


def read_dem(path, stride=1):
    import rasterio

    path = Path(path)
    with rasterio.open(path) as src:
        if src.crs is None or src.crs.is_geographic:
            raise SystemExit(
                f"{path} must use a projected CRS in metres. "
                "Reproject with gdalwarp and pass the result. This script does not choose a CRS."
            )
        if src.transform.b != 0 or src.transform.d != 0:
            raise SystemExit(f"{path} is rotated. Write a north-up GeoTIFF first.")
        values = src.read(1, masked=True)[::stride, ::stride]
        transform = src.transform
        rows = np.arange(0, src.height, stride)[: values.shape[0]]
        cols = np.arange(0, src.width, stride)[: values.shape[1]]
        x = transform.c + (cols + 0.5) * transform.a
        y = transform.f + (rows + 0.5) * transform.e
        crs = src.crs.to_string()
    if np.ma.is_masked(values) and np.ma.is_masked(values).any():
        raise SystemExit(f"{path} contains NoData. Fill the holes before meshing.")
    height = np.asarray(values, dtype=float)
    if y.size > 1 and y[1] < y[0]:
        y = y[::-1]
        height = height[::-1, :]
    origin_x = float(x.min())
    origin_y = float(y.min())
    return {
        "x": x - origin_x,
        "y": y - origin_y,
        "height": height,
        "origin_x": origin_x,
        "origin_y": origin_y,
        "crs": crs,
    }


def layer_nodes(nz, growth):
    if nz < 1:
        raise ValueError("nz must be >= 1")
    if growth <= 0:
        raise ValueError("growth must be positive")
    weights = np.power(float(growth), np.arange(nz, dtype=float))
    weights /= weights.sum()
    nodes = np.zeros(nz + 1)
    nodes[1:] = np.cumsum(weights)
    return nodes


def build_hex_mesh(x, y, ground, h_air, nz, growth=1.10):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ground = np.asarray(ground, dtype=float)
    nx = x.size - 1
    ny = y.size - 1
    if ground.shape != (ny + 1, nx + 1):
        raise ValueError("ground height must have shape (ny+1, nx+1)")
    eta = layer_nodes(nz, growth)
    points = np.empty(((nx + 1) * (ny + 1) * (nz + 1), 3))

    def pid(i, j, k):
        return i + (nx + 1) * (j + (ny + 1) * k)

    for k in range(nz + 1):
        for j in range(ny + 1):
            for i in range(nx + 1):
                points[pid(i, j, k)] = (
                    x[i], y[j], ground[j, i] + h_air * eta[k]
                )

    def cell(i, j, k):
        return i + nx * (j + ny * k)

    faces = []
    owner = []
    neighbour = []

    def add(face, own, nei=None):
        faces.append(tuple(face))
        owner.append(own)
        if nei is not None:
            neighbour.append(nei)

    for k in range(nz):
        for j in range(ny):
            for i in range(nx - 1):
                add((
                    pid(i + 1, j, k), pid(i + 1, j + 1, k),
                    pid(i + 1, j + 1, k + 1), pid(i + 1, j, k + 1),
                ), cell(i, j, k), cell(i + 1, j, k))
    for k in range(nz):
        for j in range(ny - 1):
            for i in range(nx):
                add((
                    pid(i, j + 1, k), pid(i, j + 1, k + 1),
                    pid(i + 1, j + 1, k + 1), pid(i + 1, j + 1, k),
                ), cell(i, j, k), cell(i, j + 1, k))
    for k in range(nz - 1):
        for j in range(ny):
            for i in range(nx):
                add((
                    pid(i, j, k + 1), pid(i + 1, j, k + 1),
                    pid(i + 1, j + 1, k + 1), pid(i, j + 1, k + 1),
                ), cell(i, j, k), cell(i, j, k + 1))
    n_internal = len(faces)

    patches = {}

    def add_patch(name, face_iter):
        start = len(faces)
        count = 0
        for face, own in face_iter:
            add(face, own, None)
            count += 1
        patches[name] = {"start": start, "count": count}

    add_patch("inlet", (
        ((pid(0, j, k), pid(0, j, k + 1), pid(0, j + 1, k + 1), pid(0, j + 1, k)), cell(0, j, k))
        for k in range(nz) for j in range(ny)
    ))
    add_patch("outlet", (
        ((
            pid(nx, j, k), pid(nx, j + 1, k), pid(nx, j + 1, k + 1), pid(nx, j, k + 1),
        ), cell(nx - 1, j, k))
        for k in range(nz) for j in range(ny)
    ))
    add_patch("ground", (
        ((
            pid(i, j, 0), pid(i, j + 1, 0), pid(i + 1, j + 1, 0), pid(i + 1, j, 0),
        ), cell(i, j, 0))
        for j in range(ny) for i in range(nx)
    ))
    add_patch("top", (
        ((
            pid(i, j, nz), pid(i + 1, j, nz), pid(i + 1, j + 1, nz), pid(i, j + 1, nz),
        ), cell(i, j, nz - 1))
        for j in range(ny) for i in range(nx)
    ))
    add_patch("front", (
        ((
            pid(i, 0, k), pid(i + 1, 0, k), pid(i + 1, 0, k + 1), pid(i, 0, k + 1),
        ), cell(i, 0, k))
        for k in range(nz) for i in range(nx)
    ))
    add_patch("back", (
        ((
            pid(i, ny, k), pid(i, ny, k + 1), pid(i + 1, ny, k + 1), pid(i + 1, ny, k),
        ), cell(i, ny - 1, k))
        for k in range(nz) for i in range(nx)
    ))
    return {
        "points": points,
        "faces": faces,
        "owner": np.asarray(owner, dtype=int),
        "neighbour": np.asarray(neighbour, dtype=int),
        "n_internal": n_internal,
        "patches": patches,
        "nx": nx,
        "ny": ny,
        "nz": nz,
        "x": x,
        "y": y,
        "ground": ground,
        "h_air": float(h_air),
    }


def cell_count(mesh):
    return mesh["nx"] * mesh["ny"] * mesh["nz"]


def cell_centers(mesh):
    centers = np.zeros((cell_count(mesh), 3))
    counts = np.zeros(cell_count(mesh), dtype=int)
    for face, own in zip(mesh["faces"], mesh["owner"]):
        centers[own] += mesh["points"][list(face)].mean(axis=0)
        counts[own] += 1
    for face, nei in zip(mesh["faces"][: mesh["n_internal"]], mesh["neighbour"]):
        centers[nei] += mesh["points"][list(face)].mean(axis=0)
        counts[nei] += 1
    if np.any(counts != 6):
        raise RuntimeError("Every hex cell should meet 6 faces")
    return centers / counts[:, None]


def _fmt_scalar(value):
    return f"{float(value):.8g}"


def _list_body(values, indent="    "):
    return "\n".join(indent + line for line in values)


def write_poly_mesh(mesh, directory):
    directory = Path(directory)
    points = "\n".join(
        f"({_fmt_scalar(p[0])} {_fmt_scalar(p[1])} {_fmt_scalar(p[2])})"
        for p in mesh["points"]
    )
    write_foam(
        directory / "points", "vectorField", "constant/polyMesh", "points",
        f"{len(mesh['points'])}\n(\n{points}\n)",
    )
    faces = "\n".join("4(" + " ".join(str(index) for index in face) + ")" for face in mesh["faces"])
    write_foam(
        directory / "faces", "faceList", "constant/polyMesh", "faces",
        f"{len(mesh['faces'])}\n(\n{faces}\n)",
    )
    owner = "\n".join(str(int(value)) for value in mesh["owner"])
    write_foam(
        directory / "owner", "labelList", "constant/polyMesh", "owner",
        f"{len(mesh['owner'])}\n(\n{owner}\n)",
    )
    neighbour = "\n".join(str(int(value)) for value in mesh["neighbour"])
    write_foam(
        directory / "neighbour", "labelList", "constant/polyMesh", "neighbour",
        f"{len(mesh['neighbour'])}\n(\n{neighbour}\n)",
    )
    blocks = []
    for name, patch in mesh["patches"].items():
        # Wall functions (nut, k, epsilon, alphat) require the ground type wall.
        patch_type = "wall" if name == "ground" else "patch"
        blocks.append(
            f"    {name}\n"
            "    {\n"
            f"        type {patch_type};\n"
            f"        nFaces {patch['count']};\n"
            f"        startFace {patch['start']};\n"
            "    }"
        )
    write_foam(
        directory / "boundary", "polyBoundaryMesh", "constant/polyMesh", "boundary",
        f"{len(blocks)}\n(\n" + "\n".join(blocks) + "\n)",
    )


def write_mapped_cloud(path, values):
    """Field file read by timeVaryingMappedFixedValue with setAverage off."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if values.ndim == 1:
        body = "\n".join(_fmt_scalar(value) for value in values)
    else:
        body = "\n".join(
            "(" + " ".join(_fmt_scalar(component) for component in row) + ")"
            for row in values
        )
    path.write_text(f"{len(values)}\n(\n{body}\n)\n", encoding="ascii")


def write_points_cloud(path, points):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(
        "(" + " ".join(_fmt_scalar(component) for component in row) + ")"
        for row in points
    )
    path.write_text(f"{len(points)}\n(\n{body}\n)\n", encoding="ascii")


def plane_sample_points(x_const, y_nodes, z_min, z_max, n_y=6, n_z=8):
    y_values = np.linspace(float(y_nodes[0]), float(y_nodes[-1]), n_y)
    z_values = np.linspace(z_min, z_max, n_z)
    ordered = [
        (x_const, y_values[0], z_values[0]),
        (x_const, y_values[1], z_values[0]),
        (x_const, y_values[0], z_values[1]),
    ]
    seen = set(ordered)
    for z_value in z_values:
        for y_value in y_values:
            item = (float(x_const), float(y_value), float(z_value))
            if item not in seen:
                ordered.append(item)
                seen.add(item)
    return np.asarray(ordered, dtype=float)


def z0_at(landcover, x_m, y_m):
    xs = np.unique([row["x_m"] for row in landcover])
    ys = np.unique([row["y_m"] for row in landcover])
    table = {(row["x_m"], row["y_m"]): row["z0_m"] for row in landcover}
    x0, x1, wx = _bracket(list(xs), x_m)
    y0, y1, wy = _bracket(list(ys), y_m)
    def pick(i, j):
        return table[(float(xs[i]), float(ys[j]))]
    low = (1.0 - wx) * pick(x0, y0) + wx * pick(x1, y0)
    high = (1.0 - wx) * pick(x0, y1) + wx * pick(x1, y1)
    return (1.0 - wy) * low + wy * high


def ground_ks(mesh, landcover):
    values = []
    centers = []
    for j in range(mesh["ny"]):
        for i in range(mesh["nx"]):
            x_m = 0.5 * (mesh["x"][i] + mesh["x"][i + 1])
            y_m = 0.5 * (mesh["y"][j] + mesh["y"][j + 1])
            z0 = z0_at(landcover, x_m, y_m)
            values.append(KS_PER_Z0 * z0)
            centers.append((x_m, y_m, z0))
    return np.asarray(values), centers


def scalar_internal(name, dimensions, values):
    del name, dimensions
    if np.ndim(values) == 0:
        return f"internalField   uniform {_fmt_scalar(values)};"
    body = "\n".join(_fmt_scalar(value) for value in np.asarray(values))
    return f"internalField   nonuniform\n{len(values)}\n(\n{body}\n);"


def vector_internal(values):
    if np.ndim(values) == 1 and len(values) == 3:
        return "internalField   uniform (" + " ".join(_fmt_scalar(v) for v in values) + ");"
    body = "\n".join("(" + " ".join(_fmt_scalar(v) for v in row) + ")" for row in values)
    return f"internalField   nonuniform\n{len(values)}\n(\n{body}\n);"


def vol_scalar(path, name, dimensions, internal_text, patches):
    body = f"dimensions      {dimensions};\n\n{internal_text}\n\nboundaryField\n{{\n{patches}\n}}\n"
    write_foam(path, "volScalarField", "0", name, body)


def vol_vector(path, name, internal_text, patches):
    body = f"dimensions      [velocity];\n\n{internal_text}\n\nboundaryField\n{{\n{patches}\n}}\n"
    write_foam(path, "volVectorField", "0", name, body)


def mapped_patch(vector=False):
    """``offset`` is a Function1 of the field type. Scalars cannot take a vector."""
    offset = "(0 0 0)" if vector else "0"
    return (
        "        type            timeVaryingMappedFixedValue;\n"
        f"        offset          {offset};\n"
        "        setAverage      off;\n"
        "        perturb         1e-5;\n"
    )


def write_initial_fields(case, mesh, profiles, heatflux, ks):
    zero = Path(case) / "0"
    centers = cell_centers(mesh)
    z_ground = np.empty(cell_count(mesh))
    for index in range(cell_count(mesh)):
        i = index % mesh["nx"]
        j = (index // mesh["nx"]) % mesh["ny"]
        z_ground[index] = 0.25 * (
            mesh["ground"][j, i] + mesh["ground"][j, i + 1]
            + mesh["ground"][j + 1, i] + mesh["ground"][j + 1, i + 1]
        )
    state = [interpolate_profile(profiles, 0.0, centers[n, 1], max(centers[n, 2] - z_ground[n], 0.0))
             for n in range(cell_count(mesh))]
    velocity = np.array([[row["u_ms"], row["v_ms"], row["w_ms"]] for row in state])
    temperature = np.array([row["T_K"] for row in state])
    humidity = np.array([row["q_kgkg"] for row in state])
    k_values = np.array([row["k_m2s2"] for row in state])
    epsilon = np.array([row["epsilon_m2s3"] for row in state])

    inlet_u = mapped_patch(vector=True)
    inlet_s = mapped_patch(vector=False)
    slip = "        type            slip;\n"
    calculated = "        type            calculated;\n        value           uniform 0;\n"
    inlet_outlet_scalar = (
        "        type            inletOutlet;\n"
        "        inletValue      uniform {value};\n"
        "        value           uniform {value};\n"
    )
    heat_rows = "\n".join(
        f"            ({_fmt_scalar(row['time_s'])} {_fmt_scalar(row['q_Wm2'])})"
        for row in heatflux
    )
    ground_t = (
        "        type            externalTemperature;\n"
        "        q\n"
        "        {\n"
        "            type            table;\n"
        "            outOfBounds     clamp;\n"
        "            values\n"
        "            (\n"
        f"{heat_rows}\n"
        "            );\n"
        "        }\n"
        f"        value           uniform {_fmt_scalar(T_REF)};\n"
    )
    ks_body = "\n".join(_fmt_scalar(value) for value in ks)
    ground_nut = (
        "        type            nutkRoughWallFunction;\n"
        f"        Ks              nonuniform\n{len(ks)}\n(\n{ks_body}\n);\n"
        "        Cs              uniform 0.5;\n"
        "        value           uniform 0;\n"
    )
    vol_vector(zero / "U", "U", vector_internal(velocity), "\n".join([
        "    inlet\n    {\n" + inlet_u + "    }",
        "    outlet\n    {\n        type            pressureInletOutletVelocity;\n"
        "        value           uniform (5 0 0);\n    }",
        "    ground\n    {\n        type            noSlip;\n    }",
        "    top\n    {\n" + slip + "    }",
        "    front\n    {\n" + slip + "    }",
        "    back\n    {\n" + slip + "    }",
    ]))
    t_side = inlet_outlet_scalar.format(value=_fmt_scalar(T_REF))
    vol_scalar(zero / "T", "T", "[temperature]", scalar_internal("T", "[temperature]", temperature), "\n".join([
        "    inlet\n    {\n" + inlet_s + "    }",
        "    outlet\n    {\n" + inlet_outlet_scalar.format(value=_fmt_scalar(float(np.mean(temperature)))) + "    }",
        "    ground\n    {\n" + ground_t + "    }",
        "    top\n    {\n" + t_side + "    }",
        "    front\n    {\n" + t_side + "    }",
        "    back\n    {\n" + t_side + "    }",
    ]))
    q_fallback = _fmt_scalar(float(np.mean(humidity)))
    q_side = inlet_outlet_scalar.format(value=q_fallback)
    zero_grad = "        type            zeroGradient;\n"
    vol_scalar(zero / "q", "q", "[]", scalar_internal("q", "[]", humidity), "\n".join([
        "    inlet\n    {\n" + inlet_s + "    }",
        "    outlet\n    {\n" + q_side + "    }",
        "    ground\n    {\n" + zero_grad + "    }",
        "    top\n    {\n" + q_side + "    }",
        "    front\n    {\n" + q_side + "    }",
        "    back\n    {\n" + q_side + "    }",
    ]))
    k_side = inlet_outlet_scalar.format(value=_fmt_scalar(float(np.mean(k_values))))
    vol_scalar(zero / "k", "k", "[turbulentKineticEnergy]", scalar_internal("k", "[turbulentKineticEnergy]", k_values), "\n".join([
        "    inlet\n    {\n" + inlet_s + "    }",
        "    outlet\n    {\n" + k_side + "    }",
        "    ground\n    {\n        type            kqRWallFunction;\n        value           uniform 0.1;\n    }",
        "    top\n    {\n" + k_side + "    }",
        "    front\n    {\n" + k_side + "    }",
        "    back\n    {\n" + k_side + "    }",
    ]))
    e_side = inlet_outlet_scalar.format(value=_fmt_scalar(float(np.mean(epsilon))))
    vol_scalar(zero / "epsilon", "epsilon", "[turbulentEpsilon]", scalar_internal("epsilon", "[turbulentEpsilon]", epsilon), "\n".join([
        "    inlet\n    {\n" + inlet_s + "    }",
        "    outlet\n    {\n" + e_side + "    }",
        "    ground\n    {\n        type            epsilonWallFunction;\n        value           uniform 0.01;\n    }",
        "    top\n    {\n" + e_side + "    }",
        "    front\n    {\n" + e_side + "    }",
        "    back\n    {\n" + e_side + "    }",
    ]))
    fixed_flux = f"        type            fixedFluxPressure;\n        value           uniform 0;\n"
    vol_scalar(zero / "p_rgh", "p_rgh", "[pressure]", scalar_internal("p_rgh", "[pressure]", 0.0), "\n".join([
        "    inlet\n    {\n" + fixed_flux + "    }",
        "    outlet\n    {\n" + inlet_s + "    }",
        "    ground\n    {\n" + fixed_flux + "    }",
        "    top\n    {\n" + fixed_flux + "    }",
        "    front\n    {\n" + fixed_flux + "    }",
        "    back\n    {\n" + fixed_flux + "    }",
    ]))
    calculated_p = f"        type            calculated;\n        value           uniform {_fmt_scalar(P_REF)};\n"
    vol_scalar(zero / "p", "p", "[pressure]", scalar_internal("p", "[pressure]", P_REF), "\n".join([
        f"    {name}\n    {{\n{calculated_p}    }}"
        for name in ("inlet", "outlet", "ground", "top", "front", "back")
    ]))
    vol_scalar(zero / "nut", "nut", "[turbulentViscosity]", scalar_internal("nut", "[turbulentViscosity]", 0.0), "\n".join([
        "    inlet\n    {\n" + calculated + "    }",
        "    outlet\n    {\n" + calculated + "    }",
        "    ground\n    {\n" + ground_nut + "    }",
        "    top\n    {\n" + calculated + "    }",
        "    front\n    {\n" + calculated + "    }",
        "    back\n    {\n" + calculated + "    }",
    ]))
    alphat_wall = "        type            compressible::alphatWallFunction;\n        value           uniform 0;\n"
    vol_scalar(zero / "alphat", "alphat", "[dynamicDiffusivity]", scalar_internal("alphat", "[dynamicDiffusivity]", 0.0), "\n".join([
        "    inlet\n    {\n" + calculated + "    }",
        "    outlet\n    {\n" + calculated + "    }",
        "    ground\n    {\n" + alphat_wall + "    }",
        "    top\n    {\n" + calculated + "    }",
        "    front\n    {\n" + calculated + "    }",
        "    back\n    {\n" + calculated + "    }",
    ]))


def ground_on_plane(mesh, x_const):
    """Ground elevation along the inlet or outlet, ordered with ``mesh['y']``."""
    if abs(float(x_const) - float(mesh["x"][0])) <= abs(float(x_const) - float(mesh["x"][-1])):
        return mesh["ground"][:, 0]
    return mesh["ground"][:, -1]


def ground_at_y(y_nodes, column, y_m):
    lower, upper, weight = _bracket([float(value) for value in y_nodes], float(y_m))
    return (1.0 - weight) * float(column[lower]) + weight * float(column[upper])


def write_boundary_data(case, mesh, profiles):
    z_top = float(np.max(mesh["ground"]) + mesh["h_air"])
    times = sorted({row["time_s"] for row in profiles})
    for patch, x_const in (("inlet", float(mesh["x"][0])), ("outlet", float(mesh["x"][-1]))):
        points = plane_sample_points(x_const, mesh["y"], 1.0, z_top)
        column = ground_on_plane(mesh, x_const)
        agl = np.array([
            max(point[2] - ground_at_y(mesh["y"], column, point[1]), 0.0)
            for point in points
        ])
        cloud = Path(case) / "constant" / "boundaryData" / patch
        write_points_cloud(cloud / "points", points)
        for time in times:
            time_name = str(int(time)) if float(time).is_integer() else _fmt_scalar(time)
            state = [
                interpolate_profile(profiles, time, point[1], height)
                for point, height in zip(points, agl)
            ]
            target = cloud / time_name
            if patch == "inlet":
                write_mapped_cloud(target / "U", np.array([[s["u_ms"], s["v_ms"], s["w_ms"]] for s in state]))
                write_mapped_cloud(target / "T", np.array([s["T_K"] for s in state]))
                write_mapped_cloud(target / "q", np.array([s["q_kgkg"] for s in state]))
                write_mapped_cloud(target / "k", np.array([s["k_m2s2"] for s in state]))
                write_mapped_cloud(target / "epsilon", np.array([s["epsilon_m2s3"] for s in state]))
            else:
                raw_p = np.array([s["p_Pa"] for s in state])
                anomaly, clamped = dynamic_pressure(raw_p, agl)
                write_mapped_cloud(target / "p_rgh", anomaly)
                if clamped:
                    print(
                        f"Warning: {patch} p_rgh at t={time_name} was scaled to ±{PRGH_LIMIT} Pa",
                        file=sys.stderr,
                    )


def write_meta(case, dem, mesh):
    text = "\n".join([
        f"nx {mesh['nx']}",
        f"ny {mesh['ny']}",
        f"nz {mesh['nz']}",
        f"hAir {_fmt_scalar(mesh['h_air'])}",
        f"pRef {_fmt_scalar(P_REF)}",
        f"rho0 {_fmt_scalar(RHO0)}",
        f"originX {_fmt_scalar(dem['origin_x'])}",
        f"originY {_fmt_scalar(dem['origin_y'])}",
        f"crs {dem['crs']}",
        f"cells {cell_count(mesh)}",
    ]) + "\n"
    path = Path(case) / "constant" / "terrainCase"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="ascii")


def copy_templates(case):
    case = Path(case)
    for folder in ("system", "constant"):
        source = CASE_TEMPLATE / folder
        target = case / folder
        target.mkdir(parents=True, exist_ok=True)
        for path in source.iterdir():
            if path.is_file():
                shutil.copy2(path, target / path.name)
    write_foam(
        case / "constant" / "pRef",
        "uniformDimensionedScalarField",
        "constant",
        "pRef",
        f"dimensions      [pressure];\nvalue           {_fmt_scalar(P_REF)};",
    )


def ensure_tutorial_dem(path=TUTORIAL_DEM):
    """Clip the public Copernicus COG into ``work/`` if the GeoTIFF is absent."""
    path = Path(path)
    if path.is_file() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("gdalwarp") is None:
        raise SystemExit("gdalwarp is required to clip the Copernicus DEM. Install gdal-bin.")
    env = os.environ.copy()
    env["GDAL_DISABLE_READDIR_ON_OPEN"] = "EMPTY"
    env["CPL_VSIL_CURL_ALLOWED_EXTENSIONS"] = ".tif"
    env["GDAL_HTTP_TIMEOUT"] = "120"
    env["GDAL_HTTP_MAX_RETRY"] = "3"
    subprocess.run(
        [
            "gdalwarp", "-t_srs", "EPSG:32650", "-r", "bilinear", "-tr", "30", "30",
            "-te", *(str(value) for value in TUTORIAL_DEM_TE),
            "/vsicurl/" + TUTORIAL_DEM_URL, str(path),
        ],
        check=True,
        env=env,
    )
    return path


def prepare_case(case, profiles, landcover, heatflux, dem_path=None, stride=1, nz=12,
                 h_air=180.0, growth=1.10, write_stl=True, sample_hill=False):
    case = Path(case)
    if case.exists():
        shutil.rmtree(case)
    case.mkdir(parents=True)
    dem_file = case / "dem_utm.tif"
    if sample_hill:
        write_sample_dem(dem_file)
    elif dem_path is None:
        raise ValueError("dem_path is required unless sample_hill is set")
    else:
        shutil.copy2(dem_path, dem_file)
    dem = read_dem(dem_file, stride=stride)
    mesh = build_hex_mesh(dem["x"], dem["y"], dem["height"], h_air, nz, growth)
    copy_templates(case)
    write_poly_mesh(mesh, case / "constant" / "polyMesh")
    write_meta(case, dem, mesh)
    ks, _centers = ground_ks(mesh, landcover)
    write_initial_fields(case, mesh, profiles, heatflux, ks)
    write_boundary_data(case, mesh, profiles)
    if write_stl:
        stl = case / "constant" / "triSurface" / "terrain.stl"
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "dem_to_stl.py"), str(dem_file), str(stl), "--stride", str(stride)],
            check=True,
        )
    print(
        f"Prepared {case}: cells={cell_count(mesh)} "
        f"nx={mesh['nx']} ny={mesh['ny']} nz={mesh['nz']} "
        f"Ks=[{ks.min():.4g}, {ks.max():.4g}] m"
    )
    return mesh


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, default=ROOT / "work" / "atmospheric")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--landcover", type=Path, default=DEFAULT_LANDCOVER)
    parser.add_argument("--heatflux", type=Path, default=DEFAULT_HEATFLUX)
    parser.add_argument("--dem", type=Path, default=None,
                        help="projected GeoTIFF in metres; default clips Copernicus GLO-30 over Jingshan")
    parser.add_argument("--sample-hill", action="store_true",
                        help="write the synthetic hill used by unit tests instead of the Copernicus clip")
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--nz", type=int, default=12)
    parser.add_argument("--h-air", type=float, default=180.0)
    parser.add_argument("--growth", type=float, default=1.10)
    parser.add_argument("--skip-stl", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.stride < 1:
        raise SystemExit("--stride must be >= 1")
    profiles = load_profiles(args.profiles)
    landcover = load_landcover(args.landcover)
    heatflux = load_heatflux(args.heatflux)
    dem_path = args.dem
    if not args.sample_hill and dem_path is None:
        dem_path = ensure_tutorial_dem()
    prepare_case(
        args.case, profiles, landcover, heatflux,
        dem_path=dem_path, stride=args.stride, nz=args.nz,
        h_air=args.h_air, growth=args.growth, write_stl=not args.skip_stl,
        sample_hill=args.sample_hill,
    )


if __name__ == "__main__":
    main()
