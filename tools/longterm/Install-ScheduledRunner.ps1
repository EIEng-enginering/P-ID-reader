param([Parameter(Mandatory=$true)][string]$ConfigPath,[Parameter(Mandatory=$true)][string]$ModelPython)
$ErrorActionPreference='Stop'
$ScriptPath=Join-Path $PSScriptRoot 'launch.py'
$ConfigPath=(Resolve-Path $ConfigPath).Path
$ModelPython=(Resolve-Path $ModelPython).Path
$TaskArguments='"'+$ScriptPath+'" once --config "'+$ConfigPath+'"'
$Action=New-ScheduledTaskAction -Execute $ModelPython -Argument $TaskArguments -WorkingDirectory (Split-Path (Split-Path $PSScriptRoot))
$Trigger=New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(5)) -RepetitionInterval (New-TimeSpan -Hours 1)
$Settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 58)
Register-ScheduledTask -TaskName 'PIDReaderLongTerm' -Action $Action -Trigger $Trigger -Settings $Settings -Description 'One bounded offline P&ID experiment/training slice; candidate models only.' -Force
Write-Output 'Scheduled one queue check per hour. The programme still requires a valid config and queued jobs.'
