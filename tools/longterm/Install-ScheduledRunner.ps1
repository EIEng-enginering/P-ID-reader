param([Parameter(Mandatory=$true)][string]$ConfigPath,[Parameter(Mandatory=$true)][string]$ModelPython,[switch]$CheckOnly)
$ErrorActionPreference='Stop'
$TaskName='PIDReaderLongTerm'
$ScriptPath=Join-Path $PSScriptRoot 'launch.py'
$ConfigPath=(Resolve-Path $ConfigPath).Path
$ModelPython=(Resolve-Path $ModelPython).Path
# 1. Readiness gates: every gate must be PASS (NOT_RUN blocks like FAIL). Nothing is registered otherwise.
$ready=& $ModelPython $ScriptPath readiness --config $ConfigPath
if($LASTEXITCODE -ne 0){ Write-Output $ready; throw 'Readiness gates are not all PASS; the scheduled task was NOT registered.' }
# 2. Never interrupt a running measurement or job.
$busy=Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'longterm\.worker|eval_configs\.py|eval_bubbles\.py|build_candidates\.py|pytest' -and $_.ProcessId -ne $PID }
if($busy){ throw ('A measurement/job is running (PID '+(($busy|Select-Object -First 3).ProcessId -join ',')+'); try again when it has finished.') }
if($CheckOnly){ Write-Output 'Readiness PASS and no job running; nothing registered (-CheckOnly).'; return }
# 3. One task only: updating the existing task in place avoids duplicates.
$TaskArguments='"'+$ScriptPath+'" once --config "'+$ConfigPath+'"'
$Action=New-ScheduledTaskAction -Execute $ModelPython -Argument $TaskArguments -WorkingDirectory (Split-Path (Split-Path $PSScriptRoot))
$Trigger=New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(5)) -RepetitionInterval (New-TimeSpan -Hours 1)
$Settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 58)
$existing=Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if($existing){ Set-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings | Out-Null; Write-Output "Updated the existing task $TaskName (no duplicate created)." }
else { Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description 'One bounded offline P&ID experiment/training slice; candidate models only.' | Out-Null; Write-Output "Registered task $TaskName." }
Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo | Select-Object TaskName,NextRunTime | Format-List
