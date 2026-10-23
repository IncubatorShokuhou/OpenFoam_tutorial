#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck disable=SC1091
source "$ROOT_DIR/env.sh"
CASE_DIR=${CASE_DIR:-"$ROOT_DIR/work/cavity_parallel"}
NP=${NP:-4}
case "$NP" in ''|*[!0-9]*) echo "NP must be a positive integer" >&2; exit 2 ;; esac
((NP > 0)) || { echo "NP must be greater than zero" >&2; exit 2; }

mkdir -p "$CASE_DIR"
find "$CASE_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
cp -a "$FOAM_TUTORIALS/incompressibleFluid/cavity/." "$CASE_DIR/"
cd "$CASE_DIR"
blockMesh | tee log.blockMesh
foamDictionary system/decomposeParDict -entry numberOfSubdomains -set "$NP"
decomposePar -force | tee log.decomposePar
mpirun -np "$NP" foamRun -parallel | tee log.foamRun.parallel
reconstructPar | tee log.reconstructPar
grep -q '^End$' log.foamRun.parallel
echo "Parallel run succeeded with $NP ranks: $CASE_DIR"
