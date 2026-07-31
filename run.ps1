<#
.SYNOPSIS
    Run Speech to Text in Focus straight from this checkout.

.DESCRIPTION
    Sets up .venv on the first run and starts the app. Everything lives inside the
    repo folder, so deleting it removes the app completely - nothing is installed
    system-wide.

    After a `git pull`, just run it again: the package is installed in editable
    mode, so new code is picked up with no reinstall. Only a change to
    pyproject.toml costs one, and the script notices on its own.

.PARAMETER Reinstall
    Reinstall the dependencies even if nothing changed. For when a venv is broken.

.EXAMPLE
    .\run.ps1
    Start the app. It appears in the system tray.

.EXAMPLE
    .\run.ps1 --list-devices
    Anything after the script name goes to the app: --selftest, --calibrate-mic and so on.
#>
[CmdletBinding()]
param(
    [switch]$Reinstall,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$AppArgs
)

$ErrorActionPreference = 'Stop'

$MinimumPython = [version]'3.11'

function Write-Step { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Note { param([string]$Message) Write-Host "    $Message" -ForegroundColor DarkGray }

function Get-PythonVersion {
    <#
        Ask the interpreter itself. Parsing `python --version` output is unreliable,
        and it is also how we find out whether a candidate runs at all: the Microsoft
        Store stub exits without printing anything.
    #>
    param([string]$Exe, [string[]]$Prefix = @())
    try {
        $output = & $Exe @Prefix '-c' 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $output) { return $null }
        return [version]($output | Select-Object -Last 1).Trim()
    } catch {
        return $null
    }
}

function Find-Python {
    <#
        Returns @(exe, prefix-args) for the first usable interpreter.

        The `py` launcher goes first: it knows about every real install and never
        resolves to the Store stub. Plain `python` from WindowsApps is skipped
        outright: that stub opens the Store instead of running anything.
    #>
    $candidates = @()
    if (Get-Command 'py' -ErrorAction SilentlyContinue) {
        $candidates += , @('py', @('-3'))
    }
    foreach ($name in @('python', 'python3')) {
        $found = Get-Command $name -ErrorAction SilentlyContinue
        if ($found -and $found.Source -notlike '*\WindowsApps\*') {
            $candidates += , @($found.Source, @())
        }
    }

    foreach ($candidate in $candidates) {
        $version = Get-PythonVersion -Exe $candidate[0] -Prefix $candidate[1]
        if ($version -and $version -ge $MinimumPython) {
            return $candidate
        }
    }
    return $null
}

# The app talks to Windows APIs directly for hotkeys, the microphone and the
# clipboard. Under WSL or PowerShell on Linux it would install fine and then do
# nothing, which is a worse way to find out.
if ($env:OS -ne 'Windows_NT') {
    throw 'This app runs on native Windows only (global hotkeys, microphone and clipboard). Run it from PowerShell on Windows, not from WSL.'
}

# Anchor everything to the repo, not to wherever the shell happens to be.
Push-Location $PSScriptRoot
try {
    $venv = Join-Path $PSScriptRoot '.venv'
    $venvPython = Join-Path $venv 'Scripts\python.exe'

    if (-not (Test-Path $venvPython)) {
        $python = Find-Python
        if (-not $python) {
            throw "Python $MinimumPython or newer is required, and none was found. Install it from https://www.python.org/downloads/windows/ (the python.org build, not the Microsoft Store one) and tick 'Add python.exe to PATH'."
        }
        Write-Step 'Creating the virtual environment (.venv)'
        & $python[0] @($python[1]) '-m' 'venv' $venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv.' }
    }

    # Reinstall only when the dependency list actually changed. Hashing pyproject.toml
    # is what makes `git pull; .\run.ps1` cheap on the common day, where nothing but
    # the source changed and editable mode has already picked it up.
    $stamp = Join-Path $venv '.stt-deps-hash'
    $fingerprint = (Get-FileHash (Join-Path $PSScriptRoot 'pyproject.toml') -Algorithm SHA256).Hash
    $installed = if (Test-Path $stamp) { (Get-Content $stamp -Raw).Trim() } else { '' }

    if ($Reinstall -or $installed -ne $fingerprint) {
        Write-Step 'Installing dependencies (a few minutes the first time)'
        & $venvPython '-m' 'pip' 'install' '--disable-pip-version-check' '-q' '-e' '.[windows]'
        if ($LASTEXITCODE -ne 0) { throw 'Installing the dependencies failed.' }
        Set-Content -Path $stamp -Value $fingerprint -Encoding ascii
    }

    if (-not (Test-Path (Join-Path $PSScriptRoot 'config.toml'))) {
        Write-Note 'No config.toml: running on factory settings. Copy config.example.toml to change that.'
    }

    Write-Step 'Starting Speech to Text in Focus - look for the microphone in the system tray'
    Write-Note 'On the very first run the speech model is downloaded (0.5-1.6 GB). Ctrl+C here quits.'

    & $venvPython '-m' 'stt' @AppArgs
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
