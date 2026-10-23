#!/usr/bin/env bash
# Source this file; do not execute it: source ./env.sh
_tutorial_root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [[ ! -f $_tutorial_root/local/OpenFOAM-14/etc/bashrc ]]; then
    echo "OpenFOAM is not installed. Run ./install_openfoam.sh first." >&2
    unset _tutorial_root
    return 1 2>/dev/null || exit 1
fi
# shellcheck disable=SC1091
_tutorial_had_nounset=false
[[ $- == *u* ]] && _tutorial_had_nounset=true
set +u
source "$_tutorial_root/local/OpenFOAM-14/etc/bashrc"
[[ $_tutorial_had_nounset == false ]] || set -u
export OPENFOAM_TUTORIAL_ROOT="$_tutorial_root"
unset _tutorial_root _tutorial_had_nounset
