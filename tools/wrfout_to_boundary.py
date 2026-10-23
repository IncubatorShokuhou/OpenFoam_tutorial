#!/usr/bin/env python3
"""Read a WRF ``wrfout`` NetCDF and write the atmospheric boundary CSV.

WRF output from the owner's own run is the intended input. This repository
does not ship a real forecast. ``--write-sample`` creates a tiny file with
WRF dimension names and the global attribute ``tutorial_sample=synthetic``.
The walkthrough below that attribute is a format exercise.

Heights come from ``(PH + PHB) / g`` on the staggered vertical faces, then
the two faces of a cell are averaged onto the mass point. ``U``, ``V`` and
``W`` are averaged from their staggered faces onto the same mass point.
``T`` in the file is perturbation potential temperature; the value written
for OpenFOAM is ``T + 300``. Pressure is ``P + PB``. Humidity is ``QVAPOR``.

``XLAT`` and ``XLONG`` are projected with the EPSG you pass. The script does
not read ``MAP_PROJ`` and will not guess a CRS.
"""
import argparse
import sys
from pathlib import Path

import numpy as np

from atmospheric_case import (
    GRAVITY,
    diagnose_k_epsilon,
    project_wgs84_to_local,
    write_heatflux_csv,
    write_profile_csv,
)


def destagger(values, axis):
    """Average the two staggered faces onto the mass point along ``axis``."""
    values = np.asarray(values, dtype=float)
    sl_hi = [slice(None)] * values.ndim
    sl_lo = [slice(None)] * values.ndim
    sl_hi[axis] = slice(1, None)
    sl_lo[axis] = slice(None, -1)
    return 0.5 * (values[tuple(sl_hi)] + values[tuple(sl_lo)])


def mass_fields(dataset):
    """Return unstaggered arrays on WRF mass points for one file."""
    u_mass = destagger(dataset.variables["U"][:], axis=3)
    v_mass = destagger(dataset.variables["V"][:], axis=2)
    w_mass = destagger(dataset.variables["W"][:], axis=1)
    ph = np.asarray(dataset.variables["PH"][:], dtype=float)
    phb = np.asarray(dataset.variables["PHB"][:], dtype=float)
    height_stag = (ph + phb) / GRAVITY
    height = destagger(height_stag, axis=1)
    terrain = np.asarray(dataset.variables["HGT"][:], dtype=float)
    if terrain.ndim == 2:
        terrain = np.broadcast_to(terrain, height.shape[:1] + terrain.shape)
    theta = np.asarray(dataset.variables["T"][:], dtype=float) + 300.0
    pressure = np.asarray(dataset.variables["P"][:], dtype=float) + np.asarray(dataset.variables["PB"][:], dtype=float)
    humidity = np.asarray(dataset.variables["QVAPOR"][:], dtype=float)
    latitude = np.asarray(dataset.variables["XLAT"][:], dtype=float)
    longitude = np.asarray(dataset.variables["XLONG"][:], dtype=float)
    if latitude.ndim == 2:
        latitude = np.broadcast_to(latitude, (height.shape[0],) + latitude.shape)
        longitude = np.broadcast_to(longitude, latitude.shape)
    heat = None
    if "HFX" in dataset.variables:
        heat = np.asarray(dataset.variables["HFX"][:], dtype=float)
    sample = ""
    if "tutorial_sample" in dataset.ncattrs():
        sample = str(dataset.getncattr("tutorial_sample"))
    return {
        "u": u_mass,
        "v": v_mass,
        "w": w_mass,
        "height": height,
        "terrain": np.asarray(terrain, dtype=float),
        "theta": theta,
        "pressure": pressure,
        "q": humidity,
        "lat": np.asarray(latitude, dtype=float),
        "lon": np.asarray(longitude, dtype=float),
        "heat": heat,
        "sample": sample,
    }


