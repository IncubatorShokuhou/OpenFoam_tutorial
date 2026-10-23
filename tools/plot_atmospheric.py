#!/usr/bin/env python3
"""Draw the atmospheric lesson figures from the case DEM, mesh and VTK."""
import argparse
import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atmospheric_case import _bracket, interpolate_profile, load_profiles, read_dem
from plot_cavity import read_legacy_vtk


def read_meta(path):
    meta = {}
    for line in Path(path).read_text(encoding="ascii").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            meta[parts[0]] = parts[1]
    return meta


def read_points(path):
    """Read an ascii polyMesh points file. Vectors may be `(x y z)` or bare numbers."""
    text = Path(path).read_text(encoding="ascii")
    body = text.split("}", 1)[-1]
    numbers = re.findall(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?", body)
    if not numbers:
        raise SystemExit(f"No coordinates in {path}")
    count = int(float(numbers[0]))
    values = np.asarray(numbers[1:1 + 3 * count], dtype=float)
    if values.size != 3 * count:
        raise SystemExit(f"{path} declared {count} points but parsed {values.size // 3}")
    return values.reshape(count, 3)


def configure_font():
    plt.rcParams.update({
        "font.size": 10,
        "axes.titlesize": 12,
        "font.sans-serif": ["WenQuanYi Micro Hei", "Droid Sans Fallback", "DejaVu Sans"],
        "axes.unicode_minus": False,
    })


def plot_terrain(dem, output):
    figure, axis = plt.subplots(figsize=(7.2, 4.6), constrained_layout=True)
    image = axis.pcolormesh(dem["x"], dem["y"], dem["height"], shading="auto", cmap="terrain")
    contours = axis.contour(dem["x"], dem["y"], dem["height"], levels=8, colors="k", linewidths=0.4)
    axis.clabel(contours, fontsize=7, inline=True, fmt="%.0f")
    figure.colorbar(image, ax=axis, label="高程 (m)")
    axis.set_aspect("equal")
    axis.set_xlabel("x (m)")
    axis.set_ylabel("y (m)")
    axis.set_title(f"投影 DEM 高程（{dem['crs']}）")
    figure.savefig(output, dpi=160)
    plt.close(figure)


def plot_mesh(points, meta, output):
    nx = int(meta["nx"])
    ny = int(meta["ny"])
    nz = int(meta["nz"])
    grid = points.reshape((nz + 1, ny + 1, nx + 1, 3))
    j = ny // 2
    slab = grid[:, j, :, :]
    figure, axis = plt.subplots(figsize=(7.4, 4.2), constrained_layout=True)
    for i in range(nx + 1):
        axis.plot(slab[:, i, 0], slab[:, i, 2], color="#4c566a", linewidth=0.4)
    for k in range(nz + 1):
        axis.plot(slab[k, :, 0], slab[k, :, 2], color="#4c566a", linewidth=0.4)
    axis.set_aspect("equal")
    axis.set_xlabel("x (m)")
    axis.set_ylabel("z (m)")
    axis.set_title(f"地形跟随网格，y = {slab[0, 0, 1]:.0f} m 的 x-z 截面")
    figure.savefig(output, dpi=160)
    plt.close(figure)


def slice_mask(centers, y_target, thickness):
    return np.abs(centers[:, 1] - y_target) <= thickness


def filled_slice(axis, centers, values, mask, label, cmap):
    image = axis.tricontourf(centers[mask, 0], centers[mask, 2], values[mask], levels=16, cmap=cmap)
    axis.set_xlabel("x (m)")
    axis.set_ylabel("z (m)")
    return image, label


def height_agl(centers, dem):
    """Cell-centre height above the DEM, in the same local metres as the mesh."""
    x_nodes = [float(value) for value in dem["x"]]
    y_nodes = [float(value) for value in dem["y"]]
    ground = dem["height"]
    agl = np.empty(len(centers))
    for index, (x_m, y_m, z_m) in enumerate(centers):
        i0, i1, wx = _bracket(x_nodes, float(x_m))
        j0, j1, wy = _bracket(y_nodes, float(y_m))
        low = (1.0 - wx) * ground[j0, i0] + wx * ground[j0, i1]
        high = (1.0 - wx) * ground[j1, i0] + wx * ground[j1, i1]
        agl[index] = float(z_m) - ((1.0 - wy) * low + wy * high)
    return agl


def plot_fields(vtk_path, output_dir, profiles_path, dem):
    _points, _cells, centers, fields = read_legacy_vtk(Path(vtk_path))
    if "U" not in fields or "T" not in fields or "q" not in fields:
        raise SystemExit("VTK is missing U, T or q")
    speed = np.linalg.norm(fields["U"], axis=1)
    y_values = np.unique(np.round(centers[:, 1], 6))
    y_target = float(y_values[len(y_values) // 2])
    if len(y_values) > 1:
        thickness = 0.51 * float(np.min(np.diff(y_values)))
    else:
        thickness = 1.0
    mask = slice_mask(centers, y_target, thickness)
    if mask.sum() < 4:
        raise SystemExit("Not enough cells on the vertical slice")

    figure, axis = plt.subplots(figsize=(7.6, 4.2), constrained_layout=True)
    image, _label = filled_slice(axis, centers, speed, mask, "风速", "viridis")
    step = max(1, int(mask.sum() / 80))
    chosen = np.flatnonzero(mask)[::step]
    axis.quiver(
        centers[chosen, 0], centers[chosen, 2],
        fields["U"][chosen, 0], fields["U"][chosen, 2],
        color="k", scale=0.05, width=0.0022,
    )
    figure.colorbar(image, ax=axis, label="|U| (m/s)")
    axis.set_title(f"风速与 x-z 矢量，y ≈ {y_target:.0f} m")
    figure.savefig(output_dir / "atm_wind.png", dpi=160)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(7.6, 4.2), constrained_layout=True)
    image, _label = filled_slice(axis, centers, fields["T"][:, 0], mask, "位温", "coolwarm")
    figure.colorbar(image, ax=axis, label="T (K)，本算例为位温")
    axis.set_title(f"位温，y ≈ {y_target:.0f} m")
    figure.savefig(output_dir / "atm_temperature.png", dpi=160)
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(7.6, 4.2), constrained_layout=True)
    image, _label = filled_slice(axis, centers, fields["q"][:, 0] * 1000.0, mask, "比湿", "Blues")
    figure.colorbar(image, ax=axis, label="比湿 q (g/kg)")
    axis.set_title(f"比湿，y ≈ {y_target:.0f} m")
    figure.savefig(output_dir / "atm_humidity.png", dpi=160)
    plt.close(figure)

    plot_profiles(centers, fields, dem, y_target, profiles_path, output_dir / "atm_profiles.png")
    return {
        "cells": len(centers),
        "speed_min": float(speed.min()),
        "speed_max": float(speed.max()),
        "T_min": float(fields["T"][:, 0].min()),
        "T_max": float(fields["T"][:, 0].max()),
        "q_min": float(fields["q"][:, 0].min()),
        "q_max": float(fields["q"][:, 0].max()),
    }


def binned_profile(x, z, values, x_min, x_max, bins=12):
    chosen = (x >= x_min) & (x < x_max)
    if chosen.sum() < bins:
        return np.array([]), np.array([])
    edges = np.linspace(z[chosen].min(), z[chosen].max(), bins + 1)
    centers = []
    means = []
    for lower, upper in zip(edges[:-1], edges[1:]):
        group = chosen & (z >= lower) & (z < upper if upper < edges[-1] else z <= upper)
        if group.any():
            centers.append(0.5 * (lower + upper))
            means.append(values[group].mean())
    return np.asarray(centers), np.asarray(means)


def plot_profiles(centers, fields, dem, y_target, profiles_path, output):
    x = centers[:, 0]
    z = height_agl(centers, dem)
    speed = np.linalg.norm(fields["U"], axis=1)
    x_min = float(x.min())
    dx = float(np.min(np.diff(np.unique(np.round(x, 5))))) if len(np.unique(np.round(x, 5))) > 1 else 25.0
    upstream = (x_min, x_min + 1.6 * dx)
    peak = np.unravel_index(int(np.argmax(dem["height"])), dem["height"].shape)
    crest_x = float(dem["x"][peak[1]])
    crest = (crest_x - 1.2 * dx, crest_x + 1.2 * dx)
    records = load_profiles(profiles_path)
    times = sorted({row["time_s"] for row in records})
    sample_z = np.linspace(2.0, min(180.0, max(float(z.max()), 10.0)), 40)
    sample = [interpolate_profile(records, times[-1], y_target, height) for height in sample_z]
    figure, axes = plt.subplots(1, 4, figsize=(12.5, 4.4), constrained_layout=True, sharey=True)
    series = (
        (speed, np.hypot([row["u_ms"] for row in sample], [row["v_ms"] for row in sample]), "|U| (m/s)"),
        (fields["T"][:, 0], [row["T_K"] for row in sample], "T (K)"),
        (fields["q"][:, 0] * 1000.0, [row["q_kgkg"] * 1000.0 for row in sample], "q (g/kg)"),
    )
    for axis, (solved, reference, label) in zip(axes[:3], series):
        z_up, v_up = binned_profile(x, z, solved, *upstream)
        z_crest, v_crest = binned_profile(x, z, solved, *crest)
        axis.plot(reference, sample_z, color="#999999", linewidth=1.2, label="入口表")
        if len(z_up):
            axis.plot(v_up, z_up, color="#1f4e79", marker="o", markersize=3, label="入口第一列")
        if len(z_crest):
            axis.plot(v_crest, z_crest, color="#b85c38", marker="s", markersize=3, label="高点附近")
        axis.set_xlabel(label)
        axis.grid(True, linewidth=0.3)
    if "p_rgh" in fields:
        z_up, v_up = binned_profile(x, z, fields["p_rgh"][:, 0], *upstream)
        z_crest, v_crest = binned_profile(x, z, fields["p_rgh"][:, 0], *crest)
        if len(z_up):
            axes[3].plot(v_up, z_up, color="#1f4e79", marker="o", markersize=3, label="入口第一列")
        if len(z_crest):
            axes[3].plot(v_crest, z_crest, color="#b85c38", marker="s", markersize=3, label="高点附近")
    axes[3].set_xlabel("p_rgh (Pa)")
    axes[3].grid(True, linewidth=0.3)
    axes[0].set_ylabel("离地高度 (m)")
    axes[0].legend(fontsize=7, loc="best")
    figure.suptitle("入口表、入口第一列和高点附近的剖面")
    figure.savefig(output, dpi=160)
    plt.close(figure)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--vtk", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, default=None)
    args = parser.parse_args(argv)
    configure_font()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    dem = read_dem(args.case / "dem_utm.tif")
    meta = read_meta(args.case / "constant" / "terrainCase")
    points = read_points(args.case / "constant" / "polyMesh" / "points")
    plot_terrain(dem, args.output_dir / "atm_terrain.png")
    plot_mesh(points, meta, args.output_dir / "atm_mesh.png")
    profiles = args.profiles
    if profiles is None:
        profiles = Path(__file__).resolve().parents[1] / "tutorial" / "data" / "beijing_boundary.csv"
    stats = plot_fields(args.vtk, args.output_dir, profiles, dem)
    print(
        "cells={cells}, speed=[{speed_min:.4g}, {speed_max:.4g}] m/s, "
        "T=[{T_min:.4g}, {T_max:.4g}] K, q=[{q_min:.4g}, {q_max:.4g}] kg/kg".format(**stats)
    )
    print(f"Wrote figures to {args.output_dir}")


if __name__ == "__main__":
    main()
