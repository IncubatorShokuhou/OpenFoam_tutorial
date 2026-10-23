#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "$ROOT_DIR/env.sh"
CASE_DIR=${CASE_DIR:-"$ROOT_DIR/work/cavity"}

rm_case_contents() {
    if [[ -d $CASE_DIR ]]; then
        find "$CASE_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    fi
}

mkdir -p "$CASE_DIR"
rm_case_contents
cp -a "$FOAM_TUTORIALS/incompressibleFluid/cavity/." "$CASE_DIR/"
cd "$CASE_DIR"

echo "[1/3] Generating mesh"
blockMesh | tee log.blockMesh
echo "[2/3] Checking mesh"
checkMesh | tee log.checkMesh
echo "[3/3] Solving"
foamRun | tee log.foamRun

grep -q 'Mesh OK' log.checkMesh
grep -q '^End$' log.foamRun
printf '\nSuccess: %s\n' "$CASE_DIR"
printf 'View it with: paraFoam -case %q\n' "$CASE_DIR"
