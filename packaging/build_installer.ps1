<# Build the offline installer. Output: C:\PIDWork\build\release\
   1. PyInstaller onedir app  2. PIDReader-app.zip payload  3. PIDReader-Setup.zip (payload + scripts)
   4. PIDReader-Setup.exe via Windows IExpress (self-extracting; no admin)
#>
param([string]$Python = 'C:\PIDWork\venv312\Scripts\python.exe', [string]$Work = 'C:\PIDWork\build')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ver = (& $Python -c "import sys; sys.path.insert(0, r'$root\src'); import pid_reader; print(pid_reader.__version__)")
& $Python -m PyInstaller "$root\packaging\pid_reader.spec" --distpath "$Work\dist" --workpath "$Work\work" --noconfirm
Set-Content "$Work\dist\PIDReader\VERSION.txt" $ver
$rel = "$Work\release"; New-Item -ItemType Directory -Force $rel | Out-Null
$payload = "$rel\PIDReader-app.zip"; if (Test-Path $payload) { Remove-Item $payload }
Compress-Archive -Path "$Work\dist\PIDReader" -DestinationPath $payload -CompressionLevel Optimal
Copy-Item "$root\packaging\Install-PIDReader.ps1","$root\packaging\Setup.cmd" $rel -Force
$pkg = "$rel\PIDReader-Setup-$ver.zip"; if (Test-Path $pkg) { Remove-Item $pkg }
Compress-Archive -Path $payload,"$rel\Install-PIDReader.ps1","$rel\Setup.cmd" -DestinationPath $pkg -CompressionLevel NoCompression
$sed = "$rel\setup.sed"; $exe = "$rel\PIDReader-Setup-$ver.exe"
if (Test-Path $exe) { Remove-Item $exe }
@"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles
[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=$exe
FriendlyName=PID Reader Setup
AppLaunched=cmd /c Setup.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
FILE0="Setup.cmd"
FILE1="Install-PIDReader.ps1"
FILE2="PIDReader-app.zip"
[SourceFiles]
SourceFiles0=$rel\
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
"@ | Set-Content -Encoding ASCII $sed
& "$env:WINDIR\System32\iexpress.exe" /N /Q $sed
$t = Get-Date; while (-not (Test-Path $exe) -and ((Get-Date) - $t).TotalMinutes -lt 15) { Start-Sleep 3 }
Get-FileHash $exe, $pkg, $payload -Algorithm SHA256 | ForEach-Object { "$($_.Hash)  $(Split-Path $_.Path -Leaf)" } | Set-Content "$rel\SHA256SUMS.txt"
Write-Host "Release folder: $rel"; Get-ChildItem $rel | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