def rows_from_wrf(path, epsg, origin_x, origin_y, z0, solver_times):
    import netCDF4
    with netCDF4.Dataset(path) as dataset:
        fields = mass_fields(dataset)
    n_time = fields["u"].shape[0]
    if len(solver_times) != n_time:
        raise ValueError(f"solver_times has {len(solver_times)} values and the file has {n_time} times")
    local_x, local_y = project_wgs84_to_local(
        fields["lon"][0], fields["lat"][0], epsg, origin_x, origin_y,
    )
    rows = []
    ny, nx = local_x.shape
    for time_index, time_s in enumerate(solver_times):
        for j in range(ny):
            for i in range(nx):
                z_agl = fields["height"][time_index, :, j, i] - fields["terrain"][time_index, j, i]
                order = np.argsort(z_agl)
                z_sorted = np.maximum(z_agl[order], 0.5)
                u_sorted = fields["u"][time_index, order, j, i]
                v_sorted = fields["v"][time_index, order, j, i]
                k_value, epsilon = diagnose_k_epsilon(u_sorted, v_sorted, z_sorted, z0)
                station = f"wrf_{j}_{i}"
                for level, k_item, epsilon_item in zip(order, k_value, epsilon):
                    rows.append({
                        "station": station,
                        "time_s": float(time_s),
                        "x_m": float(local_x[j, i]),
                        "y_m": float(local_y[j, i]),
                        "z_m": float(max(z_agl[level], 0.0)),
                        "u_ms": float(fields["u"][time_index, level, j, i]),
                        "v_ms": float(fields["v"][time_index, level, j, i]),
                        "w_ms": float(fields["w"][time_index, level, j, i]),
                        "T_K": float(fields["theta"][time_index, level, j, i]),
                        "q_kgkg": float(fields["q"][time_index, level, j, i]),
                        "p_Pa": float(fields["pressure"][time_index, level, j, i]),
                        "k_m2s2": float(k_item),
                        "epsilon_m2s3": float(epsilon_item),
                    })
    heat_rows = []
    if fields["heat"] is not None:
        for time_index, time_s in enumerate(solver_times):
            heat_rows.append({
                "time_s": float(time_s),
                "q_Wm2": float(np.mean(fields["heat"][time_index])),
            })
    return rows, heat_rows, fields["sample"]


