#!/usr/bin/env python3
"""Download one or more ERA5 columns and write the tutorial boundary CSV.

Needs a CDS account. Credentials stay in ~/.cdsapirc, not on the command line.
The default atmospheric case does not call this script. It reads the
committed Open-Meteo and IEM tables under tutorial/data/.
"""
import argparse
import sys
from pathlib import Path

import numpy as np

from atmospheric_case import (
    PROFILE_FIELDS,
    deaccumulate,
    diagnose_k_epsilon,
    omega_to_w,
    write_profile_csv,
)


PRESSURE_LEVELS = ("1000", "975", "950", "925", "900", "850", "800", "700")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="UTC day YYYY-MM-DD")
    parser.add_argument("--time", action="append", required=True, help="UTC time HH:MM, repeatable")
    parser.add_argument("--station", action="append", required=True,
                        help="lat,lon in WGS84 degrees, repeatable. South to north is a good order.")
    parser.add_argument("--epsg", required=True, type=int,
                        help="Projected CRS for northing. This script will not pick one.")
    parser.add_argument("--z0", required=True, type=float, help="Roughness length [m] used only to diagnose k and epsilon")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--y-m", action="append", type=float, default=None,
                        help="Optional y position [m] for each --station, in the same order")
    parser.add_argument("--cache-dir", type=Path, default=Path("downloads/era5"))
    args = parser.parse_args(argv)
    stations = []
    for item in args.station:
        lat_text, lon_text = item.split(",")
        stations.append((float(lat_text), float(lon_text)))
    if args.y_m is not None and len(args.y_m) != len(stations):
        parser.error("--y-m must be given once per --station")
    if args.z0 <= 0:
        parser.error("--z0 must be positive")

    try:
        import cdsapi
        import netCDF4
        from pyproj import Transformer
    except ImportError as error:
        raise SystemExit(
            f"Missing optional dependency ({error}). Install with:\n"
            "  python3 -m pip install -r requirements-era5.txt"
        ) from error

    year, month, day = args.date.split("-")
    cache = args.cache_dir
    cache.mkdir(parents=True, exist_ok=True)
    pressure_file = cache / "era5_pressure_levels.nc"
    single_file = cache / "era5_single_levels.nc"
    client = cdsapi.Client()
    lats = [lat for lat, _lon in stations]
    lons = [lon for _lat, lon in stations]
    area = [max(lats) + 0.25, min(lons) - 0.25, min(lats) - 0.25, max(lons) + 0.25]
    client.retrieve(
        "reanalysis-era5-pressure-levels",
        {
            "product_type": "reanalysis",
            "variable": [
                "u_component_of_wind",
                "v_component_of_wind",
                "vertical_velocity",
                "temperature",
                "specific_humidity",
                "geopotential",
            ],
            "pressure_level": list(PRESSURE_LEVELS),
            "year": year,
            "month": month,
            "day": day,
            "time": args.time,
            "area": area,
            "format": "netcdf",
        },
        str(pressure_file),
    )
    client.retrieve(
        "reanalysis-era5-single-levels",
        {
            "product_type": "reanalysis",
            "variable": ["surface_sensible_heat_flux"],
            "year": year,
            "month": month,
            "day": day,
            "time": args.time,
            "area": area,
            "format": "netcdf",
        },
        str(single_file),
    )
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{args.epsg}", always_xy=True)
    northings = []
    for lat, lon in stations:
        _east, north = transformer.transform(lon, lat)
        northings.append(north)
    if args.y_m is None:
        y_values = [value - min(northings) for value in northings]
        print(
            "y_m is northing minus the southern station. "
            "Edit the CSV if those distances are larger than the CFD domain.",
            file=sys.stderr,
        )
    else:
        y_values = args.y_m

    rows = []
    with netCDF4.Dataset(pressure_file) as dataset, netCDF4.Dataset(single_file) as single:
        level = np.asarray(dataset.variables["level"][:], dtype=float) * 100.0
        time_var = dataset.variables["time"]
        # Hours from the file, converted to seconds. The tutorial case clock is
        # whatever you put in time_s; do not assume this matches endTime 20.
        time_seconds = np.asarray(netCDF4.num2date(time_var[:], time_var.units), dtype=object)
        origin = time_seconds[0]
        elapsed = np.array([(item - origin).total_seconds() for item in time_seconds])
        heat = None
        if "sshf" in single.variables:
            raw_heat = np.asarray(single.variables["sshf"][:], dtype=float)
            # Single-level sshf is accumulated J/m2. Difference it after the
            # nearest-cell sample below.
            heat = raw_heat
        for station_index, ((lat, lon), y_m) in enumerate(zip(stations, y_values)):
            sample = _column(dataset, lat, lon)
            omega = sample["w"]
            temperature = sample["t"]
            pressure = np.broadcast_to(level, temperature.shape)
            w_ms = omega_to_w(omega, temperature, pressure)
            height = sample["z"] / 9.80665
            for time_index, time_s in enumerate(elapsed):
                column_z = height[time_index]
                k_value, epsilon = diagnose_k_epsilon(
                    sample["u"][time_index], sample["v"][time_index], column_z, args.z0,
                )
                for level_index in np.argsort(column_z):
                    rows.append({
                        "station": f"era5_{station_index}",
                        "time_s": float(time_s),
                        "y_m": float(y_m),
                        "z_m": float(column_z[level_index]),
                        "u_ms": float(sample["u"][time_index, level_index]),
                        "v_ms": float(sample["v"][time_index, level_index]),
                        "w_ms": float(w_ms[time_index, level_index]),
                        "T_K": float(temperature[time_index, level_index]),
                        "q_kgkg": float(sample["q"][time_index, level_index]),
                        "p_Pa": float(level[level_index]),
                        "k_m2s2": float(k_value[level_index]),
                        "epsilon_m2s3": float(epsilon[level_index]),
                    })
        if heat is not None:
            heat_column = _nearest_series(single, "sshf", stations[0][0], stations[0][1])
            step = float(np.diff(elapsed).mean()) if len(elapsed) > 1 else 3600.0
            watts = -deaccumulate(heat_column, step)
            heat_path = args.output.with_name(args.output.stem + "_heatflux.csv")
            heat_path.write_text(
                "# ERA5 sshf is accumulated J/m2 and positive downward.\n"
                "# Values here are W/m2 into the air: minus the time derivative.\n"
                "time_s,q_Wm2\n"
                + "".join(f"{time_s:.8g},{value:.8g}\n" for time_s, value in zip(elapsed, watts)),
                encoding="ascii",
            )
            print(f"Wrote {heat_path}")
    # PROFILE_FIELDS is the column contract shared with the sample table.
    missing = [key for key in PROFILE_FIELDS if key not in rows[0]]
    if missing:
        raise SystemExit(f"Internal column mismatch: {missing}")
    write_profile_csv(
        args.output,
        rows,
        comment=(
            "# ERA5 pressure-level column converted for the atmospheric case.\n"
            "# w_ms was converted from Pa/s. T_K is ERA5 temperature, not potential\n"
            "# temperature. k and epsilon were diagnosed with the given z0.\n"
            "# p_Pa is the pressure level. prepare_case strips the hydrostatic part\n"
            "# before writing outlet p_rgh.\n"
        ),
    )
    print(f"Wrote {args.output} ({len(rows)} rows). k and epsilon were diagnosed, not downloaded.")


def _nearest_index(values, target):
    return int(np.argmin(np.abs(np.asarray(values) - target)))


def _column(dataset, lat, lon):
    lat_index = _nearest_index(dataset.variables["latitude"][:], lat)
    lon_index = _nearest_index(dataset.variables["longitude"][:], lon)
    names = {"u": "u", "v": "v", "w": "w", "t": "t", "q": "q", "z": "z"}
    return {
        key: np.asarray(dataset.variables[name][:, :, lat_index, lon_index], dtype=float)
        for key, name in names.items()
    }


def _nearest_series(dataset, variable, lat, lon):
    lat_index = _nearest_index(dataset.variables["latitude"][:], lat)
    lon_index = _nearest_index(dataset.variables["longitude"][:], lon)
    values = np.asarray(dataset.variables[variable][:], dtype=float)
    return values[(slice(None),) + (0,) * (values.ndim - 3) + (lat_index, lon_index)]


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
