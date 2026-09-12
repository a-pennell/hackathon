#!/usr/bin/env bash
# Generate Synthea FHIR R4 bundles into data/synthea/fhir/.
#
# Usage: scripts/gen_synthea.sh [population] [seed] [age-range]
#   defaults: 100 patients, seed 4242, ages 45-85
#
# Re-running with a different seed ADDS bundles to the same folder (does not
# clear it). Don't regenerate after the golden patient is picked — everyone's
# demos depend on the same data (see CLAUDE.md).
set -euo pipefail

POP="${1:-100}"
SEED="${2:-4242}"
AGES="${3:-45-85}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
JAR="$ROOT/tools/synthea/synthea-with-dependencies.jar"
JAVA="${JAVA:-/opt/homebrew/opt/openjdk@21/bin/java}"
OUT="$ROOT/data/synthea"

if [[ ! -x "$JAVA" ]]; then
  echo "Java not found at $JAVA (set JAVA=... to override)" >&2
  exit 1
fi
if [[ ! -f "$JAR" ]]; then
  echo "Synthea jar not found at $JAR" >&2
  echo "Download: https://github.com/synthetichealth/synthea/releases/download/master-branch-latest/synthea-with-dependencies.jar" >&2
  exit 1
fi

mkdir -p "$OUT"
echo "Generating $POP patients (seed $SEED, ages $AGES) into $OUT/fhir ..."
"$JAVA" -jar "$JAR" \
  -p "$POP" -s "$SEED" -a "$AGES" \
  --exporter.baseDirectory="$OUT" \
  --exporter.fhir.export=true \
  --exporter.hospital.fhir.export=false \
  --exporter.practitioner.fhir.export=false \
  --exporter.csv.export=false \
  "${@:4}"

echo "Bundles now in $OUT/fhir: $(ls "$OUT/fhir"/*.json | wc -l | tr -d ' ')"
