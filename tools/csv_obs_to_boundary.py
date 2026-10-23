#!/usr/bin/env python3
"""Turn a wide observation CSV into the atmospheric boundary tables.

The input is a user-filled table, not a model file. Required columns, units
and the alternatives are listed in ``COLUMNS`` and checked before any
OpenFOAM file is written. Projection uses the EPSG and DEM origin you pass.
This script does not guess a CRS.

Height is metres above ground when it leaves this script. Pressure-only
rows use an isothermal hypsometric step from ``surface_pressure_hpa``.
Absolute temperature is converted to dry potential temperature at 1000 hPa.
``k`` and ``epsilon`` are diagnosed when the table does not already contain
both, using ``z0_m`` or ``--z0``. The ground roughness map is a different
file. A ``z0_m`` column here only diagnoses turbulence.
"""
import argparse
import csv
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from atmospheric_case import (
    CMU,
    CP_AIR,
    GRAVITY,
    KAPPA,
    R_DRY,
    diagnose_k_epsilon,
    potential_temperature_from_kelvin,
    project_wgs84_to_local,
    specific_humidity,
    wind_components,
    write_heatflux_csv,
    write_profile_csv,
)


COLUMNS = (
    "id", "time", "lat", "lon",
    "height_agl_m", "height_asl_m", "surface_asl_m",
    "pressure_hpa", "surface_pressure_hpa",
    "t_c", "t_k", "theta_k",
    "u_ms", "v_ms", "wind_speed_ms", "wind_dir_deg", "w_ms",
    "rh_percent", "q_kgkg", "dewpoint_c",
    "k_m2s2", "epsilon_m2s3", "ti",
    "z0_m", "heat_flux_wm2",
)
P_REF = 1.0e5
MIN_Z = 0.5
_MISSING_TOKENS = {"nan", "na", "n/a", "null", "none", "-"}


class CsvObsError(ValueError):
    """A table problem the user can fix. The message names the row."""


def _blank(text):
    return text is None or str(text).strip() == ""


def _number(line_no, column, text):
    if _blank(text):
        return None
    token = str(text).strip()
    if token.lower() in _MISSING_TOKENS:
        raise CsvObsError(
            f"line {line_no}: {column} is {token!r}. Leave the cell empty or write a number"
        )
    try:
        value = float(token)
    except ValueError as error:
        raise CsvObsError(f"line {line_no}: {column} is not a number ({token!r})") from error
    if not math.isfinite(value):
        raise CsvObsError(f"line {line_no}: {column} is not finite")
    return value


def _parse_time(line_no, text):
    if _blank(text):
        raise CsvObsError(f"line {line_no}: time is empty")
    token = str(text).strip()
    if token.endswith("Z"):
        token = token[:-1] + "+00:00"
    if " " in token and "T" not in token:
        token = token.replace(" ", "T", 1)
    try:
        stamp = datetime.fromisoformat(token)
    except ValueError as error:
        raise CsvObsError(
            f"line {line_no}: time {text!r} is not ISO-8601 UTC. "
            "Use 2025-01-15T00:00:00Z"
        ) from error
    if stamp.tzinfo is None:
        raise CsvObsError(
            f"line {line_no}: time {text!r} has no timezone. Append Z for UTC"
        )
    if stamp.utcoffset() != timezone.utc.utcoffset(None):
        raise CsvObsError(f"line {line_no}: time {text!r} is not UTC")
    return stamp.astimezone(timezone.utc).replace(microsecond=0)


def _require_header(fieldnames):
    if not fieldnames:
        raise CsvObsError("the CSV has no header")
    unknown = [name for name in fieldnames if name not in COLUMNS]
    if unknown:
        raise CsvObsError(
            "unknown column(s): " + ", ".join(unknown)
            + ". Allowed columns: " + ", ".join(COLUMNS)
        )
    missing = [name for name in ("id", "time", "lat", "lon") if name not in fieldnames]
    if missing:
        raise CsvObsError("header is missing " + ", ".join(missing))


