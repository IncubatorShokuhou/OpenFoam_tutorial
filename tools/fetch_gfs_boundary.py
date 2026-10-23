#!/usr/bin/env python3
"""Download a small GFS GRIB2 subset and write the atmospheric boundary CSV.

Source is the NOAA AWS open-data bucket ``noaa-gfs-bdp-pds``. No API key.
The global 0.25 degree file is not stored. The ``.idx`` listing is used to
HTTP-range the messages this case needs, including ``SHTFL`` from the matching
``sfluxgrb`` file. NOMADS filter URLs are documented in the tutorial; this
script uses AWS because a past cycle stays there after NOMADS drops it.

Decoding uses the eccodes Python bindings (the ``ecmwflibs`` wheel supplies
the library). cfgrib is not required.
"""
import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np

from atmospheric_case import (
    GRAVITY,
    diagnose_k_epsilon,
    omega_to_w,
    potential_temperature_from_kelvin,
    write_heatflux_csv,
    write_profile_csv,
)


AWS_ROOT = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
USER_AGENT = "openfoam-tutorial-fetch"
PRESSURE_LEVELS = ("1000 mb", "975 mb", "950 mb", "925 mb", "850 mb")
LEVEL_NAMES = {
    "UGRD": PRESSURE_LEVELS + ("10 m above ground", "100 m above ground"),
    "VGRD": PRESSURE_LEVELS + ("10 m above ground", "100 m above ground"),
    "TMP": PRESSURE_LEVELS + ("2 m above ground", "100 m above ground"),
    "HGT": PRESSURE_LEVELS + ("surface",),
    "SPFH": PRESSURE_LEVELS + ("2 m above ground",),
    "VVEL": PRESSURE_LEVELS,
    "PRES": ("surface",),
    "RH": ("2 m above ground",),
}
FLUX_NAMES = {"SHTFL": ("surface",)}
FIXED_HEIGHT = {
    "2 m above ground": 2.0,
    "10 m above ground": 10.0,
    "100 m above ground": 100.0,
}


def parse_gfs_index(text):
    """Parse a wgrib2-style ``.idx`` file into offset records."""
    records = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split(":")
        if len(parts) < 6:
            continue
        records.append({
            "offset": int(parts[1]),
            "name": parts[3],
            "level": parts[4],
        })
    for index, record in enumerate(records):
        if index + 1 < len(records):
            record["length"] = records[index + 1]["offset"] - record["offset"]
        else:
            record["length"] = None
    return records


def select_messages(records, wanted):
    chosen = []
    for record in records:
        levels = wanted.get(record["name"])
        if levels and record["level"] in levels:
            chosen.append(record)
    return chosen


def _fetch(url, range_header=None):
    headers = {"User-Agent": USER_AGENT}
    if range_header:
        headers["Range"] = range_header
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def gfs_urls(date, cycle, forecast_hour, resolution="0p25"):
    stamp = date.replace("-", "")
    hour = f"{int(forecast_hour):03d}"
    cycle = f"{int(cycle):02d}"
    folder = f"gfs.{stamp}/{cycle}/atmos"
    stem = f"gfs.t{cycle}z.pgrb2.{resolution}.f{hour}"
    flux = f"gfs.t{cycle}z.sfluxgrbf{hour}.grib2"
    return (
        f"{AWS_ROOT}/{folder}/{stem}",
        f"{AWS_ROOT}/{folder}/{flux}",
    )


def download_subset(url, messages, destination):
    destination = Path(destination)
    if destination.exists() and destination.stat().st_size > 0:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        for message in messages:
            start = message["offset"]
            if message["length"] is None:
                header = f"bytes={start}-"
            else:
                header = f"bytes={start}-{start + message['length'] - 1}"
            handle.write(_fetch(url, header))
    return destination


def _grid_axes(gid, eccodes):
    grid_type = eccodes.codes_get(gid, "gridType")
    if grid_type != "regular_ll":
        raise ValueError(f"expected regular_ll, found {grid_type}")
    ni = int(eccodes.codes_get(gid, "Ni"))
    nj = int(eccodes.codes_get(gid, "Nj"))
    lat0 = float(eccodes.codes_get(gid, "latitudeOfFirstGridPointInDegrees"))
    lon0 = float(eccodes.codes_get(gid, "longitudeOfFirstGridPointInDegrees"))
    di = float(eccodes.codes_get(gid, "iDirectionIncrementInDegrees"))
    dj = float(eccodes.codes_get(gid, "jDirectionIncrementInDegrees"))
    j_positive = int(eccodes.codes_get(gid, "jScansPositively"))
    values = np.asarray(eccodes.codes_get_values(gid), dtype=float).reshape(nj, ni)
    latitudes = lat0 + (np.arange(nj) * dj if j_positive else -np.arange(nj) * dj)
    longitudes = lon0 + np.arange(ni) * di
    # GRIB missing values are huge sentinels. A cutoff near 1e4 would also
    # delete surface pressure, which is about 1e5 Pa.
    values = np.where(np.abs(values) > 1.0e10, np.nan, values)
    return latitudes, longitudes, values


