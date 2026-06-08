# DataSure Installer — Windows (PowerShell)
# Usage:  .\install.ps1
#         .\install.ps1 -NoSetup    (skip wizard, just install)
param([switch]$NoSetup)

$ErrorActionPreference = "Stop"
$DatasureDir = "$env:USERPROFILE\.datasure"
$VenvDir     = "$DatasureDir\venv"
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "  DataSure — Analytics QA Platform — Installer" -ForegroundColor Cyan
Write-Host ""

# ── check Python ──────────────────────────────────────────────────────────────
Write-Host "→ Checking Python..." -ForegroundColor Yellow
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd -c "import sys; print(sys.version_info[:2])" 2>$null
        $ok  = & $cmd -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $python = $cmd; Write-Host "  Found: $cmd ($ver)"; break }
    } catch {}
}
if (-not $python) {
    Write-Host ""
    Write-Host "  ERROR: Python 3.10+ not found." -ForegroundColor Red
    Write-Host "  Download from: https://python.org/downloads"
    Write-Host "  Make sure to check 'Add Python to PATH' during install."
    exit 1
}

# ── create venv ───────────────────────────────────────────────────────────────
Write-Host "→ Creating virtual environment at $VenvDir ..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $DatasureDir | Out-Null
& $python -m venv $VenvDir

# ── install package ───────────────────────────────────────────────────────────
Write-Host "→ Installing DataSure..." -ForegroundColor Yellow
& "$VenvDir\Scripts\pip.exe" install --quiet --upgrade pip
& "$VenvDir\Scripts\pip.exe" install --quiet -e $ScriptDir

# ── create launcher batch file ────────────────────────────────────────────────
$LauncherDir = "$env:USERPROFILE\.local\bin"
New-Item -ItemType Directory -Force -Path $LauncherDir | Out-Null
$LauncherPath = "$LauncherDir\datasure.bat"
@"
@echo off
call "$VenvDir\Scripts\activate.bat"
datasure %*
"@ | Out-File -FilePath $LauncherPath -Encoding ASCII

Write-Host "  Created launcher: $LauncherPath" -ForegroundColor Green

# ── add to PATH ───────────────────────────────────────────────────────────────
$currentPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($currentPath -notlike "*$LauncherDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$currentPath;$LauncherDir", "User")
    $env:Path += ";$LauncherDir"
    Write-Host "  Added $LauncherDir to user PATH" -ForegroundColor Green
}

Write-Host ""
Write-Host "  DataSure installed successfully!" -ForegroundColor Green
Write-Host ""

# ── run setup wizard ──────────────────────────────────────────────────────────
if (-not $NoSetup) {
    Write-Host "→ Launching setup wizard..." -ForegroundColor Yellow
    Write-Host ""
    & "$VenvDir\Scripts\datasure.exe" setup
} else {
    Write-Host "  Skipped setup. Run 'datasure setup' to configure your Qlik connection."
    Write-Host ""
    Write-Host "  Quick start:"
    Write-Host "    datasure setup"
    Write-Host "    datasure list-apps"
    Write-Host "    datasure validate <APP_ID>"
}
