#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=${CASE_DIR:-"$ROOT_DIR/work/cavity"}
OUTPUT=${OUTPUT:-"$CASE_DIR/cavity_result.png"}

# shellcheck disable=SC1091
source "$ROOT_DIR/env.sh"
if [[ ! -d $CASE_DIR/constant/polyMesh ]]; then
    echo "No solved cavity case at $CASE_DIR; run ./run_cavity.sh first." >&2
    exit 1
fi
if ! "$ROOT_DIR/.venv/bin/python" -c 'import matplotlib, numpy' 2>/dev/null; then
    cat >&2 <<'EOF'
Python plotting environment is missing. Run:
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements-post.txt
EOF
    exit 1
fi

foamToVTK -ascii -case "$CASE_DIR" -latestTime | tee "$CASE_DIR/log.foamToVTK"
vtk_file=$(find "$CASE_DIR/VTK" -maxdepth 1 -type f -name '*.vtk' -printf '%T@ %p\n' \
    | sort -n | tail -1 | cut -d' ' -f2-)
[[ -n $vtk_file ]] || { echo "foamToVTK produced no internal VTK file" >&2; exit 1; }
"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/tools/plot_cavity.py" \
    "$vtk_file" --output "$OUTPUT"
echo "Open the figure: $OUTPUT"
