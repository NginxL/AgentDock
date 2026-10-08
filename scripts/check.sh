#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
agentdock_python="${AGENTDOCK_PYTHON:-.venv/bin/python}"
if [[ ! -x "$agentdock_python" ]]; then agentdock_python=python3; fi
"$agentdock_python" -m unittest discover -s tests -v
"$agentdock_python" -m compileall -q agentdock tests
cd web
npm test
npm run build
