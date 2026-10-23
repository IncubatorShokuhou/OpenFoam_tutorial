#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: OPENTOPOGRAPHY_API_KEY=... ./download_dem.sh SOUTH NORTH WEST EAST [OUTPUT]

Download a clipped Copernicus GLO-30 GeoTIFF from the OpenTopography API.
Coordinates are decimal degrees in WGS84. OUTPUT defaults to work/terrain/dem_wgs84.tif.
Request a free API key at https://opentopography.org/developers

Example (a small area near Beijing):
  OPENTOPOGRAPHY_API_KEY=... ./download_dem.sh 39.85 39.95 116.30 116.45
EOF
}

if [[ ${1:-} == -h || ${1:-} == --help ]]; then usage; exit 0; fi
if (($# < 4 || $# > 5)); then usage >&2; exit 2; fi
: "${OPENTOPOGRAPHY_API_KEY:?Set OPENTOPOGRAPHY_API_KEY (see --help)}"
for command_name in curl python3; do
    command -v "$command_name" >/dev/null || { echo "Missing command: $command_name" >&2; exit 1; }
done

south=$1; north=$2; west=$3; east=$4
output=${5:-work/terrain/dem_wgs84.tif}
python3 - "$south" "$north" "$west" "$east" <<'PY'
import sys
south, north, west, east = map(float, sys.argv[1:])
if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
    raise SystemExit("Invalid WGS84 bounding box")
PY
mkdir -p "$(dirname "$output")"
curl -fL --retry 3 --get 'https://portal.opentopography.org/API/globaldem' \
    --data-urlencode demtype=COP30 \
    --data-urlencode "south=$south" \
    --data-urlencode "north=$north" \
    --data-urlencode "west=$west" \
    --data-urlencode "east=$east" \
    --data-urlencode outputFormat=GTiff \
    --data-urlencode "API_Key=$OPENTOPOGRAPHY_API_KEY" \
    --output "$output"
echo "Downloaded: $output"
echo "This raster is geographic; reproject it to metres before dem_to_stl.py."