def decode_grib(path):
    """Return a dict keyed by (shortName, level) of lat, lon, values."""
    import eccodes
    fields = {}
    with open(path, "rb") as handle:
        while True:
            gid = eccodes.codes_grib_new_from_file(handle)
            if not gid:
                break
            try:
                name = eccodes.codes_get(gid, "shortName")
                level = _level_label(gid, eccodes)
                latitudes, longitudes, values = _grid_axes(gid, eccodes)
            finally:
                eccodes.codes_release(gid)
            fields[(name, level)] = {
                "lat": latitudes,
                "lon": longitudes,
                "values": values,
            }
    return fields


def _level_label(gid, eccodes):
    type_of_level = eccodes.codes_get(gid, "typeOfLevel")
    level = eccodes.codes_get(gid, "level")
    if type_of_level == "isobaricInhPa":
        return f"{int(level)} mb"
    if type_of_level == "surface":
        return "surface"
    if type_of_level == "heightAboveGround":
        return f"{int(level)} m above ground"
    return f"{level} {type_of_level}"


def nearest_value(field, lat, lon):
    latitudes = field["lat"]
    longitudes = field["lon"] % 360.0
    target_lon = float(lon) % 360.0
    j = int(np.argmin(np.abs(latitudes - lat)))
    i = int(np.argmin(np.abs(longitudes - target_lon)))
    return float(field["values"][j, i]), float(latitudes[j]), float(longitudes[i])


def bracket_latitudes(field, lat):
    latitudes = np.asarray(field["lat"], dtype=float)
    order = np.argsort(latitudes)
    sorted_lat = latitudes[order]
    if lat <= sorted_lat[0]:
        return [float(sorted_lat[0])]
    if lat >= sorted_lat[-1]:
        return [float(sorted_lat[-1])]
    upper = int(np.searchsorted(sorted_lat, lat))
    return [float(sorted_lat[upper - 1]), float(sorted_lat[upper])]


def column_from_fields(fields, lat, lon, z0):
    """One vertical column. Heights are metres above the GFS orography.

    Keys are eccodes short names. The AWS index still says UGRD and TMP;
    eccodes renames 10 m wind to ``10u`` and 2 m temperature to ``2t``.
    """
    surface = nearest_value(fields[("orog", "surface")], lat, lon)
    surface_height = surface[0]
    surface_pressure = nearest_value(fields[("sp", "surface")], lat, lon)[0]
    grid_lat, grid_lon = surface[1], surface[2]
    points = []

    def grab(name, level):
        if (name, level) not in fields:
            return None
        value, _, _ = nearest_value(fields[(name, level)], lat, lon)
        return value

    temperature_2m = grab("2t", "2 m above ground")
    humidity_2m = grab("2sh", "2 m above ground") or 0.0
    u10 = grab("10u", "10 m above ground")
    v10 = grab("10v", "10 m above ground")
    if temperature_2m is not None and u10 is not None:
        scale = np.log((2.0 + z0) / z0) / np.log((10.0 + z0) / z0)
        points.append({
            "z": 2.0,
            "u": u10 * scale,
            "v": v10 * scale,
            "w": 0.0,
            "t": temperature_2m,
            "q": humidity_2m,
            "p": surface_pressure,
        })
        points.append({
            "z": 10.0,
            "u": u10,
            "v": v10,
            "w": 0.0,
            "t": temperature_2m,
            "q": humidity_2m,
            "p": float(surface_pressure * np.exp(-GRAVITY * 10.0 / (287.05 * temperature_2m))),
        })
    u100 = grab("u", "100 m above ground")
    v100 = grab("v", "100 m above ground")
    t100 = grab("t", "100 m above ground")
    if u100 is not None and t100 is not None:
        points.append({
            "z": 100.0,
            "u": u100,
            "v": v100,
            "w": 0.0,
            "t": t100,
            "q": humidity_2m,
            "p": float(surface_pressure * np.exp(-GRAVITY * 100.0 / (287.05 * t100))),
        })
    for level_name in PRESSURE_LEVELS:
        height = grab("gh", level_name)
        if height is None:
            continue
        z_agl = height - surface_height
        if z_agl < 5.0:
            continue
        temperature = grab("t", level_name)
        pressure = float(level_name.split()[0]) * 100.0
        omega = grab("w", level_name)
        omega = 0.0 if omega is None else omega
        points.append({
            "z": z_agl,
            "u": grab("u", level_name),
            "v": grab("v", level_name),
            "w": float(omega_to_w(omega, temperature, pressure)),
            "t": temperature,
            "q": grab("q", level_name) or 0.0,
            "p": pressure,
        })
    points.sort(key=lambda item: item["z"])
    z_values = np.array([item["z"] for item in points])
    k_value, epsilon = diagnose_k_epsilon(
        [item["u"] for item in points],
        [item["v"] for item in points],
        np.maximum(z_values, 0.5),
        z0,
    )
    for item, k_item, epsilon_item in zip(points, k_value, epsilon):
        item["k"] = float(k_item)
        item["epsilon"] = float(epsilon_item)
        item["theta"] = potential_temperature_from_kelvin(item["t"], item["p"])
    return {
        "lat": grid_lat,
        "lon": grid_lon,
        "surface_height": surface_height,
        "points": points,
    }


