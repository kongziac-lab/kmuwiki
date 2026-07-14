#!/bin/sh
# Clean old Hermes artifacts accidentally created at the NAS share root.
# Dry-run by default. Pass --apply to remove the listed targets.

set -eu

ROOT="${HERMES_NAS_ROOT:-/volume1/jdh}"
APPLY=0

if [ "${1:-}" = "--apply" ]; then
  APPLY=1
elif [ "${1:-}" = "" ] || [ "${1:-}" = "--dry-run" ]; then
  APPLY=0
else
  echo "Usage: sh cleanup-hermes-root.sh [--dry-run|--apply]"
  exit 2
fi

case "$ROOT" in
  /volume1/*) ;;
  *)
    echo "Refusing to operate outside /volume1: $ROOT"
    exit 2
    ;;
esac

if [ ! -d "$ROOT" ]; then
  echo "Root does not exist: $ROOT"
  exit 2
fi

CR_NAME="$(printf 'hermes\r')"

echo "Root: $ROOT"
if [ "$APPLY" -eq 1 ]; then
  echo "Mode: apply"
else
  echo "Mode: dry-run"
fi
echo
echo "Targets:"

find "$ROOT" -maxdepth 1 \
  \( -type d \( -name 'hermes' -o -name "$CR_NAME" \) -o -type f -name 'hermes-*.log' \) \
  -print

if [ "$APPLY" -eq 0 ]; then
  echo
  echo "No files removed. Re-run with --apply to delete these targets."
  exit 0
fi

find "$ROOT" -maxdepth 1 \
  \( -type d \( -name 'hermes' -o -name "$CR_NAME" \) -o -type f -name 'hermes-*.log' \) \
  -exec rm -rf -- {} +

echo
echo "Cleanup complete."
