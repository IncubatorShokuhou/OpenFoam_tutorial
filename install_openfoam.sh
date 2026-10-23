#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
VERSION=14
PATCH_TAG=20261008
JOBS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)
PREFIX="$ROOT_DIR/local"
DOWNLOAD_DIR="$ROOT_DIR/downloads"
RUN_TEST=false

usage() {
    cat <<'EOF'
Usage: ./install_openfoam.sh [options]

Download and compile OpenFOAM Foundation v14 with bundled Scotch/Zoltan.
The script uses the system GCC and OpenMPI and is safe to rerun.

  --prefix DIR       source/build installation parent (default: ./local)
  --download-dir DIR archive cache (default: ./downloads)
  -j, --jobs N       parallel compile jobs (default: logical CPU count)
  --run-test         run the cavity smoke test after compilation
  -h, --help         show this help

Ubuntu prerequisites:
  sudo apt update
  sudo apt install build-essential flex bison git curl ca-certificates \
      openmpi-bin libopenmpi-dev zlib1g-dev libreadline-dev
EOF
}

while (($#)); do
    case "$1" in
        --prefix) PREFIX=$2; shift 2 ;;
        --download-dir) DOWNLOAD_DIR=$2; shift 2 ;;
        -j|--jobs) JOBS=$2; shift 2 ;;
        --run-test) RUN_TEST=true; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done
case "$JOBS" in ''|*[!0-9]*) echo "--jobs must be a positive integer" >&2; exit 2 ;; esac
((JOBS > 0)) || { echo "--jobs must be greater than zero" >&2; exit 2; }

for command_name in gcc g++ make flex bison curl tar mpicc mpicxx mpirun; do
    command -v "$command_name" >/dev/null || {
        echo "Missing prerequisite: $command_name (see --help)" >&2
        exit 1
    }
done

mkdir -p "$PREFIX" "$DOWNLOAD_DIR" "$ROOT_DIR/logs"
foam_dir="$PREFIX/OpenFOAM-$VERSION"
third_party_dir="$PREFIX/ThirdParty-$VERSION"
foam_archive="$DOWNLOAD_DIR/OpenFOAM-$VERSION-$PATCH_TAG.tar.gz"
third_party_archive="$DOWNLOAD_DIR/ThirdParty-$VERSION-version-$VERSION.tar.gz"

download() {
    local url=$1 destination=$2
    if [[ ! -s $destination ]]; then
        echo "Downloading $url"
        curl -fL --retry 3 --continue-at - -o "$destination" "$url"
    fi
    tar -tzf "$destination" >/dev/null || {
        echo "Invalid/incomplete archive: $destination; delete it and rerun." >&2
        exit 1
    }
}

download "https://github.com/OpenFOAM/OpenFOAM-$VERSION/archive/refs/tags/$PATCH_TAG.tar.gz" "$foam_archive"
download "https://github.com/OpenFOAM/ThirdParty-$VERSION/archive/refs/tags/version-$VERSION.tar.gz" "$third_party_archive"

if [[ ! -f $foam_dir/etc/bashrc ]]; then
    tmp_name="OpenFOAM-$VERSION.extracting.$$"
    tar -xzf "$foam_archive" -C "$PREFIX" \
        --transform="s/^OpenFOAM-$VERSION-$PATCH_TAG/$tmp_name/"
    mv "$PREFIX/$tmp_name" "$foam_dir"
fi
if [[ ! -f $third_party_dir/Allwmake ]]; then
    tmp_name="ThirdParty-$VERSION.extracting.$$"
    tar -xzf "$third_party_archive" -C "$PREFIX" \
        --transform="s/^ThirdParty-$VERSION-version-$VERSION/$tmp_name/"
    mv "$PREFIX/$tmp_name" "$third_party_dir"
fi

# shellcheck disable=SC1090
source "$foam_dir/etc/bashrc"
echo "Building ThirdParty libraries with $JOBS jobs..."
(cd "$third_party_dir" && ./Allwmake -j "$JOBS") 2>&1 | tee "$ROOT_DIR/logs/thirdparty-build.log"
echo "Building OpenFOAM with $JOBS jobs..."
(cd "$foam_dir" && ./Allwmake -j "$JOBS") 2>&1 | tee "$ROOT_DIR/logs/openfoam-build.log"

command -v foamRun >/dev/null
command -v blockMesh >/dev/null
echo "OpenFOAM $VERSION build succeeded."
echo "For each new terminal run: source \"$foam_dir/etc/bashrc\""

if [[ $RUN_TEST == true ]]; then
    "$ROOT_DIR/run_cavity.sh"
fi
