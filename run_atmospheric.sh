#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CASE_DIR=${CASE_DIR:-"$ROOT_DIR/work/atmospheric"}

usage() {
    cat <<'EOF'
Usage: ./run_atmospheric.sh

Prepare the atmospheric case if constant/polyMesh is missing, then run
checkMesh and foamRun -solver fluid. Time directories above 0 are removed
first so a second run starts from 0/.

  --help             show this help
EOF
}

if [[ ${1:-} == -h || ${1:-} == --help ]]; then
    usage
    exit 0
fi
if (($#)); then
    echo "Unknown argument: $1" >&2
    usage >&2
    exit 2
fi

# shellcheck disable=SC1091
source "$ROOT_DIR/env.sh"

if [[ ! -d $CASE_DIR/constant/polyMesh ]]; then
    "$ROOT_DIR/prepare_atmospheric.sh" --case "$CASE_DIR"
fi

cd "$CASE_DIR"
if [[ -f system/controlDict ]]; then
    while IFS= read -r time_name; do
        if [[ $time_name != 0 && -d $time_name ]]; then
            rm -rf -- "$time_name"
        fi
    done < <(foamListTimes -withZero -case "$CASE_DIR" || true)
fi
rm -rf postProcessing VTK

echo "[1/2] Checking mesh"
checkMesh -case "$CASE_DIR" | tee "$CASE_DIR/log.checkMesh"
echo "[2/2] Solving with foamRun -solver fluid"
foamRun -solver fluid -case "$CASE_DIR" | tee "$CASE_DIR/log.foamRun"

grep -q 'Mesh OK' "$CASE_DIR/log.checkMesh"
grep -q '^End$' "$CASE_DIR/log.foamRun"
printf '\nSuccess: %s\n' "$CASE_DIR"
