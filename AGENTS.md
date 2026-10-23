# Repository Guidelines

This repository contains a reproducible, beginner-oriented OpenFOAM Foundation tutorial.

- Keep generated source trees, builds, cases, logs, and large terrain data under ignored directories (`local/`, `work/`, `logs/`, or `downloads/`).
- Keep `README.md` as the short entry point and numbered Chinese lessons under `tutorial/`.
- Shell scripts use `set -euo pipefail`, quote expansions, accept `--help`, and avoid machine-specific paths.
- Python tools use only documented dependencies and must not silently guess a geographic coordinate system.
- Pin upstream versions and URLs. Update the version, checksum/tag, docs, and tests together.
- Validate shell syntax with `bash -n *.sh`; validate Python with `python3 -m unittest discover -s tests`.
- Never commit OpenFOAM source, compiler output, DEM rasters, STL meshes, ParaView states, or simulation time directories.