def load_obs_rows(path):
    """Return ``(line_number, dict)`` for data rows. Comments start with ``#``."""
    path = Path(path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeError as error:
        raise CsvObsError(f"{path} is not UTF-8") from error
    payload = []
    numbers = []
    for number, line in enumerate(lines, start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        payload.append(line)
        numbers.append(number)
    if not payload:
        raise CsvObsError(f"{path} has no data rows")
    reader = csv.DictReader(payload)
    _require_header(reader.fieldnames)
    rows = []
    for line_no, raw in zip(numbers[1:], reader):
        if raw.get("id") is None and all(_blank(value) for value in raw.values()):
            continue
        item = {"line": line_no, "id": (raw.get("id") or "").strip(), "time_text": raw.get("time")}
        if not item["id"]:
            raise CsvObsError(f"line {line_no}: id is empty")
        if not item["id"].isascii() or any(ch.isspace() for ch in item["id"]):
            raise CsvObsError(f"line {line_no}: id {item['id']!r} must be ASCII without spaces")
        item["time"] = _parse_time(line_no, raw.get("time"))
        for column in COLUMNS:
            if column in ("id", "time"):
                continue
            if column not in raw:
                item[column] = None
            else:
                item[column] = _number(line_no, column, raw.get(column))
        rows.append(item)
    if not rows:
        raise CsvObsError(f"{path} has a header and no data rows")
    return rows


def _one_of(row, options, label):
    present = [name for name in options if row[name] is not None]
    if len(present) != 1:
        joined = " or ".join(options)
        raise CsvObsError(
            f"line {row['line']}: {label} needs exactly one of {joined}, found {present or 'none'}"
        )
    return present[0]


def _same_choice(rows, options, label):
    choices = {_one_of(row, options, label) for row in rows}
    if len(choices) != 1:
        raise CsvObsError(
            f"{label} must use the same column on every row, found {sorted(choices)}"
        )
    return choices.pop()


def _vertical_mode(rows):
    modes = []
    for row in rows:
        has_agl = row["height_agl_m"] is not None
        has_asl = row["height_asl_m"] is not None
        has_p = row["pressure_hpa"] is not None
        if has_agl and has_asl:
            raise CsvObsError(
                f"line {row['line']}: fill height_agl_m or height_asl_m, not both"
            )
        if has_agl:
            modes.append("agl")
        elif has_asl:
            modes.append("asl")
        elif has_p:
            modes.append("pressure")
        else:
            raise CsvObsError(
                f"line {row['line']}: need height_agl_m, height_asl_m, or pressure_hpa"
            )
    if len(set(modes)) != 1:
        raise CsvObsError(
            "every row must use the same vertical coordinate. "
            f"This file mixes {sorted(set(modes))}"
        )
    return modes[0]


def _absolute_kelvin(row, choice):
    if choice == "t_c":
        if row["t_c"] < -100.0 or row["t_c"] > 60.0:
            raise CsvObsError(f"line {row['line']}: t_c={row['t_c']} is outside -100..60 C")
        return row["t_c"] + 273.15
    if choice == "t_k":
        if row["t_k"] < 170.0 or row["t_k"] > 330.0:
            raise CsvObsError(f"line {row['line']}: t_k={row['t_k']} is outside 170..330 K")
        return row["t_k"]
    if row["theta_k"] < 170.0 or row["theta_k"] > 330.0:
        raise CsvObsError(f"line {row['line']}: theta_k={row['theta_k']} is outside 170..330 K")
    return None


def _humidity(row, choice, temperature_c, pressure_pa):
    if choice == "q_kgkg":
        q_value = row["q_kgkg"]
    elif choice == "rh_percent":
        if row["rh_percent"] < 0.0 or row["rh_percent"] > 100.0:
            raise CsvObsError(f"line {row['line']}: rh_percent must be 0..100")
        if temperature_c is None or pressure_pa is None:
            raise CsvObsError(f"line {row['line']}: rh_percent needs absolute temperature and pressure_hpa")
        q_value = specific_humidity(row["rh_percent"], temperature_c, pressure_pa)
    else:
        if pressure_pa is None:
            raise CsvObsError(f"line {row['line']}: dewpoint_c needs pressure_hpa")
        dewpoint = row["dewpoint_c"]
        saturation = 611.2 * math.exp(17.67 * dewpoint / (dewpoint + 243.5))
        denom = pressure_pa - 0.378 * saturation
        if denom <= 0.0:
            raise CsvObsError(f"line {row['line']}: dewpoint_c={dewpoint} is inconsistent with the pressure")
        q_value = 0.622 * saturation / denom
    if q_value < 0.0 or q_value > 0.05:
        raise CsvObsError(f"line {row['line']}: specific humidity {q_value:.6g} kg/kg is outside 0..0.05")
    return q_value


def _wind(row):
    has_vector = row["u_ms"] is not None or row["v_ms"] is not None
    has_polar = row["wind_speed_ms"] is not None or row["wind_dir_deg"] is not None
    if has_vector and has_polar:
        raise CsvObsError(
            f"line {row['line']}: fill u_ms and v_ms, or wind_speed_ms and wind_dir_deg, not both"
        )
    if has_vector:
        if row["u_ms"] is None or row["v_ms"] is None:
            raise CsvObsError(f"line {row['line']}: u_ms and v_ms are a pair")
        return row["u_ms"], row["v_ms"]
    if has_polar:
        if row["wind_speed_ms"] is None or row["wind_dir_deg"] is None:
            raise CsvObsError(f"line {row['line']}: wind_speed_ms and wind_dir_deg are a pair")
        if row["wind_speed_ms"] < 0.0:
            raise CsvObsError(f"line {row['line']}: wind_speed_ms must be >= 0")
        return wind_components(row["wind_speed_ms"], row["wind_dir_deg"])
    raise CsvObsError(
        f"line {row['line']}: need u_ms and v_ms, or wind_speed_ms and wind_dir_deg"
    )


def _pressure_pa(row, z_agl, temperature_k, diagnosed):
    if row["pressure_hpa"] is not None:
        if row["pressure_hpa"] < 100.0 or row["pressure_hpa"] > 1100.0:
            raise CsvObsError(f"line {row['line']}: pressure_hpa={row['pressure_hpa']} is outside 100..1100")
        return row["pressure_hpa"] * 100.0, diagnosed
    if temperature_k is None:
        raise CsvObsError(
            f"line {row['line']}: theta_k without pressure_hpa cannot be turned into a pressure. "
            "Add pressure_hpa"
        )
    if row["surface_pressure_hpa"] is not None:
        surface = row["surface_pressure_hpa"] * 100.0
    else:
        surface = P_REF
        diagnosed = True
    pressure = surface * math.exp(-GRAVITY * z_agl / (R_DRY * temperature_k))
    return pressure, diagnosed


def _height(row, mode, temperature_k):
    if mode == "agl":
        z_agl = row["height_agl_m"]
    elif mode == "asl":
        if row["surface_asl_m"] is None:
            raise CsvObsError(f"line {row['line']}: height_asl_m needs surface_asl_m on the same row")
        z_agl = row["height_asl_m"] - row["surface_asl_m"]
    else:
        if row["surface_pressure_hpa"] is None:
            raise CsvObsError(
                f"line {row['line']}: pressure_hpa as the vertical coordinate needs surface_pressure_hpa"
            )
        if row["pressure_hpa"] > row["surface_pressure_hpa"] + 0.05:
            raise CsvObsError(
                f"line {row['line']}: pressure_hpa is above surface_pressure_hpa, so the height would be negative"
            )
        if temperature_k is None:
            raise CsvObsError(
                f"line {row['line']}: converting pressure_hpa to height needs t_c or t_k. "
                "theta_k still needs an absolute temperature for the hypsometric step"
            )
        ratio = row["surface_pressure_hpa"] / row["pressure_hpa"]
        z_agl = (R_DRY * temperature_k / GRAVITY) * math.log(ratio)
    if z_agl < MIN_Z:
        raise CsvObsError(
            f"line {row['line']}: height AGL is {z_agl:.4g} m. "
            f"Keep levels at or above {MIN_Z:g} m so the log law stays defined"
        )
    return z_agl


def _location_checks(rows):
    for row in rows:
        if row["lat"] is None or row["lon"] is None:
            raise CsvObsError(f"line {row['line']}: lat and lon are required")
        if not -90.0 <= row["lat"] <= 90.0:
            raise CsvObsError(f"line {row['line']}: lat={row['lat']} is outside -90..90")
        if not -180.0 <= row["lon"] <= 180.0:
            raise CsvObsError(f"line {row['line']}: lon={row['lon']} is outside -180..180")
    for station in {row["id"] for row in rows}:
        group = [row for row in rows if row["id"] == station]
        lats = {round(row["lat"], 6) for row in group}
        lons = {round(row["lon"], 6) for row in group}
        if len(lats) != 1 or len(lons) != 1:
            raise CsvObsError(f"id {station}: lat and lon must be constant for that id")


def _z0_for_station(rows, fallback):
    values = {row["z0_m"] for row in rows}
    if values == {None}:
        if fallback is None:
            raise CsvObsError(
                f"id {rows[0]['id']}: z0_m is empty and --z0 was not set. "
                "The log-law diagnosis needs a roughness length"
            )
        return float(fallback)
    if None in values or len(values) != 1:
        raise CsvObsError(f"id {rows[0]['id']}: z0_m must be the same number on every row of that id")
    z0 = values.pop()
    if z0 <= 0.0:
        raise CsvObsError(f"id {rows[0]['id']}: z0_m must be positive")
    return float(z0)


def _turbulence(column, z0):
    """Fill k and epsilon. ``column`` items already have u, v, z."""
    if any(item["k"] is not None or item["epsilon"] is not None or item["ti"] is not None for item in column):
        for item in column:
            has_k = item["k"] is not None
            has_e = item["epsilon"] is not None
            has_ti = item["ti"] is not None
            if has_ti and (has_k or has_e):
                raise CsvObsError(
                    f"line {item['line']}: ti replaces k_m2s2 and epsilon_m2s3. Do not fill both"
                )
            if has_k != has_e:
                raise CsvObsError(
                    f"line {item['line']}: k_m2s2 and epsilon_m2s3 must both be filled, or both left empty"
                )
            if has_ti and not (0.0 < item["ti"] < 1.0):
                raise CsvObsError(
                    f"line {item['line']}: ti={item['ti']} must be a fraction between 0 and 1 "
                    "(0.12 means 12 percent)"
                )
        if all(item["k"] is not None for item in column):
            for item in column:
                if item["k"] < 0.0 or item["epsilon"] <= 0.0:
                    raise CsvObsError(f"line {item['line']}: k_m2s2 must be >= 0 and epsilon_m2s3 > 0")
            return
        speed = np.hypot(
            np.array([item["u"] for item in column]),
            np.array([item["v"] for item in column]),
        )
        k_value = 1.5 * (np.array([item["ti"] for item in column]) * speed) ** 2
        length = KAPPA * (np.array([item["z"] for item in column]) + z0)
        epsilon = (CMU ** 0.75) * k_value ** 1.5 / length
        for item, k_item, epsilon_item in zip(column, k_value, epsilon):
            item["k"] = float(k_item)
            item["epsilon"] = float(epsilon_item)
        return
    k_value, epsilon = diagnose_k_epsilon(
        [item["u"] for item in column],
        [item["v"] for item in column],
        np.maximum([item["z"] for item in column], MIN_Z),
        z0,
    )
    for item, k_item, epsilon_item in zip(column, k_value, epsilon):
        item["k"] = float(k_item)
        item["epsilon"] = float(epsilon_item)


def _heat_rows(rows, clock):
    grouped = {}
    for row in rows:
        if row["heat_flux_wm2"] is None:
            raise CsvObsError(
                f"line {row['line']}: heat_flux_wm2 is empty. "
                "The ground boundary needs one sensible-heat flux in W/m2 for each time"
            )
        grouped.setdefault(row["time"], []).append(row["heat_flux_wm2"])
    heat_rows = []
    for stamp in sorted(grouped):
        values = grouped[stamp]
        if max(values) - min(values) > 1.0e-4:
            raise CsvObsError(
                f"time {stamp.strftime('%Y-%m-%dT%H:%M:%SZ')}: heat_flux_wm2 spans "
                f"{min(values):.6g} to {max(values):.6g}. "
                "This case uses one ground flux for the whole domain at each time"
            )
        heat_rows.append({"time_s": clock[stamp], "q_Wm2": float(values[0])})
    return heat_rows


def rows_from_obs(rows, epsg, origin_x, origin_y, solver_times, z0_fallback=None):
    """Validate ``rows`` from ``load_obs_rows`` and return boundary plus heat rows."""
    if epsg is None:
        raise CsvObsError("epsg is required")
    if z0_fallback is not None and any(row["z0_m"] is not None for row in rows):
        raise CsvObsError("z0_m is filled and --z0 was also set. Keep one of them")
    _location_checks(rows)
    mode = _vertical_mode(rows)
    temperature_choice = _same_choice(rows, ("t_c", "t_k", "theta_k"), "temperature")
    humidity_choice = _same_choice(rows, ("q_kgkg", "rh_percent", "dewpoint_c"), "humidity")
    stamps = sorted({row["time"] for row in rows})
    if len(solver_times) != len(stamps):
        raise CsvObsError(
            f"--solver-times has {len(solver_times)} values and the table has {len(stamps)} distinct times"
        )
    clock = {stamp: float(seconds) for stamp, seconds in zip(stamps, solver_times)}
    diagnosed_pressure = False
    stations = []
    for station in sorted({row["id"] for row in rows}):
        group = [row for row in rows if row["id"] == station]
        has_turbulence = all(
            row["k_m2s2"] is not None and row["epsilon_m2s3"] is not None for row in group
        )
        z0 = None if has_turbulence else _z0_for_station(group, z0_fallback)
        xy = project_wgs84_to_local(group[0]["lon"], group[0]["lat"], int(epsg), origin_x, origin_y)
        built = []
        for row in group:
            absolute = _absolute_kelvin(row, temperature_choice)
            if mode == "pressure" and absolute is None:
                raise CsvObsError(
                    f"line {row['line']}: pressure-to-height needs t_c or t_k on this row"
                )
            if mode == "pressure":
                z_agl = _height(row, mode, absolute)
                pressure, diagnosed_pressure = _pressure_pa(row, z_agl, absolute, diagnosed_pressure)
            else:
                z_agl = _height(row, mode, absolute)
                pressure, diagnosed_pressure = _pressure_pa(row, z_agl, absolute, diagnosed_pressure)
            if temperature_choice == "theta_k":
                theta = row["theta_k"]
                absolute = theta * (pressure / P_REF) ** (R_DRY / CP_AIR)
            else:
                theta = potential_temperature_from_kelvin(absolute, pressure)
            temperature_c = absolute - 273.15
            q_value = _humidity(row, humidity_choice, temperature_c, pressure)
            u_ms, v_ms = _wind(row)
            w_ms = 0.0 if row["w_ms"] is None else row["w_ms"]
            built.append({
                "line": row["line"],
                "time": row["time"],
                "z": z_agl,
                "u": u_ms,
                "v": v_ms,
                "w": w_ms,
                "theta": theta,
                "q": q_value,
                "p": pressure,
                "k": row["k_m2s2"],
                "epsilon": row["epsilon_m2s3"],
                "ti": row["ti"],
            })
        for stamp in stamps:
            column = [item for item in built if item["time"] == stamp]
            if len(column) < 2:
                raise CsvObsError(
                    f"id {station} at {stamp.strftime('%Y-%m-%dT%H:%M:%SZ')} has {len(column)} level(s). "
                    "Need at least two heights so the inlet can interpolate"
                )
            column.sort(key=lambda item: item["z"])
            for left, right in zip(column, column[1:]):
                if abs(right["z"] - left["z"]) < 1.0e-3:
                    raise CsvObsError(
                        f"id {station} at {stamp.strftime('%Y-%m-%dT%H:%M:%SZ')}: "
                        f"two levels both sit at {left['z']:.4g} m AGL"
                    )
            if any(item["k"] is None or item["ti"] is not None for item in column):
                if z0 is None:
                    raise CsvObsError(f"id {station}: diagnosing k and epsilon needs z0_m or --z0")
                _turbulence(column, z0)
            else:
                _turbulence(column, 1.0)
            thetas = [item["theta"] for item in column if item["z"] <= 300.0]
            if len(thetas) >= 2 and thetas[-1] <= thetas[0]:
                print(
                    f"Warning: {station} at {stamp.strftime('%Y-%m-%dT%H:%M:%SZ')} "
                    f"potential temperature falls from {thetas[0]:.2f} K to {thetas[-1]:.2f} K "
                    "in the lowest 300 m. The rows are kept.",
                    file=sys.stderr,
                )
        stations.append((station, xy[0], xy[1], built))
    if diagnosed_pressure:
        print(
            "Warning: some rows had no pressure_hpa. Pressure was filled with "
            "p = p_surface * exp(-g z / (R T)), or p_surface = 101325 Pa when that too was empty.",
            file=sys.stderr,
        )
    out_rows = []
    for station, x_m, y_m, built in stations:
        for item in sorted(built, key=lambda item: (item["time"], item["z"])):
            out_rows.append({
                "station": station,
                "time_s": clock[item["time"]],
                "x_m": float(x_m),
                "y_m": float(y_m),
                "z_m": float(item["z"]),
                "u_ms": float(item["u"]),
                "v_ms": float(item["v"]),
                "w_ms": float(item["w"]),
                "T_K": float(item["theta"]),
                "q_kgkg": float(item["q"]),
                "p_Pa": float(item["p"]),
                "k_m2s2": float(item["k"]),
                "epsilon_m2s3": float(item["epsilon"]),
            })
    return out_rows, _heat_rows(rows, clock)


def template_text():
    comment = "\n".join([
        "# Blank observation template for tools/csv_obs_to_boundary.py.",
        "# Delete these comment lines only if you want. Lines starting with # are ignored.",
        "# id: station name, ASCII, constant lat/lon for that id.",
        "# time: UTC, 2025-01-15T00:00:00Z. Map each distinct time with --solver-times.",
        "# lat, lon: WGS84 degrees. Pass --epsg --origin-x --origin-y. The script does not guess a CRS.",
        "# Vertical coordinate, the same choice on every row:",
        "#   height_agl_m  metres above ground, must be >= 0.5",
        "#   height_asl_m and surface_asl_m  metres above sea level, both required together",
        "#   pressure_hpa and surface_pressure_hpa  hPa. Height is (R T / g) ln(ps/p), T absolute.",
        "# Temperature, one column: t_c Celsius, t_k Kelvin, or theta_k potential temperature.",
        "# Wind, one pair: u_ms and v_ms (east, north), or wind_speed_ms and wind_dir_deg.",
        "#   wind_dir_deg is meteorological, the direction the wind comes FROM, degrees clockwise from north.",
        "# Humidity, one column: q_kgkg, rh_percent, or dewpoint_c. rh and dewpoint need a pressure.",
        "# Optional: w_ms (default 0), pressure_hpa when height is the vertical coordinate,",
        "#   k_m2s2 and epsilon_m2s3 together, or ti as a fraction (0.12 = 12 percent),",
        "#   z0_m constant per id (log-law diagnosis only, not the ground Ks map),",
        "#   heat_flux_wm2 in W/m2, positive into the air, one value per time.",
        "# Empty cells are missing. The words nan, na and null are rejected.",
        "# At least two heights per id and time. Do not drop a row because a check complains.",
        "# " + ",".join(COLUMNS),
    ])
    return comment + "\n" + ",".join(COLUMNS) + "\n"


def convert_file(input_path, output_path, epsg, origin_x, origin_y, solver_times, z0, heat_path=None):
    rows = load_obs_rows(input_path)
    profile_rows, heat_rows = rows_from_obs(
        rows, epsg, origin_x, origin_y, solver_times, z0,
    )
    output_path = Path(output_path)
    write_profile_csv(
        output_path,
        profile_rows,
        comment=(
            "# Observation table converted by tools/csv_obs_to_boundary.py.\n"
            f"# Source {input_path}. Projected with EPSG:{int(epsg)}.\n"
            "# T_K is dry potential temperature at 100000 Pa. z_m is metres above ground.\n"
            "# k and epsilon are copied when the table has both, otherwise diagnosed.\n"
            "# w_ms is 0 where the table left it empty.\n"
        ),
    )
    if heat_path is None:
        heat_path = output_path.with_name(output_path.stem + "_heatflux.csv")
    write_heatflux_csv(
        heat_path,
        heat_rows,
        comment=(
            "# Ground sensible-heat flux into the air, W/m2, taken from heat_flux_wm2.\n"
            "# One value per time. Positive heats the fluid.\n"
        ),
    )
    print(f"Wrote {output_path} ({len(profile_rows)} rows)")
    print(f"Wrote {heat_path}")
    return output_path, heat_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Wide observation CSV")
    parser.add_argument("--output", type=Path, help="Boundary profile CSV to write")
    parser.add_argument("--heatflux", type=Path, default=None, help="Defaults to <output stem>_heatflux.csv")
    parser.add_argument("--write-template", type=Path, default=None, help="Write a blank CSV and exit")
    parser.add_argument("--epsg", type=int, help="Case CRS. Required for a conversion. Not guessed.")
    parser.add_argument("--origin-x", type=float, help="DEM origin easting [m]")
    parser.add_argument("--origin-y", type=float, help="DEM origin northing [m]")
    parser.add_argument("--solver-times", type=float, nargs="+", default=None,
                        help="Solver seconds for each distinct UTC time, oldest first")
    parser.add_argument("--z0", type=float, default=None,
                        help="Roughness [m] used only when the z0_m column is absent")
    args = parser.parse_args(argv)
    try:
        if args.write_template is not None:
            args.write_template.parent.mkdir(parents=True, exist_ok=True)
            args.write_template.write_text(template_text(), encoding="utf-8")
            print(f"Wrote {args.write_template}")
            return
        if args.input is None or args.output is None:
            parser.error("--input and --output are required")
        if args.epsg is None or args.origin_x is None or args.origin_y is None:
            parser.error("--epsg, --origin-x and --origin-y are required together")
        if not args.solver_times:
            parser.error("--solver-times is required")
        if args.z0 is not None and args.z0 <= 0.0:
            parser.error("--z0 must be positive")
        convert_file(
            args.input, args.output, args.epsg, args.origin_x, args.origin_y,
            args.solver_times, args.z0, args.heatflux,
        )
    except CsvObsError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