def _project_apart(lon, lat, epsg, origin_x, origin_y):
    """Project in a fresh process.

    eccodes and rasterio both ship PROJ. Calling rasterio after eccodes in
    this process aborts. The CRS is still the one the caller passed.
    """
    code = (
        "import json,sys,rasterio.warp\n"
        "lon,lat,epsg,ox,oy=json.loads(sys.stdin.read())\n"
        "east,north=rasterio.warp.transform('EPSG:4326', f'EPSG:{int(epsg)}', [lon], [lat])\n"
        "json.dump([east[0]-ox, north[0]-oy], sys.stdout)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps([lon, lat, int(epsg), origin_x, origin_y]),
        text=True, capture_output=True, check=True,
    )
    x_m, y_m = json.loads(completed.stdout)
    return float(x_m), float(y_m)


def rows_from_hours(hours, epsg, origin_x, origin_y, z0):
    """``hours`` is a list of (solver_time, fields, site_lat, site_lon, heat_wm2)."""
    rows = []
    heat_rows = []
    stations = None
    for solver_time, fields, site_lat, site_lon, heat_wm2 in hours:
        probe = fields[("orog", "surface")]
        latitudes = bracket_latitudes(probe, site_lat)
        longitudes = [nearest_value(probe, site_lat, site_lon)[2]]
        if stations is None:
            stations = []
            for latitude in latitudes:
                for longitude in longitudes:
                    stations.append((latitude, longitude))
        for latitude, longitude in stations:
            column = column_from_fields(fields, latitude, longitude, z0)
            _x_m, y_m = _project_apart(column["lon"], column["lat"], epsg, origin_x, origin_y)
            station = f"gfs_{column['lat']:.2f}N_{column['lon']:.2f}E"
            thetas = [item["theta"] for item in column["points"] if item["z"] <= 300.0]
            if len(thetas) >= 2 and thetas[-1] <= thetas[0]:
                print(
                    f"Warning: {station} t={solver_time} potential temperature falls "
                    f"from {thetas[0]:.2f} K to {thetas[-1]:.2f} K in the lowest 300 m",
                    file=sys.stderr,
                )
            for item in column["points"]:
                rows.append({
                    "station": station,
                    "time_s": float(solver_time),
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
        if heat_wm2 is not None:
            heat_rows.append({"time_s": float(solver_time), "q_Wm2": float(heat_wm2)})
    return rows, heat_rows


def nearest_on_any_grid(path, short_name, lat, lon):
    """Sample one message. The surface-flux file is a Gaussian grid, not lat/lon."""
    import eccodes
    with open(path, "rb") as handle:
        while True:
            gid = eccodes.codes_grib_new_from_file(handle)
            if not gid:
                break
            try:
                if eccodes.codes_get(gid, "shortName") != short_name:
                    continue
                hits = eccodes.codes_grib_find_nearest(gid, float(lat), float(lon), npoints=1)
                return float(hits[0]["value"])
            finally:
                eccodes.codes_release(gid)
    raise KeyError(f"{short_name} not found in {path}")


def fetch_hour(date, cycle, forecast_hour, cache_dir, resolution="0p25", lat=None, lon=None):
    cache_dir = Path(cache_dir)
    atmos_url, flux_url = gfs_urls(date, cycle, forecast_hour, resolution)
    atmos_idx = _fetch(atmos_url + ".idx").decode("ascii", errors="replace")
    flux_idx = _fetch(flux_url + ".idx").decode("ascii", errors="replace")
    atmos_messages = select_messages(parse_gfs_index(atmos_idx), LEVEL_NAMES)
    flux_messages = select_messages(parse_gfs_index(flux_idx), FLUX_NAMES)
    if len(atmos_messages) < 10:
        raise RuntimeError(f"GFS index at {atmos_url}.idx did not list the expected messages")
    stamp = f"{date.replace('-', '')}_t{int(cycle):02d}_f{int(forecast_hour):03d}"
    atmos_path = download_subset(atmos_url, atmos_messages, cache_dir / f"{stamp}_atmos.grib2")
    flux_path = download_subset(flux_url, flux_messages, cache_dir / f"{stamp}_flux.grib2")
    fields = decode_grib(atmos_path)
    heat = None
    if lat is not None and flux_messages:
        heat = nearest_on_any_grid(flux_path, "ishf", lat, lon)
    return fields, heat


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Cycle day YYYY-MM-DD")
    parser.add_argument("--cycle", default="00", help="Cycle hour, usually 00, 06, 12 or 18")
    parser.add_argument("--forecast-hour", type=int, action="append", required=True,
                        help="Forecast hour, repeatable. Valid time is cycle plus this hour.")
    parser.add_argument("--solver-times", type=float, nargs="+", required=True,
                        help="Solver seconds for each --forecast-hour, same order")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--epsg", type=int, required=True,
                        help="Case CRS. This script will not guess one from the longitude.")
    parser.add_argument("--origin-x", type=float, required=True)
    parser.add_argument("--origin-y", type=float, required=True)
    parser.add_argument("--z0", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolution", default="0p25", choices=("0p25", "0p50"))
    parser.add_argument("--cache-dir", type=Path, default=Path("downloads/gfs"))
    args = parser.parse_args(argv)
    if len(args.solver_times) != len(args.forecast_hour):
        parser.error("--solver-times must match --forecast-hour")
    if args.z0 <= 0:
        parser.error("--z0 must be positive")
    hours = []
    for forecast_hour, solver_time in zip(args.forecast_hour, args.solver_times):
        print(f"Fetching GFS {args.date} cycle {args.cycle} f{forecast_hour:03d}", file=sys.stderr)
        fields, heat = fetch_hour(
            args.date, args.cycle, forecast_hour, args.cache_dir, args.resolution, args.lat, args.lon,
        )
        hours.append((solver_time, fields, args.lat, args.lon, heat))
    rows, heat_rows = rows_from_hours(hours, args.epsg, args.origin_x, args.origin_y, args.z0)
    write_profile_csv(
        args.output,
        rows,
        comment=(
            f"# GFS {args.resolution} from {AWS_ROOT}, cycle {args.date} {args.cycle}Z.\n"
            f"# Forecast hours {args.forecast_hour} mapped to solver times {args.solver_times}.\n"
            f"# Site request {args.lat}N {args.lon}E, projected with EPSG:{args.epsg}.\n"
            "# T_K is potential temperature. GFS TMP is absolute. VVEL is Pa/s and was\n"
            "# converted with w = -omega/(rho g). 2 m wind is the 10 m wind log-scaled\n"
            f"# with z0={args.z0}. k and epsilon are diagnosed, not in the GRIB.\n"
            "# Surface heat flux is the idx name SHTFL. eccodes calls it ishf,\n"
            "# instantaneous W/m2, positive upward.\n"
            "# GRIB subsets stay in downloads/gfs and are not part of the tutorial commit.\n"
        ),
    )
    print(f"Wrote {args.output} ({len(rows)} rows)")
    if heat_rows:
        heat_path = args.output.with_name("gfs_heatflux.csv")
        write_heatflux_csv(
            heat_path,
            heat_rows,
            comment=(
                "# GFS SHTFL surface sensible heat flux, W/m2, positive upward.\n"
                "# Taken from gfs.tCCz.sfluxgrbfFFF.grib2 on noaa-gfs-bdp-pds.\n"
            ),
        )
        print(f"Wrote {heat_path}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
