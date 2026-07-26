<#
.SYNOPSIS
    Build the DeckForge desktop application for Windows.

.DESCRIPTION
    Exports the frontend, freezes the backend with PyInstaller and (optionally)
    produces an installer with Inno Setup.

.EXAMPLE
    ./packaging/build.ps1                 # build the app folder
    ./packaging/build.ps1 -Installer      # ... and the .exe installer
    ./packaging/build.ps1 -SkipFrontend   # reuse the existing frontend/out
#>
[CmdletBinding()]
param(
    [switch]$Installer,
    [switch]$SkipFrontend,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$Python = Join-Path $Backend ".venv\Scripts\python.exe"

function Step($message) { Write-Host "`n=== $message ===" -ForegroundColor Cyan }

if (-not (Test-Path $Python)) {
    throw "No virtual environment at $Python. Create one: uv venv --python 3.14 backend/.venv"
}

# --- 1. Python dependencies -------------------------------------------------
if (-not $SkipInstall) {
    Step "Installing backend, desktop and build dependencies"
    # Braces are required: "$Backend[...]" would parse as an index expression.
    $target = "${Backend}[desktop,build]"
    # A `uv venv` has no pip in it, and that is the setup DEVELOPMENT.md documents,
    # so install through uv when it is the tool that made the environment.
    # Asked this way rather than `pip --version`: a missing module writes to
    # stderr, and with $ErrorActionPreference = "Stop" that alone aborts the build.
    $hasPip = & $Python -c "import importlib.util,sys; sys.stdout.write('1' if importlib.util.find_spec('pip') else '0')"
    if ($hasPip -eq "1") {
        & $Python -m pip install --disable-pip-version-check -q -e $target
    } elseif (Get-Command uv -ErrorAction SilentlyContinue) {
        & uv pip install --python $Python -q -e $target
    } else {
        throw "Neither pip nor uv is available for $Python. Install uv, or run with -SkipInstall."
    }
    if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }
}

# --- 2. Frontend static export ---------------------------------------------
if (-not $SkipFrontend) {
    Step "Building the frontend"
    Push-Location (Join-Path $Root "frontend")
    try {
        if (-not (Test-Path "node_modules")) { npm ci --no-audit --no-fund }
        $env:NEXT_TELEMETRY_DISABLED = "1"
        # Empty: the app is served by its own backend, so the API is same-origin.
        $env:NEXT_PUBLIC_API_URL = ""
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
    } finally { Pop-Location }
}

if (-not (Test-Path (Join-Path $Root "frontend\out\index.html"))) {
    throw "frontend/out/index.html is missing - the export did not run"
}

# --- 3. Icon ----------------------------------------------------------------
Step "Generating the icon"
& $Python (Join-Path $PSScriptRoot "make_icon.py")

# --- 4. Freeze --------------------------------------------------------------
Step "Freezing with PyInstaller"
Push-Location $Root
try {
    & $Python -m PyInstaller (Join-Path $PSScriptRoot "deckforge.spec") `
        --noconfirm --clean `
        --distpath (Join-Path $Root "dist") `
        --workpath (Join-Path $Root "build")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
} finally { Pop-Location }

$AppDir = Join-Path $Root "dist\DeckForge"
$Exe = Join-Path $AppDir "DeckForge.exe"
if (-not (Test-Path $Exe)) { throw "expected $Exe to exist" }

$size = [math]::Round(((Get-ChildItem $AppDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host "`nApplication: $AppDir ($size MB)" -ForegroundColor Green

# --- 5. Installer -----------------------------------------------------------
if ($Installer) {
    Step "Building the installer"
    $iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if (-not $iscc) {
        # winget installs per user by default, which is not on PATH.
        $candidates = @(
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
        )
        $found = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $found) {
            throw "Inno Setup 6 not found. Install it (winget install JRSoftware.InnoSetup) or drop -Installer."
        }
        $iscc = $found
    }
    & $iscc (Join-Path $PSScriptRoot "windows\installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
    Get-ChildItem (Join-Path $Root "dist\installer") -Filter *.exe |
        ForEach-Object { Write-Host "Installer: $($_.FullName) ($([math]::Round($_.Length/1MB,1)) MB)" -ForegroundColor Green }
}

Write-Host "`nDone." -ForegroundColor Green
