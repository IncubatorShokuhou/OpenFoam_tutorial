#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=${CASE_DIR:-"$ROOT_DIR/work/atmospheric"}
OUTPUT_DIR=${OUTPUT_DIR:-"$ROOT_DIR/tutorial/images"}

usage() {
    cat <<'EOF'
Usage: ./plot_atmospheric.sh

Export the latest atmospheric time with foamToVTK -ascii and write the
lesson figures (terrain, mesh, wind, temperature, humidity, profiles).

  --help             show this help
EOF
}

if [[ ${1:-} == -h || ${1:-} == --help ]]; then
    usage
    exit 0
fi

# shellcheck disable=SC1091
source "$ROOT_DIR/env.sh"
if [[ ! -d $CASE_DIR/constant/polyMesh ]]; then
    echo "No atmospheric case at $CASE_DIR; run ./run_atmospheric.sh first." >&2
    exit 1
fi
python3 - <<'PY'
import importlib.util
import sys
missing = [name for name in ("numpy", "matplotlib", "rasterio") if importlib.util.find_spec(name) is None]
if missing:
    sys.stderr.write("Missing Python module(s): " + ", ".join(missing) + "\n")
    sys.exit(1)
PY

foamToVTK -ascii -case "$CASE_DIR" -latestTime | tee "$CASE_DIR/log.foamToVTK"
vtk_file=$(find "$CASE_DIR/VTK" -maxdepth 1 -type f -name '*.vtk' -printf '%T@ %p\n' \
    | sort -n | tail -1 | cut -d' ' -f2-)
[[ -n $vtk_file ]] || { echo "foamToVTK produced no internal VTK file" >&2; exit 1; }
python3 "$ROOT_DIR/tools/plot_atmospheric.py" \
    --case "$CASE_DIR" \
    --vtk "$vtk_file" \
    --profiles "$ROOT_DIR/tutorial/data/beijing_boundary.csv" \
    --output-dir "$OUTPUT_DIR"
echo "Figures are in $OUTPUT_DIR"
