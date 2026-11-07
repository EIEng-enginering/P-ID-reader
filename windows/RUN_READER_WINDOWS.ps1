# Local preview only. Does not install packages or contact a server.
param([string]$ProjectDatabase = '')
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $ProjectDatabase) {
    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA unavailable; supply -ProjectDatabase.' }
    $Folder = Join-Path $env:LOCALAPPDATA 'PIDReader\Projects'
    New-Item -ItemType Directory -Force -Path $Folder | Out-Null
    $ProjectDatabase = Join-Path $Folder 'development_preview.sqlite'
}
Push-Location $Root
try {
    $env:PYTHONPATH = (Join-Path $Root 'src')
    & py -3.12 -c "import PySide6,pypdfium2"
    if ($LASTEXITCODE -ne 0) { throw 'PySide6 6.12.0 and pypdfium2 must be installed before GUI use.' }
    if (-not (Test-Path $ProjectDatabase)) {
        & py -3.12 -m pid_reader.cli init-project $ProjectDatabase
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the local project database.' }
    }
    & py -3.12 -m pid_reader.cli gui $ProjectDatabase
    if ($LASTEXITCODE -ne 0) { throw 'GUI exited with an error.' }
} finally {
    Pop-Location
}
