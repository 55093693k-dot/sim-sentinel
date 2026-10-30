<#
  register_tasks.ps1 -- create (or update) the 1-minute scheduled task.

  Three settings are NOT optional. Drop any one of them and the task will
  "look like it is running" while doing nothing:
    -AllowStartIfOnBatteries / -DontStopIfGoingOnBatteries
        on a laptop it silently stops triggering once unplugged
    -MultipleInstances IgnoreNew
        one wedged instance makes every later trigger be dropped silently
    -ExecutionTimeLimit <finite>
        the default limit is 72 hours, i.e. a wedged instance never frees itself

  Usage
    powershell -ExecutionPolicy Bypass -File register_tasks.ps1
    powershell -ExecutionPolicy Bypass -File register_tasks.ps1 -Preview
    powershell -ExecutionPolicy Bypass -File register_tasks.ps1 -Remove

  Diagnostics for "it stopped working"
    Get-ScheduledTaskInfo -TaskName 'Sim_Sentinel_1min'
      LastTaskResult 267009 (0x00041301) + State Running  = an instance is wedged
      LastRunTime keeps updating even then -- so it is NOT evidence of progress
#>
param(
    [switch]$Preview,
    [switch]$Remove,
    [string]$TaskName = 'Sim_Sentinel_1min'
)

$ErrorActionPreference = 'Stop'
$Kit    = Split-Path -Parent $PSScriptRoot
$Launch = Join-Path $PSScriptRoot 'sentinel_run.cmd'

if (-not (Test-Path $Launch)) { throw "launcher not found: $Launch" }

if ($Remove) {
    if ($Preview) { "would unregister: $TaskName"; exit 0 }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    "removed: $TaskName"
    exit 0
}

$Action = New-ScheduledTaskAction -Execute 'cmd.exe' `
            -Argument ('/c ""' + $Launch + '""') `
            -WorkingDirectory $Kit

$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(2) `
             -RepetitionInterval (New-TimeSpan -Minutes 1) `
             -RepetitionDuration (New-TimeSpan -Days 3650)

$Setting = New-ScheduledTaskSettingsSet `
             -AllowStartIfOnBatteries `
             -DontStopIfGoingOnBatteries `
             -MultipleInstances IgnoreNew `
             -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

if ($Preview) {
    "task     : $TaskName"
    "action   : cmd.exe /c ""$Launch""   (workdir $Kit)"
    "trigger  : once at $((Get-Date).Date.AddMinutes(2).ToString('HH:mm')), repeat every 1 min, no end date"
    "settings : batteries=allowed  instances=IgnoreNew  time_limit=5 min  run_as=current user"
    "note     : nothing was registered (-Preview)"
    exit 0
}

Register-ScheduledTask -TaskName $TaskName -Action $Action `
    -Trigger $Trigger -Settings $Setting -Force | Out-Null

Get-ScheduledTaskInfo -TaskName $TaskName |
    Select-Object TaskName, LastRunTime, LastTaskResult, NextRunTime | Format-List
