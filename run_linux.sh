#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "Primero crea el entorno e instala requirements.txt"
  exit 1
fi
exec .venv/bin/python launcher.py
