#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p data input
if [ "${1:-}" = "--gpu" ]; then
  docker compose -f compose.yaml -f compose.gpu.yaml up -d --build
else
  docker compose -f compose.yaml up -d --build
fi
printf '%s\n' 'Kairos Studio: http://localhost:8000'
