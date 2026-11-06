#!/bin/bash
# Double-click in Finder to install dependencies and start the dashboard.
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
set -e

# Stop anything still running from a previous launch on our ports.
for port in 8000 5173; do
  pids=$(lsof -ti tcp:$port 2>/dev/null || true)
  if [ -n "$pids" ]; then echo "Freeing port $port"; kill $pids 2>/dev/null || true; sleep 1; fi
done

echo "== Backend setup"
cd backend
if [ ! -d .venv ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 .venv
  else
    PY=""
    for c in python3.13 python3.12 python3.11 python3.10 python3; do
      if command -v $c >/dev/null 2>&1 && $c -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then PY=$c; break; fi
    done
    if [ -z "$PY" ]; then echo "Python 3.10+ is required. Install it with: brew install python@3.12"; read -n1; exit 1; fi
    $PY -m venv .venv
  fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python -q -r requirements.txt
else
  .venv/bin/python -m pip install -q -r requirements.txt
fi
.venv/bin/python -m uvicorn app.main:app --port 8000 &
API_PID=$!
cd ..

echo "== Frontend setup"
cd frontend
if ! command -v npm >/dev/null 2>&1; then echo "Node.js is required. Install it with: brew install node"; kill $API_PID; read -n1; exit 1; fi
[ -d node_modules ] || npm install
npx vite --port 5173 &
WEB_PID=$!
cd ..

trap "kill $API_PID $WEB_PID 2>/dev/null" EXIT
echo "Waiting for servers..."
for i in $(seq 1 60); do curl -s localhost:8000/api/health >/dev/null && curl -s localhost:5173 >/dev/null && break; sleep 1; done
open http://localhost:5173
echo ""
echo "Dashboard: http://localhost:5173   API docs: http://localhost:8000/docs"
echo "Close this window to stop both servers."
wait
