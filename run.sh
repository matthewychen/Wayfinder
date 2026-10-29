#!/usr/bin/env sh
# Wayfinder - local launcher for Git Bash / macOS / Linux.  Usage: ./run.sh [port]
cd "$(dirname "$0")" || exit 1
PORT="${1:-8501}"
if [ -x ".venv/Scripts/python.exe" ]; then PY=".venv/Scripts/python.exe"; else PY=".venv/bin/python"; fi
if [ -e ".venv" ] && ! "$PY" -c "import sys" >/dev/null 2>&1; then
    echo "The .venv folder does not work on this computer; rebuilding it ..."
    rm -rf .venv
fi
if [ ! -x "$PY" ] || [ ! -e ".venv" ]; then
    echo "Creating the virtual environment ..."
    python3 -m venv .venv || python -m venv .venv || exit 1
    if [ -x ".venv/Scripts/python.exe" ]; then PY=".venv/Scripts/python.exe"; else PY=".venv/bin/python"; fi
fi
echo "Checking requirements ..."
"$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt || { echo "Installing requirements failed. It needs Python 3.10 or newer and an internet connection."; exit 1; }
echo "Starting the planner on http://localhost:$PORT  (Ctrl+C to stop)"
exec "$PY" -m streamlit run app.py --server.port "$PORT" --server.headless false --browser.gatherUsageStats false
