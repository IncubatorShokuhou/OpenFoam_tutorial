#!/usr/bin/env python3
"""Turn ERA5 pressure-level and single-level NetCDF into the case CSV.

The CDS download needs an account. Credentials stay in ~/.cdsapirc, never on
the command line. Without a key, ``--write-sample`` builds a tiny NetCDF with
the same short names and the attribute ``tutorial_sample=synthetic``. That
file is not ERA5. ``--from-files`` reads either one.

Open-Meteo archive ``models=era5`` is the no-key surface alternative already
used for the Jingshan heat-flux estimate. Its pressure-level names come back
null, so it cannot replace this script for u, v, omega and geopotential.
"""
import argparse
import sys
from pathlib import Path

import numpy as np

from atmospheric_case import (
    GRAVITY,
    PROFILE_FIELDS,
    deaccumulate,
    diagnose_k_epsilon,
    omega_to_w,
    potential_temperature_from_kelvin,
    project_wgs84_to_local,
    write_heatflux_csv,
    write_profile_csv,
)


PRESSURE_LEVELS = ("1000", "975", "950", "925", "900", "850", "800", "700")
SHORT_NAMES = {
    "u": ("u", "u_component_of_wind"),
    "v": ("v", "v_component_of_wind"),
    "w": ("w", "vertical_velocity"),
    "t": ("t", "temperature"),
    "q": ("q", "specific_humidity"),
    "z": ("z", "geopotential"),
}


def _pick(dataset, aliases):
    for name in aliases:
        if name in dataset.variables:
            return name
    raise KeyError("none of " + ", ".join(aliases) + " is in the NetCDF")


def _nearest_index(values, target):
    return int(np.argmin(np.abs(np.asarray(values) - target)))


def _column(dataset, lat, lon):
    lat_name = "latitude" if "latitude" in dataset.variables else "lat"
    lon_name = "longitude" if "longitude" in dataset.variables else "lon"
    lat_index = _nearest_index(dataset.variables[lat_name][:], lat)
    lon_index = _nearest_index(dataset.variables[lon_name][:], lon)
    sample = {}
    for key, aliases in SHORT_NAMES.items():
        name = _pick(dataset, aliases)
        sample[key] = np.asarray(
            dataset.variables[name][:, :, lat_index, lon_index], dtype=float,
        )
    return sample


def _nearest_series(dataset, variable, lat, lon):
    lat_name = "latitude" if "latitude" in dataset.variables else "lat"
    lon_name = "longitude" if "longitude" in dataset.variables else "lon"
    lat_index = _nearest_index(dataset.variables[lat_name][:], lat)
    lon_index = _nearest_index(dataset.variables[lon_name][:], lon)
    values = np.asarray(dataset.variables[variable][:], dtype=float)
    return values[(slice(None),) + (0,) * (values.ndim - 3) + (lat_index, lon_index)]


def _elapsed_seconds(dataset):
    import netCDF4
    time_name = "time" if "time" in dataset.variables else "valid_time"
    time_var = dataset.variables[time_name]
    stamps = np.asarray(netCDF4.num2date(time_var[:], time_var.units), dtype=object)
    origin = stamps[0]
    return np.array([(item - origin).total_seconds() for item in stamps])


def _level_pa(dataset):
    if "level" in dataset.variables:
        values = np.asarray(dataset.variables["level"][:], dtype=float)
    else:
        values = np.asarray(dataset.variables["pressure_level"][:], dtype=float)
    # CDS stores hPa. A value above 2000 is already Pa.
    if float(np.nanmax(values)) < 2000:
        values = values * 100.0
    return values


