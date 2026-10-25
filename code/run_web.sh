#!/usr/bin/env bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ -f "$DIR/.venv/bin/python" ]; then
  PYTHON="$DIR/.venv/bin/python"
elif [ -f "/home/toshibaba/lifelocker/.venv/bin/python" ]; then
  PYTHON="/home/toshibaba/lifelocker/.venv/bin/python"
else
  PYTHON="python3"
fi

PORT="${1:-5000}"
echo "=========================================================="
echo " 🌐 Starting Inbox To-Do Scanner on http://localhost:$PORT"
echo "=========================================================="
exec "$PYTHON" "$DIR/app.py" "$PORT"
