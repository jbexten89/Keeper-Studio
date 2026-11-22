# One-time setup for Keeper Studio on Windows.
#
# Do not run this directly -- double-click Setup.bat instead, which launches it
# with the execution policy bypassed. Windows blocks .ps1 files by default.
#
# Safe to re-run: it reuses an existing .venv.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Record everything to a log. The window closes as soon as a key is pressed at
# the end, so without this there is no way to see what happened afterwards.
$LogPath = Join-Path $PSScriptRoot "setup-log.txt"
try { Start-Transcript -Path $LogPath -Force | Out-Null } catch { }

$Reqs = "requirements.txt"

trap {
    Write-Host ""
    Write-Host "=======================================" -ForegroundColor Red
    Write-Host " SETUP FAILED" -ForegroundColor Red
    Write-Host "=======================================" -ForegroundColor Red
    Write-Host ""
    Write-Host ($_ | Out-String)
    Write-Host "Full details saved to setup-log.txt in this folder."
    Write-Host "Send that file over and it can be diagnosed."
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

# Windows keeps its venv interpreter somewhere different from everywhere else.
$OnWindows = -not (Test-Path variable:IsWindows) -or $IsWindows
$VenvPy = if ($OnWindows) { ".venv\Scripts\python.exe" } else { ".venv/bin/python" }

function Test-Interpreter {
    <# Returns the version string if this command is a usable Python, else $null.

    Asking the interpreter to print its own version does double duty: it
    filters out versions outside the supported range, and it weeds out the
    Microsoft Store's "python.exe" placeholder, which exists when Python is not
    installed and only opens the Store rather than running anything. Matching
    on the executable path instead would wrongly reject a genuine Store
    install, which also lives under WindowsApps.
    #>
    param([string]$Exe, [string[]]$Prefix)
    try {
        $probe = 'import sys; sys.stdout.write(".".join(map(str, sys.version_info[:3])) if (3,9) <= sys.version_info < (3,13) else "")'
        $version = & $Exe @Prefix -c $probe 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        if ($version -match '^\d+\.\d+\.\d+$') { return $version }
        return $null
    } catch {
        return $null
    }
}

Write-Host "Looking for a compatible Python..." -ForegroundColor Cyan

$candidates = @()
if ($OnWindows) {
    foreach ($v in "3.12", "3.11", "3.10", "3.9") { $candidates += , @("py", @("-$v")) }
    $candidates += , @("python", @())
} else {
    foreach ($n in "python3.12", "python3.11", "python3.10", "python3.9", "python3") {
        $candidates += , @($n, @())
    }
}

$PyExe = $null
$PyArgs = @()
foreach ($candidate in $candidates) {
    if (-not (Get-Command $candidate[0] -ErrorAction SilentlyContinue)) { continue }
    $version = Test-Interpreter -Exe $candidate[0] -Prefix $candidate[1]
    if ($version) {
        $PyExe = $candidate[0]
        $PyArgs = $candidate[1]
        Write-Host "Found Python $version" -ForegroundColor Green
        break
    }
}

if (-not $PyExe) {
    Write-Host ""
    Write-Host "ERROR: no Python between 3.9 and 3.12 was found." -ForegroundColor Red
    Write-Host ""
    Write-Host "mediapipe, which does the face detection, publishes no installer for"
    Write-Host "Python 3.13 or newer. Installing against one fails with a confusing"
    Write-Host "'no matching distribution' error."
    Write-Host ""
    Write-Host "Install Python 3.12 from:"
    Write-Host "  https://www.python.org/downloads/windows/" -ForegroundColor Yellow
    Write-Host "Choose the latest 3.12.x release, download 'Windows installer (64-bit)',"
    Write-Host "and TICK 'Add python.exe to PATH' on the first screen of the installer."
    Write-Host "Then double-click Setup.bat again."
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

if (Test-Path ".venv") {
    Write-Host "Reusing existing .venv"
} else {
    Write-Host "Creating .venv..."
    & $PyExe @PyArgs -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "could not create the virtual environment" }
}

& $VenvPy -m pip install --upgrade pip --quiet
Write-Host "Installing dependencies from $Reqs." -ForegroundColor Cyan
Write-Host "This takes a few minutes the first time. Leave the window open."
& $VenvPy -m pip install -r $Reqs --quiet
if ($LASTEXITCODE -ne 0) { throw "dependency installation failed" }

# The cut-out model is 220 MB. If PhotoCropper's extractor already has it next
# door, reuse that copy instead of downloading it again on first use.
$RembgDir = Join-Path "models" "rembg"
$Mine = Join-Path $RembgDir "birefnet-general-lite.onnx"
$Theirs = Join-Path $PSScriptRoot "..\Photo Cropper\models\rembg\birefnet-general-lite.onnx"
if (-not (Test-Path $Mine) -and (Test-Path $Theirs)) {
    Write-Host "Copying the cut-out model from PhotoCropper (220 MB)..."
    New-Item -ItemType Directory -Force -Path $RembgDir | Out-Null
    Copy-Item $Theirs $Mine
}

# Load the detector once now, so a broken install fails here rather than
# partway through a job.
& $VenvPy -c @"
import sys
from pathlib import Path
sys.path.insert(0, '.')
from photocropper.config import load
from photocropper import detectors
cfg = load(Path('config.yaml'))
detectors.build(cfg.detector['name'], cfg.detector).close()
print('Detector loads OK. Sizes: ' + ', '.join(r.name for r in cfg.ratios))
import webview
print('App window component OK.')
"@
if ($LASTEXITCODE -ne 0) { throw "the detector failed to load" }

Write-Host ""
Write-Host "=======================================" -ForegroundColor Green
Write-Host " SETUP SUCCEEDED" -ForegroundColor Green
Write-Host "=======================================" -ForegroundColor Green
Write-Host ""
Write-Host " Next: double-click Keeper Studio.bat"
Write-Host ""
try { Stop-Transcript | Out-Null } catch { }
