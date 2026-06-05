#!/usr/bin/env bash
#
# setup.sh — one-shot environment setup for Clone Hero Auto-Charter.
#
# Creates a Python 3.10 virtualenv, installs PyTorch (GPU or CPU), the project
# requirements, and the ADTOF-pytorch transcription model.
#
# Usage:
#   ./setup.sh              # auto-detect GPU, install accordingly
#   ./setup.sh --cpu        # force CPU-only PyTorch
#   ./setup.sh --cuda 121   # force a specific CUDA wheel (e.g. 118, 121, 124)
#
set -euo pipefail

# ---- config ----------------------------------------------------------------
PYTHON_BIN="${PYTHON_BIN:-python3.10}"   # override: PYTHON_BIN=python3.11 ./setup.sh
VENV_DIR="venv"
ADTOF_REPO="https://github.com/xavriley/ADTOF-pytorch.git"
ADTOF_DIR="ADTOF-pytorch"
CUDA_VERSION=""        # empty = auto-detect
FORCE_CPU=0

# ---- parse args ------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cpu)   FORCE_CPU=1; shift ;;
    --cuda)  CUDA_VERSION="$2"; shift 2 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

echo "==> Clone Hero Auto-Charter setup"

# ---- check python ----------------------------------------------------------
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: '$PYTHON_BIN' not found." >&2
  echo "Install Python 3.10 (recommended for the ADTOF/ML stack), or set" >&2
  echo "PYTHON_BIN to an available interpreter, e.g.:  PYTHON_BIN=python3.11 ./setup.sh" >&2
  exit 1
fi
PY_VER="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
echo "    Using $PYTHON_BIN (Python $PY_VER)"
if [[ "$PY_VER" != "3.10" ]]; then
  echo "    WARNING: 3.10 is recommended; $PY_VER may hit dependency issues with ADTOF."
fi

# ---- check ffmpeg ----------------------------------------------------------
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "    WARNING: ffmpeg not found on PATH. Demucs needs it for audio I/O."
  echo "             Install it (e.g. 'sudo apt install ffmpeg') before charting."
fi

# ---- create venv -----------------------------------------------------------
if [[ -d "$VENV_DIR" ]]; then
  echo "==> Reusing existing venv at ./$VENV_DIR"
else
  echo "==> Creating venv at ./$VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip wheel >/dev/null

# ---- detect GPU ------------------------------------------------------------
if [[ "$FORCE_CPU" -eq 0 && -z "$CUDA_VERSION" ]]; then
  if command -v nvidia-smi >/dev/null 2>&1; then
    CUDA_VERSION="121"   # safe default for modern drivers
    echo "==> NVIDIA GPU detected; installing CUDA $CUDA_VERSION PyTorch wheel"
  else
    FORCE_CPU=1
    echo "==> No NVIDIA GPU detected; installing CPU PyTorch"
  fi
fi

# ---- install torch ---------------------------------------------------------
if [[ "$FORCE_CPU" -eq 1 ]]; then
  pip install torch
else
  pip install torch --index-url "https://download.pytorch.org/whl/cu${CUDA_VERSION}"
fi

# ---- install project requirements ------------------------------------------
echo "==> Installing project requirements"
pip install -r requirements.txt

# ---- install ADTOF ---------------------------------------------------------
if [[ -d "$ADTOF_DIR" ]]; then
  echo "==> ADTOF already cloned at ./$ADTOF_DIR (skipping clone)"
else
  echo "==> Cloning ADTOF-pytorch"
  git clone "$ADTOF_REPO" "$ADTOF_DIR"
fi
echo "==> Installing ADTOF-pytorch (editable)"
pip install -e "./$ADTOF_DIR"

# ---- verify ----------------------------------------------------------------
echo "==> Verifying install"
python - <<'PYCHECK'
import importlib, sys
ok = True
for mod in ("torch", "demucs", "librosa", "mido"):
    try:
        importlib.import_module(mod)
        print(f"    [ok] {mod}")
    except Exception as e:
        ok = False
        print(f"    [FAIL] {mod}: {e}")
try:
    import torch
    print(f"    [info] CUDA available: {torch.cuda.is_available()}")
except Exception:
    pass
sys.exit(0 if ok else 1)
PYCHECK

ADTOF_PY="$(pwd)/$VENV_DIR/bin/python"
cat <<DONE

==> Setup complete.

Activate the environment whenever you use the tool:
    source $VENV_DIR/bin/activate

Then chart a song:
    python src/chart_song.py path/to/song.mp3 \\
        --title "Song Name" --artist "Artist Name" \\
        --adtof-python "$ADTOF_PY" --pro

DONE
