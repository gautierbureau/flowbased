#!/usr/bin/env bash
# (Re)download the OpenRAO example resources from powsybl/pypowsybl (tag v1.15.0).
set -euo pipefail
TAG="v1.15.0"
BASE="https://raw.githubusercontent.com/powsybl/pypowsybl/${TAG}/data/rao"
DEST="$(cd "$(dirname "$0")/.." && pwd)/data/rao"
mkdir -p "$DEST"
for f in rao_network.uct rao_crac.json rao_parameters.json rao_glsk.xml; do
  curl -fsSL "$BASE/$f" -o "$DEST/$f"
  echo "fetched $f"
done
echo "Done -> $DEST"