def decode_era5_pair(pressure_path, single_path, stations, y_values, z0, solver_times=None):
    """Return profile rows and heat-flux rows.

    ``T_K`` in the rows is potential temperature. ERA5 stores absolute ``t``.
    ``z_m`` is height above the single-level geopotential, not above the DEM.
    """
    import netCDF4
    if len(y_values) != len(stations):
        raise ValueError("y_values and stations must have the same length")
    rows = []
    with netCDF4.Dataset(pressure_path) as dataset, netCDF4.Dataset(single_path) as single:
        sample_flag = ""
        if "tutorial_sample" in dataset.ncattrs():
            sample_flag = str(dataset.getncattr("tutorial_sample"))
        level = _level_pa(dataset)
        elapsed = _elapsed_seconds(dataset)
        if solver_times is not None:
            if len(solver_times) != len(elapsed):
                raise ValueError("solver_times must have one entry per ERA5 time")
            clock = [float(value) for value in solver_times]
        else:
            clock = [float(value) for value in elapsed]
        surface_name = _pick(single, ("z", "geopotential"))
        heat_name = None
        for candidate in ("sshf", "surface_sensible_heat_flux"):
            if candidate in single.variables:
                heat_name = candidate
                break
        for station_index, ((lat, lon), y_m) in enumerate(zip(stations, y_values)):
            sample = _column(dataset, lat, lon)
            surface_z = float(_nearest_series(single, surface_name, lat, lon)[0])
            height = (sample["z"] - surface_z) / GRAVITY
            temperature = sample["t"]
            pressure = np.broadcast_to(level, temperature.shape)
            w_ms = omega_to_w(sample["w"], temperature, pressure)
            theta = np.empty_like(temperature)
            for time_index in range(temperature.shape[0]):
                for level_index in range(temperature.shape[1]):
                    theta[time_index, level_index] = potential_temperature_from_kelvin(
                        temperature[time_index, level_index], level[level_index],
                    )
            for time_index, time_s in enumerate(clock):
                column_z = height[time_index]
                k_value, epsilon = diagnose_k_epsilon(
                    sample["u"][time_index], sample["v"][time_index], np.maximum(column_z, 0.5), z0,
                )
                for level_index in np.argsort(column_z):
                    rows.append({
                        "station": f"era5_{station_index}",
                        "time_s": float(time_s),
                        "y_m": float(y_m),
                        "z_m": float(max(column_z[level_index], 0.0)),
                        "u_ms": float(sample["u"][time_index, level_index]),
                        "v_ms": float(sample["v"][time_index, level_index]),
                        "w_ms": float(w_ms[time_index, level_index]),
                        "T_K": float(theta[time_index, level_index]),
                        "q_kgkg": float(sample["q"][time_index, level_index]),
                        "p_Pa": float(level[level_index]),
                        "k_m2s2": float(k_value[level_index]),
                        "epsilon_m2s3": float(epsilon[level_index]),
                    })
        heat_rows = []
        if heat_name is not None:
            heat_column = _nearest_series(single, heat_name, stations[0][0], stations[0][1])
            step = float(np.diff(elapsed).mean()) if len(elapsed) > 1 else 3600.0
            watts = -deaccumulate(np.asarray(heat_column, dtype=float), step)
            heat_rows = [
                {"time_s": float(time_s), "q_Wm2": float(value)}
                for time_s, value in zip(clock, watts)
            ]
    missing = [key for key in PROFILE_FIELDS if key not in rows[0]]
    if missing:
        raise ValueError(f"Internal column mismatch: {missing}")
    return rows, heat_rows, sample_flag