def write_sample_wrfout(path, origin_x, origin_y, epsg=32650):
    """A 5 by 4 by 5 mass grid in WRF layout, labeled synthetic.

    Lat/lon are the inverse of ``epsg`` from ``origin_x/y`` plus a local
    spacing of 150 m by 120 m, so the same origin maps the file back onto
    the Jingshan clip.
    """
    import netCDF4
    import rasterio.warp
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    nx, ny, nz = 5, 4, 5
    x_local = np.arange(nx) * 150.0
    y_local = np.arange(ny) * 120.0
    east = origin_x + x_local[None, :]
    north = origin_y + y_local[:, None]
    lon, lat = rasterio.warp.transform(
        f"EPSG:{int(epsg)}", "EPSG:4326",
        np.broadcast_to(east, (ny, nx)).ravel(),
        np.broadcast_to(north, (ny, nx)).ravel(),
    )
    lat = np.asarray(lat).reshape(ny, nx)
    lon = np.asarray(lon).reshape(ny, nx)
    n_time = 2
    with netCDF4.Dataset(path, "w") as dataset:
        dataset.TITLE = "synthetic wrfout for the OpenFOAM tutorial"
        dataset.tutorial_sample = "synthetic wrfout-format NetCDF, not a WRF forecast"
        dataset.DX = 150.0
        dataset.DY = 120.0
        dataset.createDimension("Time", n_time)
        dataset.createDimension("DateStrLen", 19)
        dataset.createDimension("west_east", nx)
        dataset.createDimension("south_north", ny)
        dataset.createDimension("bottom_top", nz)
        dataset.createDimension("west_east_stag", nx + 1)
        dataset.createDimension("south_north_stag", ny + 1)
        dataset.createDimension("bottom_top_stag", nz + 1)
        times = dataset.createVariable("Times", "S1", ("Time", "DateStrLen"))
        for index, stamp in enumerate((b"2025-01-15_00:00:00", b"2025-01-15_01:00:00")):
            times[index] = np.array(list(stamp.decode()), dtype="S1")
        xlat = dataset.createVariable("XLAT", "f8", ("Time", "south_north", "west_east"))
        xlong = dataset.createVariable("XLONG", "f8", ("Time", "south_north", "west_east"))
        hgt = dataset.createVariable("HGT", "f8", ("Time", "south_north", "west_east"))
        xlat[:] = lat
        xlong[:] = lon
        hgt[:] = 50.0
        # Staggered winds. Mass-point u increases with height and slightly in y.
        u_stag = np.zeros((n_time, nz, ny, nx + 1))
        v_stag = np.zeros((n_time, nz, ny + 1, nx))
        w_stag = np.zeros((n_time, nz + 1, ny, nx))
        theta_p = np.zeros((n_time, nz, ny, nx))
        pressure_p = np.zeros((n_time, nz, ny, nx))
        pressure_b = np.zeros_like(pressure_p)
        qvapor = np.zeros_like(theta_p)
        dz = 40.0
        for k in range(nz):
            z_agl = (k + 0.5) * dz
            u_stag[:, k, :, :] = 2.0 + 0.01 * z_agl
            v_stag[:, k, :, :] = 0.3
            theta_p[:, k, :, :] = (263.0 + 0.02 * z_agl) - 300.0
            pressure_b[:, k, :, :] = 101325.0 * np.exp(-GRAVITY * z_agl / (287.05 * 268.0))
            qvapor[:, k, :, :] = 0.0008 - 0.000001 * z_agl
        u_stag[:, :, :, :] += 0.0
        u_stag[1] += 0.5
        w_stag[:, 1:-1, :, :] = 0.05
        phb = np.zeros((n_time, nz + 1, ny, nx))
        for k in range(nz + 1):
            phb[:, k, :, :] = GRAVITY * (50.0 + k * dz)
        dataset.createVariable("U", "f8", ("Time", "bottom_top", "south_north", "west_east_stag"))[:] = u_stag
        dataset.createVariable("V", "f8", ("Time", "bottom_top", "south_north_stag", "west_east"))[:] = v_stag
        dataset.createVariable("W", "f8", ("Time", "bottom_top_stag", "south_north", "west_east"))[:] = w_stag
        dataset.createVariable("PH", "f8", ("Time", "bottom_top_stag", "south_north", "west_east"))[:] = 0.0
        dataset.createVariable("PHB", "f8", ("Time", "bottom_top_stag", "south_north", "west_east"))[:] = phb
        dataset.createVariable("T", "f8", ("Time", "bottom_top", "south_north", "west_east"))[:] = theta_p
        dataset.createVariable("P", "f8", ("Time", "bottom_top", "south_north", "west_east"))[:] = pressure_p
        dataset.createVariable("PB", "f8", ("Time", "bottom_top", "south_north", "west_east"))[:] = pressure_b
        dataset.createVariable("QVAPOR", "f8", ("Time", "bottom_top", "south_north", "west_east"))[:] = qvapor
        hfx = dataset.createVariable("HFX", "f8", ("Time", "south_north", "west_east"))
        hfx[0] = 18.0
        hfx[1] = 10.0
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wrfout", type=Path, help="Path to wrfout_d0x_YYYY-mm-dd_HH:MM:SS")
    parser.add_argument("--write-sample", type=Path, help="Write a labeled synthetic wrfout and exit")
    parser.add_argument("--epsg", type=int, help="Case CRS. Required unless only --write-sample is used.")
    parser.add_argument("--origin-x", type=float, required=True)
    parser.add_argument("--origin-y", type=float, required=True)
    parser.add_argument("--z0", type=float, default=0.1)
    parser.add_argument("--solver-times", type=float, nargs="+", default=None)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.write_sample is not None:
        if args.epsg is None:
            parser.error("--write-sample needs --epsg so the lat/lon match the case")
        path = write_sample_wrfout(args.write_sample, args.origin_x, args.origin_y, args.epsg)
        print(f"Wrote synthetic wrfout {path}")
        if args.output is None:
            return
        args.wrfout = path
    if args.wrfout is None or args.output is None or args.epsg is None or args.solver_times is None:
        parser.error("converting needs --wrfout, --output, --epsg and --solver-times")
    if args.z0 <= 0:
        parser.error("--z0 must be positive")
    rows, heat_rows, sample = rows_from_wrf(
        args.wrfout, args.epsg, args.origin_x, args.origin_y, args.z0, args.solver_times,
    )
    label = "SYNTHETIC wrfout sample, not a WRF forecast. " if sample else ""
    write_profile_csv(
        args.output,
        rows,
        comment=(
            f"# {label}Columns sampled on WRF mass points.\n"
            "# U, V, W were destaggered by averaging the two faces of each cell.\n"
            "# z_m is (PH+PHB)/g minus HGT. T_K is WRF T + 300, already potential temperature.\n"
            "# p_Pa is P+PB. q_kgkg is QVAPOR. k and epsilon are diagnosed.\n"
            f"# Projected with EPSG:{args.epsg}. MAP_PROJ inside the file was ignored.\n"
            f"# sample attribute: {sample or 'none'}\n"
        ),
    )
    print(f"Wrote {args.output} ({len(rows)} rows)")
    if heat_rows:
        heat_path = args.output.with_name("wrf_heatflux.csv")
        write_heatflux_csv(
            heat_path,
            heat_rows,
            comment="# WRF HFX domain mean, W/m2, positive upward into the air.\n",
        )
        print(f"Wrote {heat_path}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
