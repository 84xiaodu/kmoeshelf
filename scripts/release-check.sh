#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

scripts/check-sensitive-files.sh
git diff --check
.venv/bin/python -m pytest -q -s
npm --prefix frontend run build
npm --prefix frontend test
KMOE_APP_SECRET_KEY="${KMOE_APP_SECRET_KEY:-local-release-validation-key-000000000000}" docker compose config >/dev/null

if [[ "${KMOE_SKIP_DOCKER_BUILD:-false}" != "true" ]]; then
  docker build -t kmoe-subscriptions:release-check .
fi
