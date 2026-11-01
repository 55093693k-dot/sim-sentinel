# sim-sentinel

A background simulation can keep writing its log without showing you any progress. **sim-sentinel**
reads that local log once a minute and sends a Windows notification when a run finishes, fails, or
stops moving. It reports state changes; it does not notify you every minute.

Windows 10/11, Python 3.8+, standard library only. No third-party packages, database, or resident
service. The included rules target Lumerical FDTD/EME `*_p0.log` files and can be adapted to other
local text logs.

![license](https://img.shields.io/badge/license-MIT-blue)
![python](https://img.shields.io/badge/python-3.8%2B-blue)
![platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-lightgrey)
[![tests](https://github.com/55093693k-dot/sim-sentinel/actions/workflows/tests.yml/badge.svg)](https://github.com/55093693k-dot/sim-sentinel/actions/workflows/tests.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23817306.svg)](https://doi.org/10.5281/zenodo.23817306)

![Example notification](docs/toast-example.png)

*A demonstration notification. Progress may remain below 100% when the solver's own stopping condition
is met: this example ends at 99.3998% while the closing summary line marks completion. Windows
notification settings control whether the banner is visible.*

## Quick start

Run these commands from the extracted repository folder. The examples watch
`D:\SimWorkbench\sim`; replace that path with your simulation folder.

### 1. Download

Choose **Code → Download ZIP** and extract to a fixed location. Do not move the folder after
registering the scheduled task.

### 2. Point the tool at your logs

```powershell
Copy-Item .\sentinel\config.example.json .\sentinel\config.json
```

Edit `sentinel\config.json`:

```json
{
  "root": "D:\\SimWorkbench",
  "watch_subdir": "sim",
  "log_glob": "**/*_p0.log"
}
```

This searches `D:\SimWorkbench\sim` and its subfolders for files ending in `_p0.log`. If the logs are
directly under `root`, set `watch_subdir` to `""`. Keep the other settings at their defaults initially.

### 3. Python path (usually automatic)

`launch\sentinel_run.cmd` first tries the Windows `py -3` launcher, then `python` on `PATH`. On most
machines no edit is needed. If both are missing, the launcher writes `ERROR python not found` to
`logs\sentinel_stdout.txt` and exits with code 9009.

To force a specific interpreter, open `launch\sentinel_run.cmd` and replace:

```bat
set "PY="
```

with its full path:

```bat
set "PY=C:\Python311\python.exe"
```

Do not append a comment to that line.

### 4. Check before scheduling

```powershell
python .\sentinel\sentinel.py --once --no-toast
powershell -NoProfile -ExecutionPolicy Bypass -File .\_selftest_kit.ps1
python .\sentinel\sentinel.py --test
```

The first command checks without showing notifications. `logs_watched=0` means the folder or filename
pattern does not match. The first sighting of a log establishes a silent baseline, preventing a burst
of notifications for old runs.

The self-test uses temporary files, does not touch real simulations, and must end with
`RESULT: ALL PASS`. The last command tests the Windows notification separately.

A successful test adds one line to `logs\toast.log`:

```text
OK  2026-11-01 12:00:00  aumid=<id>  setting=Enabled  banner=allow  sound=wav  Sentinel self-test
```

`aumid=` identifies the sender that accepted the call. `setting=Enabled` means Windows reports the
app's notification channel as enabled; any other value means that sender is blocked. `banner=allow`
means Windows has `ShowBanner=1` for that sender; `unset` or `deny` means the call can still succeed
while no banner appears. If no installed sender is allowed, set `toast_aumid` in `config.json` to an
AUMID whose notification settings allow banners. The value is written to the log, so the sender is
never a guess.

### 5. Schedule one check per minute

Preview, then register:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\launch\register_tasks.ps1 -Preview
powershell -NoProfile -ExecutionPolicy Bypass -File .\launch\register_tasks.ps1
```

The task is named `Sim_Sentinel_1min`. Changes to `config.json` take effect on the next check; do not
register again. Remove the task with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\launch\register_tasks.ps1 -Remove
```

## What it reports

| Status | Evidence |
|---|---|
| `FINISHED` | A configured completion line appears in the log |
| `FAILED` | A configured error line appears and no engine process is found |
| `STALLED` | The log stops growing for the configured number of checks and no engine process is found |

The notification titles are `Simulation finished: <file>`, `Simulation failed: <file>`, and
`Simulation stalled: <file>`. The body carries the observed elapsed time, the last percentage when
one exists, and the log path relative to `root`.

Each check starts Python, reads recent logs, saves their state, and exits. Normally only the last
6 KB of each log is read. Nothing stays resident between checks.

This is not a continuously updating progress bar. Detailed percentages remain in the original log.
A recorded percentage can stay below 100% even for a completed run; `FINISHED` is taken from the
solver's closing summary line, not from the percentage.

## Notification sound

By default the tool plays `%SystemRoot%\Media\Windows Notify System Generic.wav` and falls back to a
console beep. To use your own sound, put a standard WAV file at a fixed path and set
`toast_sound` in `config.json`:

```json
{
  "toast_sound": "C:\\Sounds\\sim-done.wav"
}
```

`%USERPROFILE%` and `~` are expanded. Leave the value empty to keep the system sound. The toast XML
is deliberately silent; `toast.ps1` plays the file itself, so the custom sound does not depend on
the sender application's notification audio policy.

Read the last line of `<root>\logs\toast.log` to see what happened:

| `sound=` | Meaning |
|---|---|
| `custom` | the configured WAV played |
| `wav` | the system WAV played |
| `custom-missing+default` | the custom path was wrong; the system WAV played instead |
| `custom-fail+default` | the custom file existed but could not be played; the system WAV played instead |
| `beep` or `...+beep` | no WAV could be played; the console beep was used |

A missing or unsupported custom file is not fatal: the tool falls back to the system WAV, then to a
beep. MP3 and other formats are not decoded by `System.Media.SoundPlayer`; use WAV.

Sound can still be lost when the system is muted, the output device is unavailable, the volume is
too low, or the scheduled task did not run. Those are separate from banner visibility: the banner
can be suppressed by Windows while the sound still plays, or the reverse.

## Resource use

- No resident process or third-party service.
- State and event records are small text files; results and complete logs are not copied.
- On one test machine (2026-10-31), a check took about 1.7–4.6 seconds and peaked at 15 MB with
  python.org Python 3.14 or 48 MB with Miniconda Python. These are local measurements, not a
  performance guarantee for other machines.

## Files and troubleshooting

Under the configured `root`, `logs\state.json` remembers what was seen, `logs\events.jsonl`
records verdicts, and `logs\toast.log` records notification attempts. Create an empty
`<root>\sentinel.pause` file to pause checks; delete it to resume.

| Symptom | What to check |
|---|---|
| `logs_watched=0` | `root`, `watch_subdir`, and `log_glob` in `config.json` |
| The task says it ran but nothing happens | Look for fresh `start` lines in the repository's `logs\sentinel_stdout.txt`; the task panel alone is not enough |
| `Last Result 267009` with `State: Running` | A previous instance is still running; end it and trigger the task once manually |
| The notification log succeeds but no banner appears | Read `logs\toast.log`: `banner=allow` points to Focus assist or the global switch; `unset`/`deny` means the sender itself is not allowed. Set `toast_aumid`, or enable banners for that sender in Windows notification settings |

## Adapt it to another solver

Change `log_glob`, `done_patterns`, and `error_patterns` in `config.json` using real log excerpts.
Avoid matching a bare word such as `error`: normal prose can contain it. `Auto Shutoff` is not a
completion marker in the Lumerical logs for which the defaults were written.

The process check recognizes executable names ending in `-engine.exe`. Completion and error rules
can be adapted in the configuration, but a solver with a different process name also requires a
code change for `FAILED` and `STALLED` detection.

See which rules match a log without changing state or sending a notification:

```powershell
python .\sentinel\sentinel.py --explain D:\SimWorkbench\sim\runA\project_p0.log
```

## Limitations

- **Windows and local text logs only.** Cloud jobs, including Tidy3D cloud runs, are not covered.
- **First sightings are silent.** If a run finishes between checks and its log is immediately moved
  or deleted, that event can be missed.
- **Stalled detection is delayed.** The default requires repeated unchanged checks. An unknown
  process state is never treated as proof of failure.
- **Sleep stops checks.** Events whose logs disappear while the computer is asleep cannot be recovered.
- **A notification is not proof that anyone saw it.** Windows can suppress the banner, and it
  controls which registered sender identity is used. `logs\toast.log` records the attempted sender
  and whether that sender is allowed to show banners; set `toast_aumid` to choose one explicitly.
- **Completion is not correctness.** The tool does not judge convergence, energy balance, physics,
  or the validity of simulation results.

## Uninstall and cleanup

Remove the scheduled task first:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\launch\register_tasks.ps1 -Remove
```

If the launcher is already gone, remove the task directly:

```powershell
Unregister-ScheduledTask -TaskName 'Sim_Sentinel_1min' -Confirm:$false
```

Then remove only the files the tool created:

- The extracted repository folder (code, `config.json`, and repository `logs\sentinel_stdout.txt`).
- `<root>\logs\state.json`, `events.jsonl`, `toast.log`, and `_toast_msg.txt`.
- `<root>\sentinel.pause`, if present.
- Any custom sound path or `toast_aumid` entry in the removed `config.json`.

**Do not delete `*_p0.log`, `.fsp`, result files, or the simulation folders.** The tool only records
its own state; removing its `logs\` directory does not remove simulation output.

## Safety and security

`sim-sentinel` is a local log reader. It does not edit simulation files, start or kill a solver,
change Windows settings, or shut down the computer. It runs with the current user's permissions and
does not use the network, a model, telemetry, a service, or a driver.

It still creates state and notification records under `logs/`; treat those files as private. Windows,
Python, the solver, and the hardware can fail independently, so no software can guarantee that a
machine will never crash. The tool is not a substitute for solver validation or backups. See
[SECURITY.md](SECURITY.md) for the precise scope and reporting guidance.

## Citation and discussions

Cite the concept DOI, which resolves to the latest archived version:

**[10.5281/zenodo.23817306](https://doi.org/10.5281/zenodo.23817306)**

Questions and suggestions: **[Discussions](https://github.com/55093693k-dot/sim-sentinel/discussions)**.

## Licence

Copyright (c) 2026 Chan Kingho.

Source code, tests, and automation scripts are MIT; written documentation and the screenshot are
CC BY 4.0. See `LICENSE` and `LICENSE-docs.md`.
