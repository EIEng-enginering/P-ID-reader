<#
.SYNOPSIS
  Registers (or removes) the Windows scheduled task "PID Reader Training Resume".

.DESCRIPTION
  At each logon (after a 2-minute delay) the task runs `pid_reader.cli trainer autoresume`, which restarts the symbol-detector
  training ONLY if a run was cut off while it was meant to be going (restart, crash, logoff). It never starts a new run, and it leaves
  alone a run you paused, stopped, or that finished. Runs as you, with no elevation, only while you are logged on, with no window.
  The runner itself still honours the battery, memory, disk and daily-hours limits.

  Remove it with:  powershell -File Install-ResumeTask.ps1 -Remove
#>
param(
    [switch]$Remove,
    [string]$Python = "C:\PIDWork\venv312\Scripts\python.exe",
    [int]$DelayMinutes = 2
)
$ErrorActionPreference = "Stop"
$name = "PID Reader Training Resume"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        "Removed the scheduled task '$name'."
    } else {
        "No scheduled task '$name' is registered."
    }
    return
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$pythonw = Join-Path (Split-Path $Python) "pythonw.exe"
if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found next to $Python" }
$code = "import sys; sys.path.insert(0, r'$root\src'); from pid_reader.cli import main; sys.exit(main(['trainer','autoresume']))"

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-c `"$code`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$trigger.Delay = "PT$($DelayMinutes)M"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "Resumes the P&ID Reader symbol-detector training after a restart, only if it was cut off. Never starts a new run." -Force | Out-Null
"Registered '$name' (at logon + $DelayMinutes min, runs as $env:USERNAME)."