def write_sample_era5(pressure_path, single_path):
    """Write a two-cell, three-time NetCDF that uses ERA5 short names.

    The global attribute ``tutorial_sample`` says this is synthetic. Numbers
    are a stable winter column, not a CDS extract.
    """
    import netCDF4
    pressure_path = Path(pressure_path)
    single_path = Path(single_path)
    pressure_path.parent.mkdir(parents=True, exist_ok=True)
    latitudes = np.array([39.75, 40.00])
    longitudes = np.array([116.25, 116.50])
    levels = np.array([1000, 975, 950, 925])
    # Absolute temperature decreases with height. Theta still increases.
    temperature = np.array([268.0, 266.5, 265.0, 263.5])
    height_asl = np.array([80.0, 280.0, 490.0, 710.0])
    with netCDF4.Dataset(pressure_path, "w") as dataset:
        dataset.tutorial_sample = "synthetic ERA5-shaped NetCDF, not a CDS download"
        dataset.createDimension("time", 3)
        dataset.createDimension("level", len(levels))
        dataset.createDimension("latitude", len(latitudes))
        dataset.createDimension("longitude", len(longitudes))
        time_var = dataset.createVariable("time", "f8", ("time",))
        time_var.units = "hours since 2025-01-15 00:00:00"
        time_var[:] = np.array([0.0, 1.0, 2.0])
        dataset.createVariable("level", "f8", ("level",))[:] = levels
        dataset.createVariable("latitude", "f8", ("latitude",))[:] = latitudes
        dataset.createVariable("longitude", "f8", ("longitude",))[:] = longitudes
        shape = ("time", "level", "latitude", "longitude")
        for name in ("u", "v", "w", "t", "q", "z"):
            dataset.createVariable(name, "f8", shape)
        for time_index, wind_shift in enumerate((0.0, 0.4, -0.2)):
            for level_index, level in enumerate(levels):
                for lat_index in range(len(latitudes)):
                    north_boost = 0.8 * lat_index
                    dataset.variables["u"][time_index, level_index, lat_index, :] = (
                        2.2 + 0.004 * (1000 - level) + wind_shift + north_boost
                    )
                    dataset.variables["v"][time_index, level_index, lat_index, :] = 0.4 + 0.3 * lat_index
                    dataset.variables["w"][time_index, level_index, lat_index, :] = 0.02
                    dataset.variables["t"][time_index, level_index, lat_index, :] = (
                        temperature[level_index] + 0.3 * time_index
                    )
                    dataset.variables["q"][time_index, level_index, lat_index, :] = 0.0008 - 0.0000004 * (1000 - level)
                    dataset.variables["z"][time_index, level_index, lat_index, :] = height_asl[level_index] * GRAVITY
    surface_z = 50.0 * GRAVITY
    with netCDF4.Dataset(single_path, "w") as dataset:
        dataset.tutorial_sample = "synthetic ERA5-shaped NetCDF, not a CDS download"
        dataset.createDimension("time", 3)
        dataset.createDimension("latitude", len(latitudes))
        dataset.createDimension("longitude", len(longitudes))
        time_var = dataset.createVariable("time", "f8", ("time",))
        time_var.units = "hours since 2025-01-15 00:00:00"
        time_var[:] = np.array([0.0, 1.0, 2.0])
        dataset.createVariable("latitude", "f8", ("latitude",))[:] = latitudes
        dataset.createVariable("longitude", "f8", ("longitude",))[:] = longitudes
        dataset.createVariable("z", "f8", ("time", "latitude", "longitude"))[:] = surface_z
        sshf = dataset.createVariable("sshf", "f8", ("time", "latitude", "longitude"))
        # Accumulated J/m2, positive downward, as ERA5 stores sshf.
        sshf[0, :, :] = -20.0 * 3600.0
        sshf[1, :, :] = -20.0 * 3600.0 - 15.0 * 3600.0
        sshf[2, :, :] = -20.0 * 3600.0 - 15.0 * 3600.0 - 8.0 * 3600.0
    return pressure_path, single_path


def _stations_from_args(parser, args):
    stations = []
    for item in args.station:
        lat_text, lon_text = item.split(",")
        stations.append((float(lat_text), float(lon_text)))
    if args.y_m is not None and len(args.y_m) != len(stations):
        parser.error("--y-m must be given once per --station")
    if args.z0 <= 0:
        parser.error("--z0 must be positive")
    return stations


def _y_values(args, stations):
    if args.y_m is not None:
        return args.y_m
    if args.origin_x is None or args.origin_y is None:
        raise SystemExit("Pass --y-m for each station, or --origin-x and --origin-y together with --epsg")
    values = []
    for lat, lon in stations:
        _x_m, y_m = project_wgs84_to_local(lon, lat, args.epsg, args.origin_x, args.origin_y)
        values.append(y_m)
    return values


