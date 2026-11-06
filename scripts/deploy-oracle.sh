#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose build
docker compose up -d
docker compose --profile bot up -d telegram
docker compose ps
