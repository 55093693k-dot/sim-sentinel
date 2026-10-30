# _selftest_kit.ps1 -- end-to-end check of sentinel\ in a throw-away sandbox.
# No toast is shown (--no-toast); nothing outside %TEMP% is touched.
#   powershell -ExecutionPolicy Bypass -File _selftest_kit.ps1
#   powershell -ExecutionPolicy Bypass -File _selftest_kit.ps1 -Keep   (keep the sandbox)
param([switch]$Keep)

$ErrorActionPreference = 'Stop'
$src = $PSScriptRoot
foreach ($d in 'sentinel', 'launch') {
    if (-not (Test-Path (Join-Path $src $d))) { throw "$d not found under $src" }
}

$t = Join-Path $env:TEMP ('sentinel_test_' + (Get-Random))
$k = Join-Path $t 'kit'
$r = Join-Path $t 'root'
New-Item -ItemType Directory -Force -Path $k | Out-Null
Copy-Item -Recurse (Join-Path $src 'sentinel') $k
Copy-Item -Recurse (Join-Path $src 'launch') $k
New-Item -ItemType Directory -Force -Path (Join-Path $r 'sim\runA'), (Join-Path $r 'logs') | Out-Null

$cfg = [ordered]@{ root = $r; watch_subdir = 'sim'; log_glob = '**/*_p0.log'
                   tail_bytes = 6000; mtime_window_s = 900; stall_after = 3 }
# the sandbox gets its own config, so the real workbench state is never touched
[IO.File]::WriteAllText((Join-Path $k 'sentinel\config.json'), ($cfg | ConvertTo-Json),
    (New-Object System.Text.UTF8Encoding($false)))

$py = (Get-Command python).Source
$sp = Join-Path $k 'sentinel\sentinel.py'
$ev = Join-Path $r 'logs\events.jsonl'

function Count-Events {
    if (-not (Test-Path $ev)) { return 0 }
    return (Select-String -Path $ev -Pattern '"kind": "(FINISHED|FAILED|STALLED)"').Count
}
function Run-Sentinel { param([string[]]$Extra = @())
    $a = @($sp, '--once', '--no-toast') + $Extra
    & $py @a | Out-Null
}

$fail = 0
function Check($name, $expect, $got) {
    $ok = ($expect -eq $got)
    if (-not $ok) { $script:fail++ }
    "{0}  {1,-52} expect={2} got={3}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $name, $expect, $got
}

$done = "99.3998% complete. Max time remaining: 3 hrs`r`ntotal FDTD solver speed on 10 processes (Mnodes/s): 214.504635`r`n"
$prog = "2.00031% complete. Elapsed simulation time: 1.2e-13 secs. Max time remaining: 41 hrs. Auto Shutoff: 0.101703`r`n"
$err  = "Error: there was an unknown parallel error. The error code is 10, the process number is 0`r`n"

$A = Join-Path $r 'sim\runA\projA_p0.log'
[IO.File]::WriteAllText($A, $done, (New-Object System.Text.UTF8Encoding($false)))
Run-Sentinel; Check 'finished log, FIRST sight -> silent baseline' 0 (Count-Events)
Run-Sentinel; Check 'same log again -> still silent (dedupe)' 0 (Count-Events)

$C = Join-Path $r 'sim\runA\projC_p0.log'
[IO.File]::WriteAllText($C, $prog, (New-Object System.Text.UTF8Encoding($false)))
Run-Sentinel; Check 'progress only -> no verdict' 0 (Count-Events)

[IO.File]::WriteAllText($C, $prog + $err, (New-Object System.Text.UTF8Encoding($false)))
Run-Sentinel; Check 'error appears in same log -> FAILED fires once' 1 (Count-Events)
Run-Sentinel; Check 'FAILED again -> deduped' 1 (Count-Events)

$D = Join-Path $r 'sim\runA\projD_p0.log'
[IO.File]::WriteAllText($D, $prog, (New-Object System.Text.UTF8Encoding($false)))
1..4 | ForEach-Object { Run-Sentinel }
Check 'unchanged size x3 polls -> STALLED (4th run)' 2 (Count-Events)

[IO.File]::WriteAllText((Join-Path $r 'sentinel.pause'), 'pause', (New-Object System.Text.UTF8Encoding($false)))
[IO.File]::WriteAllText($D, $prog + $err, (New-Object System.Text.UTF8Encoding($false)))
Run-Sentinel
Check 'pause marker -> polling skipped' 2 (Count-Events)
Remove-Item (Join-Path $r 'sentinel.pause')

""
"--- register_tasks.ps1 -Preview ---"
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $k 'launch\register_tasks.ps1') -Preview
""
"--- events.jsonl (verdict lines only) ---"
Select-String -Path $ev -Pattern '"kind": "(FINISHED|FAILED|STALLED)"' | ForEach-Object { $_.Line }
""
"sandbox = $t"
if ($Keep) {
    "kept (--Keep): inspect it, then delete it yourself"
} else {
    Remove-Item -Recurse -Force $t -ErrorAction SilentlyContinue
    "sandbox deleted (pass -Keep to inspect it)"
}
if ($fail -eq 0) { "RESULT: ALL PASS" } else { "RESULT: $fail FAILED" }
exit $fail
