#!/usr/bin/env python3
"""Convert a projected GeoTIFF DEM to an ASCII STL terrain surface."""
import argparse
from pathlib import Path
import numpy as np
import rasterio


def triangle(normal_unused, vertices):
    a, b, c = vertices
    normal = np.cross(b - a, c - a)
    norm = np.linalg.norm(normal)
    if norm:
        normal /= norm
    lines = [f"  facet normal {normal[0]:.9g} {normal[1]:.9g} {normal[2]:.9g}", "    outer loop"]
    lines += [f"      vertex {p[0]:.9g} {p[1]:.9g} {p[2]:.9g}" for p in vertices]
    lines += ["    endloop", "  endfacet"]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="projected, north-up GeoTIFF DEM")
    parser.add_argument("output", type=Path, help="output ASCII STL")
    parser.add_argument("--stride", type=int, default=1, help="keep every Nth raster point")
    parser.add_argument("--z-scale", type=float, default=1.0, help="vertical exaggeration")
    parser.add_argument("--name", default="terrain")
    args = parser.parse_args()
    if args.stride < 1:
        parser.error("--stride must be >= 1")

    with rasterio.open(args.input) as src:
        if src.crs is None or src.crs.is_geographic:
            raise SystemExit("Input must have a projected CRS in metres; reproject it with gdalwarp first.")
        if src.transform.b != 0 or src.transform.d != 0:
            raise SystemExit("Rotated rasters are unsupported; create a north-up GeoTIFF first.")
        z = src.read(1, masked=True)[:: args.stride, :: args.stride]
        transform = src.transform
        rows = np.arange(0, src.height, args.stride)[: z.shape[0]]
        cols = np.arange(0, src.width, args.stride)[: z.shape[1]]
        x = transform.c + (cols + 0.5) * transform.a
        y = transform.f + (rows + 0.5) * transform.e

    if z.shape[0] < 2 or z.shape[1] < 2:
        raise SystemExit("DEM must contain at least 2x2 retained cells")
    x = x - x.min()
    y = y - y.min()
    z = z.astype(float) * args.z_scale
    args.output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with args.output.open("w", encoding="ascii") as stream:
        stream.write(f"solid {args.name}\n")
        for row in range(z.shape[0] - 1):
            for col in range(z.shape[1] - 1):
                values = [z[row, col], z[row, col + 1], z[row + 1, col + 1], z[row + 1, col]]
                if any(np.ma.is_masked(value) for value in values):
                    continue
                p00 = np.array([x[col], y[row], values[0]])
                p10 = np.array([x[col + 1], y[row], values[1]])
                p11 = np.array([x[col + 1], y[row + 1], values[2]])
                p01 = np.array([x[col], y[row + 1], values[3]])
                stream.write(triangle(None, (p00, p11, p10)) + "\n")
                stream.write(triangle(None, (p00, p01, p11)) + "\n")
                count += 2
        stream.write(f"endsolid {args.name}\n")
    print(f"Wrote {count} triangles to {args.output}")


if __name__ == "__main__":
    main()
