# Security and safety

`sim-sentinel` is a local, per-user Windows utility that reads simulation logs and sends a
notification. This page states what it accesses and what it deliberately does not do.

## What it accesses

- Reads files matching `log_glob` under the configured `root`.
- Reads the Windows process table to see whether a solver process is still alive.
- Writes state, event, and toast records under `<root>\logs\`.
- Writes `logs\sentinel_stdout.txt` under the repository folder when the launcher runs.
- Starts `powershell.exe` for one notification attempt; `toast.ps1` uses the Windows toast API and
  may play a WAV file.
- `register_tasks.ps1` creates or removes one per-user Task Scheduler entry.

No administrator rights are required. The tool does not open a network connection, call a model,
send telemetry, or install a service or driver.

## What it does not do

- It does not edit solver logs, project files, results, or simulation settings.
- It does not start, stop, suspend, or kill a solver process.
- It does not change Windows notification settings, power settings, or the registry.
- It does not shut down, restart, or sleep the computer.
- It does not delete simulation logs or results.

The only files it creates are its own state and records under `logs/`, plus a temporary message file
used to pass notification text to PowerShell.

## Safety statement

The code is a log reader and a notification caller. It contains no routine that reboots or powers
off the machine, terminates a solver, or changes system configuration. It is not designed to crash
the computer.

No software can promise that a machine will never fail. Windows, Python, the solver, the disk, and
the hardware can fail independently of this tool. `sim-sentinel` is not a substitute for solver
validation, backups, or system monitoring. Its correctness is limited to the rules in
`config.json`; `FINISHED` does not mean that a simulation result is physically correct.

## Operational limits

- The default process check recognizes names ending in `-engine.exe`. A solver with another process
  name requires a code change for `FAILED` and `STALLED` detection.
- A notification attempt can succeed while Windows suppresses the banner. Read `logs\toast.log`
  and check `setting=` and `banner=`.
- The state files contain file names and short log excerpts. Treat the `logs/` directory as private
  and do not attach it to a public issue.

## Reporting

Use GitHub Discussions or a minimal issue for defects. Do not attach a complete simulation log,
credentials, absolute workstation paths, or a full `logs/` directory. If a report needs a private
channel, ask in the issue first and the maintainer will arrange one.
