#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

API_HOST="${API_HOST:-}"
if [[ -z "${API_HOST}" ]]; then
  echo "ERROR: Set API_HOST to the running Rhyolite API (e.g. http://rhyolite-api:8000)." >&2
  exit 2
fi

export API_HOST

echo "Waiting for API to be reachable at: $API_HOST"
python - <<'PY'
import os
import sys
import time

import httpx

api_host = os.environ["API_HOST"].rstrip("/")
if not (api_host.startswith("http://") or api_host.startswith("https://")):
    api_host = "http://" + api_host

deadline = time.time() + 60
last_err = None
while time.time() < deadline:
    try:
        with httpx.Client(base_url=api_host, timeout=2.0) as c:
            r = c.get("/kinds")
            if r.status_code < 500:
                print("API is reachable.")
                sys.exit(0)
    except Exception as e:
        last_err = e
    time.sleep(1)

print(f"ERROR: API not reachable at {api_host} after 60s. Last error: {last_err}", file=sys.stderr)
sys.exit(2)
PY

echo "Running pytest..."
set +e
pytest testing.py -vvv
PYTEST_EXIT=$?
set -e

if [[ $PYTEST_EXIT -eq 0 ]]; then
  echo "pytest OK"
else
  echo "pytest FAILED (exit $PYTEST_EXIT)" >&2
fi

exit $PYTEST_EXIT
