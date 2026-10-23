#!/usr/bin/env python3
"""Plot an OpenFOAM cavity result exported by foamToVTK -ascii."""
import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def read_legacy_vtk(path: Path):
    text = path.read_text(encoding="ascii")
    if "\nASCII\n" not in text:
        raise ValueError("VTK must be ASCII; run foamToVTK with -ascii")
    tokens = text.split()

    def locate(word, start=0):
        try:
            return tokens.index(word, start)
        except ValueError as error:
            raise ValueError(f"VTK section not found: {word}") from error

    point_pos = locate("POINTS")
    point_count = int(tokens[point_pos + 1])
    start = point_pos + 3
    points = np.asarray(tokens[start : start + 3 * point_count], dtype=float).reshape(-1, 3)

    cell_pos = locate("CELLS", start + 3 * point_count)
    cell_count = int(tokens[cell_pos + 1])
    cursor = cell_pos + 3
    cells = []
    for _ in range(cell_count):
        size = int(tokens[cursor])
        cursor += 1
        cells.append(np.asarray(tokens[cursor : cursor + size], dtype=int))
        cursor += size

    data_pos = locate("CELL_DATA", cursor)
    if int(tokens[data_pos + 1]) != cell_count:
        raise ValueError("CELL_DATA size does not match CELLS")
    field_pos = locate("FIELD", data_pos)
    field_count = int(tokens[field_pos + 2])
    cursor = field_pos + 3
    fields = {}
    for _ in range(field_count):
        name = tokens[cursor]
        components = int(tokens[cursor + 1])
        tuples = int(tokens[cursor + 2])
        cursor += 4
        size = components * tuples
        fields[name] = np.asarray(tokens[cursor : cursor + size], dtype=float).reshape(tuples, components)
        cursor += size
    centers = np.asarray([points[cell].mean(axis=0) for cell in cells])
    return points, cells, centers, fields


def regular_grid(centers, values):
    x_values = np.unique(np.round(centers[:, 0], 12))
    y_values = np.unique(np.round(centers[:, 1], 12))
    if len(x_values) * len(y_values) != len(centers):
        raise ValueError("streamplot requires a regular x-y grid")
    result = np.empty((len(y_values), len(x_values)))
    x_index = {value: index for index, value in enumerate(x_values)}
    y_index = {value: index for index, value in enumerate(y_values)}
    for center, value in zip(centers, values):
        result[y_index[round(center[1], 12)], x_index[round(center[0], 12)]] = value
    return x_values, y_values, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vtk", type=Path)
    parser.add_argument("--output", type=Path, default=Path("cavity_result.png"))
    args = parser.parse_args()
    points, cells, centers, fields = read_legacy_vtk(args.vtk)
    if "U" not in fields or "p" not in fields:
        raise SystemExit("VTK must contain cell fields U and p")
    velocity = fields["U"]
    pressure = fields["p"][:, 0]
    speed = np.linalg.norm(velocity[:, :2], axis=1)
    x, y, u = regular_grid(centers, velocity[:, 0])
    _, _, v = regular_grid(centers, velocity[:, 1])

    plt.rcParams.update({
        "font.size": 10,
        "axes.titlesize": 12,
        "font.sans-serif": ["WenQuanYi Micro Hei", "Droid Sans Fallback", "DejaVu Sans"],
        "axes.unicode_minus": False,
    })
    figure, axes = plt.subplots(1, 3, figsize=(15, 4.7), constrained_layout=True)
    for coordinate in np.unique(np.round(points[:, 0], 12)):
        axes[0].axvline(coordinate, color="#8da0ae", linewidth=0.35)
    for coordinate in np.unique(np.round(points[:, 1], 12)):
        axes[0].axhline(coordinate, color="#8da0ae", linewidth=0.35)
    skip = np.arange(len(centers)) % 2 == 0
    axes[0].quiver(
        centers[skip, 0], centers[skip, 1], velocity[skip, 0], velocity[skip, 1],
        speed[skip], cmap="viridis", scale=12, width=0.004,
    )
    axes[0].set_title("A. 400 个控制体与速度箭头")

    filled = axes[1].tricontourf(centers[:, 0], centers[:, 1], speed, levels=20, cmap="viridis")
    axes[1].streamplot(x, y, u, v, color="white", density=1.25, linewidth=0.7, arrowsize=0.8)
    figure.colorbar(filled, ax=axes[1], label="速度大小 |U| (m/s)")
    axes[1].set_title("B. 速度大小与流线")

    pressure_plot = axes[2].tricontourf(centers[:, 0], centers[:, 1], pressure, levels=20, cmap="coolwarm")
    pressure_lines = axes[2].tricontour(centers[:, 0], centers[:, 1], pressure, levels=8, colors="k", linewidths=0.45)
    axes[2].clabel(pressure_lines, fontsize=7, inline=True)
    figure.colorbar(pressure_plot, ax=axes[2], label="运动压力 p (m²/s²)")
    axes[2].set_title("C. 运动压力场")

    for axis in axes:
        axis.set_aspect("equal")
        axis.set_xlim(0, 0.1)
        axis.set_ylim(0, 0.1)
        axis.set_xlabel("x (m)")
        axis.set_ylabel("y (m)")
        axis.plot([0, 0.1], [0.1, 0.1], color="#d62728", linewidth=3)
    figure.suptitle("OpenFOAM v14 方腔流真实结果：t = 10 s（红线为向右运动的上壁面）", fontsize=14)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=180)
    print(
        f"cells={len(cells)}, points={len(points)}, "
        f"speed=[{speed.min():.6g}, {speed.max():.6g}] m/s; wrote {args.output}"
    )


if __name__ == "__main__":
    main()