def _write_tables(output, rows, heat_rows, sample_flag):
    label = "SYNTHETIC ERA5-shaped sample, not a CDS download. " if sample_flag else ""
    write_profile_csv(
        output,
        rows,
        comment=(
            f"# {label}ERA5 pressure-level column converted for the atmospheric case.\n"
            "# T_K is potential temperature. ERA5 temperature is absolute.\n"
            "# w_ms was converted from Pa/s by w = -omega/(rho g).\n"
            "# z_m is metres above the single-level geopotential.\n"
            "# k and epsilon were diagnosed with the given z0. p_Pa is the level.\n"
            f"# sample attribute: {sample_flag or 'none'}\n"
        ),
    )
    print(f"Wrote {output} ({len(rows)} rows). k and epsilon were diagnosed, not downloaded.")
    if heat_rows:
        heat_path = output.with_name(output.stem + "_heatflux.csv")
        write_heatflux_csv(
            heat_path,
            heat_rows,
            comment=(
                "# ERA5 sshf is accumulated J/m2 and positive downward.\n"
                "# q_Wm2 is the deaccumulation, negated, so positive heats the air.\n"
            ),
        )
        print(f"Wrote {heat_path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="UTC day YYYY-MM-DD, required for a CDS download")
    parser.add_argument("--time", action="append", help="UTC time HH:MM, repeatable")
    parser.add_argument("--station", action="append", required=True,
                        help="lat,lon in WGS84 degrees, repeatable. South to north is a good order.")
    parser.add_argument("--epsg", required=True, type=int,
                        help="Projected CRS for the case. This script will not pick one.")
    parser.add_argument("--z0", required=True, type=float, help="Roughness length [m] used only to diagnose k and epsilon")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--y-m", action="append", type=float, default=None,
                        help="Optional y position [m] for each --station, in the same order")
    parser.add_argument("--origin-x", type=float, default=None, help="DEM origin easting, with --origin-y")
    parser.add_argument("--origin-y", type=float, default=None, help="DEM origin northing, with --origin-x")
    parser.add_argument("--solver-times", type=float, nargs="+", default=None,
                        help="Solver seconds for each file time, in file order")
    parser.add_argument("--cache-dir", type=Path, default=Path("downloads/era5"))
    parser.add_argument("--from-files", nargs=2, type=Path, metavar=("PRESSURE_NC", "SINGLE_NC"))
    parser.add_argument("--write-sample", type=Path, default=None,
                        help="Write a labeled synthetic pair under this directory and exit")
    args = parser.parse_args(argv)
    if args.write_sample is not None:
        pressure, single = write_sample_era5(
            args.write_sample / "era5_pressure_sample.nc",
            args.write_sample / "era5_single_sample.nc",
        )
        print(f"Wrote synthetic sample {pressure} and {single}")
        return
    stations = _stations_from_args(parser, args)
    y_values = _y_values(args, stations)
    if args.from_files:
        pressure_file, single_file = args.from_files
    else:
        if not args.date or not args.time:
            parser.error("a CDS download needs --date and at least one --time")
        try:
            import cdsapi
        except ImportError as error:
            raise SystemExit(
                "Missing cdsapi. Install with: python3 -m pip install -r requirements-era5.txt\n"
                "Without a key, rerun with --write-sample and --from-files."
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
                    "u_component_of_wind", "v_component_of_wind", "vertical_velocity",
                    "temperature", "specific_humidity", "geopotential",
                ],
                "pressure_level": list(PRESSURE_LEVELS),
                "year": year, "month": month, "day": day, "time": args.time,
                "area": area, "format": "netcdf",
            },
            str(pressure_file),
        )
        client.retrieve(
            "reanalysis-era5-single-levels",
            {
                "product_type": "reanalysis",
                "variable": ["surface_sensible_heat_flux", "geopotential"],
                "year": year, "month": month, "day": day, "time": args.time,
                "area": area, "format": "netcdf",
            },
            str(single_file),
        )
    rows, heat_rows, sample_flag = decode_era5_pair(
        pressure_file, single_file, stations, y_values, args.z0, args.solver_times,
    )
    _write_tables(args.output, rows, heat_rows, sample_flag)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
