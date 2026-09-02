#!/usr/bin/env bash
# Create the backend virtualenv and install dependencies.
#
#   ./setup.sh
#
# Handles the common Debian/Ubuntu case where python3 ships without the
# `venv`/`ensurepip` module (the `python3-venv` package is missing) and there is
# no system pip either. Rather than requiring sudo, we create the venv without
# pip and bootstrap pip into it using PyPA's official installer. Everything
# stays inside backend/.venv — no system packages are touched.

set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR="${VENV_DIR:-.venv}"
PYTHON="${PYTHON:-python3}"
GET_PIP_URL="https://bootstrap.pypa.io/get-pip.py"

echo "==> Using $($PYTHON --version) at $(command -v "$PYTHON")"

if [ -d "$VENV_DIR" ]; then
  echo "==> $VENV_DIR already exists; reusing it (delete it to start clean)"
else
  # The standard path. Fails on systems without python3-venv/ensurepip, which is
  # why the fallback below exists.
  # venv prints its ensurepip failure to stdout, not stderr, so silence both.
  if $PYTHON -m venv "$VENV_DIR" >/dev/null 2>&1 && [ -x "$VENV_DIR/bin/python" ]; then
    echo "==> Created $VENV_DIR"
  else
    echo "==> venv with pip unavailable (no ensurepip); bootstrapping pip manually"
    rm -rf "$VENV_DIR"
    $PYTHON -m venv --without-pip "$VENV_DIR"
    echo "==> Created $VENV_DIR without pip"
  fi
fi

VENV_PY="$VENV_DIR/bin/python"

if ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
  echo "==> Installing pip into $VENV_DIR"
  TMP_GET_PIP="$(mktemp -t get-pip-XXXXXX.py)"
  trap 'rm -f "$TMP_GET_PIP"' EXIT
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$GET_PIP_URL" -o "$TMP_GET_PIP"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$TMP_GET_PIP" "$GET_PIP_URL"
  else
    echo "ERROR: need curl or wget to bootstrap pip." >&2
    echo "       Alternatively: sudo apt install python3-venv python3-pip" >&2
    exit 1
  fi
  "$VENV_PY" "$TMP_GET_PIP" --quiet
fi

echo "==> pip $("$VENV_PY" -m pip --version | awk '{print $2}')"
echo "==> Installing dependencies"
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -r requirements.txt

"$VENV_PY" - <<'PY'
import fastapi, sklearn, httpx, openai, pandas, numpy, joblib  # noqa: F401
print("==> All imports OK")
PY

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> Wrote .env from .env.example (no LLM key needed; it runs without one)"
fi

cat <<'EOF'

Setup complete. Next:

  .venv/bin/python -m app.crawl.run --pages 60 --details 500   # ~10 min
  .venv/bin/python -m app.ingest
  .venv/bin/python -m app.pricing --train
  .venv/bin/python -m app.enrich
  .venv/bin/uvicorn app.main:app --reload

EOF
