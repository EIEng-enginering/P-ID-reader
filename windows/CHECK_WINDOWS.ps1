# Offline Windows preflight. Does NOT install packages or contact the network.
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $Root
try {
    $env:PYTHONPATH = (Join-Path $Root 'src')
    Write-Host 'Checking Python 3.12 and project imports...'
    & py -3.12 -c "import sys,pid_reader;print(sys.version);print(pid_reader.__file__)"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 not installed or project cannot be imported.' }
    & py -3.12 tools/release_preflight.py
    if ($LASTEXITCODE -ne 0) { throw 'Release preflight failed.' }
    Write-Host 'Running unit/regression tests...'
    & py -3.12 -m pytest -q tests
    if ($LASTEXITCODE -ne 0) { throw 'Unit tests failed.' }
    Write-Host 'Checking optional GUI dependencies...'
    & py -3.12 -c "import PySide6,pypdfium2;print('PySide6 installed:',PySide6.__version__)"
    if ($LASTEXITCODE -ne 0) { Write-Warning 'GUI dependencies unavailable; no GUI acceptance claim can be made.' }
    Write-Host 'Windows GUI, DPI, installer and host integration require manual test evidence.'
} finally {
    Pop-Location
}
