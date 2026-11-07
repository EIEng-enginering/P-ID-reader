<#
 Per-user, offline installer for P&ID Reader. No administrator rights, no network.
   Install-PIDReader.ps1 [-Payload PIDReader-app.zip] [-InstallDir <dir>] [-Uninstall]
 Installs to %LOCALAPPDATA%\Programs\PIDReader, adds Start-menu shortcut and an
 "Apps & features" uninstall entry under HKCU. Project data lives separately in
 %LOCALAPPDATA%\PIDReader\projects and is NEVER deleted by uninstall.
#>
param([string]$Payload = (Join-Path $PSScriptRoot 'PIDReader-app.zip'),
      [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\PIDReader'),
      [switch]$Uninstall, [switch]$Quiet)
$ErrorActionPreference = 'Stop'
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\PIDReader'
$menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\P&ID Reader.lnk'
function Say($m) { if (-not $Quiet) { Write-Host $m } }
if ($Uninstall) {
    if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
    if (Test-Path $menu) { Remove-Item -Force $menu }
    if (Test-Path $key) { Remove-Item -Recurse -Force $key }
    Say 'P&ID Reader removed. Your project databases were left in place.'
    return
}
if (-not (Test-Path $Payload)) { throw "Payload not found: $Payload" }
$tmp = Join-Path $env:TEMP ('pidreader-' + [guid]::NewGuid().ToString('N'))
Say "Unpacking to $InstallDir ..."
Expand-Archive -LiteralPath $Payload -DestinationPath $tmp
$src = Join-Path $tmp 'PIDReader'
if (-not (Test-Path (Join-Path $src 'PIDReader.exe'))) { Remove-Item -Recurse -Force $tmp; throw 'Payload is not a P&ID Reader build.' }
if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
New-Item -ItemType Directory -Force (Split-Path $InstallDir) | Out-Null
Move-Item $src $InstallDir
Remove-Item -Recurse -Force $tmp
Copy-Item $PSCommandPath (Join-Path $InstallDir 'Uninstall-PIDReader.ps1') -Force
$sh = New-Object -ComObject WScript.Shell
$lnk = $sh.CreateShortcut($menu)
$lnk.TargetPath = Join-Path $InstallDir 'PIDReader.exe'
$lnk.WorkingDirectory = $InstallDir
$lnk.Description = 'P&ID Reader - reads drawings and proposes interpretations for review'
$lnk.Save()
New-Item -Path $key -Force | Out-Null
$ver = (Get-Content (Join-Path $InstallDir 'VERSION.txt') -ErrorAction SilentlyContinue | Select-Object -First 1)
Set-ItemProperty $key DisplayName 'P&ID Reader'
Set-ItemProperty $key DisplayVersion ($ver)
Set-ItemProperty $key Publisher 'Enhance Integration Engineering (development build)'
Set-ItemProperty $key InstallLocation $InstallDir
Set-ItemProperty $key UninstallString ("powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"" + (Join-Path $InstallDir 'Uninstall-PIDReader.ps1') + "`" -Uninstall")
Set-ItemProperty $key NoModify 1
Set-ItemProperty $key NoRepair 1
Say "Installed. Start-menu entry: P&ID Reader.  CLI: $InstallDir\pid-reader-cli.exe"
