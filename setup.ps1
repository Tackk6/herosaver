# setup.ps1 — one-shot environment setup for HeroSaver on Windows (PowerShell).
#
# Mirrors setup.sh. Creates a Python 3.10 venv, installs PyTorch (GPU or CPU),
# the project requirements, and the ADTOF-pytorch transcription model.
#
# Usage (from the repo root in PowerShell):
#   .\setup.ps1                 # auto-detect GPU, install accordingly
#   .\setup.ps1 -Cpu            # force CPU-only PyTorch
#   .\setup.ps1 -Cuda 121       # force a specific CUDA wheel (e.g. 118, 121, 124)
#   .\setup.ps1 -PythonBin "C:\path\to\python3.10.exe"   # explicit interpreter
#
# If PowerShell blocks the script, allow it for this session first:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

param(
    [switch]$Cpu,
    [string]$Cuda = "",
    [string]$PythonBin = "python"
)

$ErrorActionPreference = "Stop"
$VenvDir = "venv"
$AdtofRepo = "https://github.com/xavriley/ADTOF-pytorch.git"
$AdtofDir = "ADTOF-pytorch"

Write-Host "==> HeroSaver setup (Windows)"

# ---- check python ----------------------------------------------------------
try {
    $pyVer = & $PythonBin -c "import sys; print('%d.%d' % sys.version_info[:2])"
} catch {
    Write-Host "ERROR: '$PythonBin' not found." -ForegroundColor Red
    Write-Host "Install Python 3.10 from python.org and either add it to PATH or"
    Write-Host "pass it explicitly:  .\setup.ps1 -PythonBin 'C:\path\to\python.exe'"
    exit 1
}
Write-Host "    Using $PythonBin (Python $pyVer)"
if ($pyVer -ne "3.10") {
    Write-Host "    WARNING: 3.10 is recommended; $pyVer may hit dependency issues with ADTOF." -ForegroundColor Yellow
}

# ---- check ffmpeg ----------------------------------------------------------
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "    WARNING: ffmpeg not found on PATH. Demucs needs it for audio I/O." -ForegroundColor Yellow
    Write-Host "             Install it (e.g. 'winget install Gyan.FFmpeg') before charting."
}

# ---- create venv -----------------------------------------------------------
if (Test-Path $VenvDir) {
    Write-Host "==> Reusing existing venv at .\$VenvDir"
} else {
    Write-Host "==> Creating venv at .\$VenvDir"
    & $PythonBin -m venv $VenvDir
}
$VenvPython = Join-Path (Resolve-Path $VenvDir) "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip wheel | Out-Null

# ---- detect GPU ------------------------------------------------------------
if (-not $Cpu -and $Cuda -eq "") {
    if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
        $Cuda = "121"
        Write-Host "==> NVIDIA GPU detected; installing CUDA $Cuda PyTorch wheel"
    } else {
        $Cpu = $true
        Write-Host "==> No NVIDIA GPU detected; installing CPU PyTorch"
    }
}

# ---- install torch ---------------------------------------------------------
if ($Cpu) {
    & $VenvPython -m pip install torch
} else {
    & $VenvPython -m pip install torch --index-url "https://download.pytorch.org/whl/cu$Cuda"
}

# ---- install project requirements ------------------------------------------
Write-Host "==> Installing project requirements"
& $VenvPython -m pip install -r requirements.txt

# ---- install ADTOF ---------------------------------------------------------
if (Test-Path $AdtofDir) {
    Write-Host "==> ADTOF already cloned at .\$AdtofDir (skipping clone)"
} else {
    Write-Host "==> Cloning ADTOF-pytorch"
    git clone $AdtofRepo $AdtofDir
}
Write-Host "==> Installing ADTOF-pytorch (editable)"
& $VenvPython -m pip install -e ".\$AdtofDir"

# ---- verify ----------------------------------------------------------------
Write-Host "==> Verifying install"
& $VenvPython -c @"
import importlib, sys
ok = True
for mod in ('torch', 'demucs', 'librosa', 'mido'):
    try:
        importlib.import_module(mod); print(f'    [ok] {mod}')
    except Exception as e:
        ok = False; print(f'    [FAIL] {mod}: {e}')
try:
    import torch; print(f'    [info] CUDA available: {torch.cuda.is_available()}')
except Exception:
    pass
sys.exit(0 if ok else 1)
"@

Write-Host ""
Write-Host "==> Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Activate the environment whenever you use the tool:"
Write-Host "    .\$VenvDir\Scripts\Activate.ps1"
Write-Host ""
Write-Host "Then chart a song:"
Write-Host "    python src\chart_song.py path\to\song.mp3 ``"
Write-Host "        --title `"Song Name`" --artist `"Artist Name`" ``"
Write-Host "        --adtof-python `"$VenvPython`" --pro"
