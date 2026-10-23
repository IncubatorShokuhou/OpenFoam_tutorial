#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

usage() {
    cat <<'EOF'
Usage: ./prepare_atmospheric.sh [options passed to tools/atmospheric_case.py]

Write work/atmospheric from the committed Beijing tables and a projected DEM.
With no --dem, gdalwarp clips the public Copernicus GLO-30 COG over Jingshan
into work/terrain/. That window sits inside the download_dem.sh Beijing box.
Pass --sample-hill only for the synthetic unit-test terrain.
A user DEM must already be in a projected CRS with units of metres.

  --help             show this help, then the Python help
EOF
}

if [[ ${1:-} == -h || ${1:-} == --help ]]; then
    usage
    exec python3 "$ROOT_DIR/tools/atmospheric_case.py" --help
fi

if ! python3 -c 'import numpy, rasterio' 2>/dev/null; then
    echo "numpy and rasterio are required. Install requirements-terrain.txt." >&2
    exit 1
fi

python3 "$ROOT_DIR/tools/atmospheric_case.py" "$@"
