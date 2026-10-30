# sim-sentinel

When a simulation runs in the background — launched by a script, a batch job, or an agent — the progress
bar belongs to that process, not to you. The log keeps being written; you just never see it. This is a
one-minute Windows scheduled task that reads that log and raises **one** toast the first time a run is
seen to finish, fail or stall. Every verdict is appended to disk as a single JSON line, so "did it tell
me last night?" has an answer.

![license](https://img.shields.io/badge/license-MIT-blue)
![python](https://img.shields.io/badge/python-3.8%2B-blue)
![platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-lightgrey)
[![verdict tests](https://github.com/55093693k-dot/sim-sentinel/actions/workflows/tests.yml/badge.svg)](https://github.com/55093693k-dot/sim-sentinel/actions/workflows/tests.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23817306.svg)](https://doi.org/10.5281/zenodo.23817306)

**Who this is for.** Anyone running long local simulations — Lumerical FDTD or MODE, or any solver
that writes progress lines to a log — on a laptop, without a cluster and without wanting to install a
monitoring stack. That includes runs started by a script, a batch job or an agent, and runs left alone
with the lid closed.

**What it does not do.** It does not query the solver, does not judge whether a result is converged,
energy-conserving or correct, and does not submit or cancel a cloud task. It answers one question:
*did the run finish, fail, or stop moving?*

## The problem

A three-dimensional FDTD run or an EME sweep usually outlasts the time a person can sit in front of
the screen. The solver offers no completion callback: it writes a log and exits. So the only fact
available is the log file, and the only useful behaviour is to watch it from outside.

## How it decides

Three rules; every line of code traces to one of them.

| What it does | Why it is written that way |
|---|---|
| It only reads files | The tool never asks the solver anything. No log, no verdict. When it cannot read the process list it stays silent instead of guessing. |
| One message per run | Each log file has a small record remembering what was already announced. One run produces exactly one notification, however often it polls. |
| Proof it ran, not the program's own claim | A printed "success", a fresh *Last Run Time* and an exit code of 0 are not proof. A heartbeat timestamp, the output file's modification time and an append-only event record are. |

## What one poll does

1. The scheduled task fires and calls the launcher (a batch file).
2. The launcher writes one heartbeat line into `logs\` before anything else.
3. Python starts, reads `config.json`.
4. It scans the watch folder for `*_p0.log` (pattern is configurable) and skips anything untouched for 15 minutes.
5. For each log it reads **only the last 6 KB** — progress lines sit at the end, the whole file is not needed.
6. It checks two things against the pattern lists: a closing summary line, and an anchored error line.
7. **Only when there is no closing summary line** does it ask the operating system whether an engine process is alive. That is the slowest step in a poll, so it is skipped whenever the log already says "finished".
8. It compares with the stored record: a changed state raises one toast and appends one JSON line; then the record is saved and the process exits.

Nothing stays resident, and there is no background service. When nothing new has appeared, it does not even read the process list.

## Check it, do not trust it

The verdict is one function that takes text and facts and returns the verdict plus the evidence that
produced it — no I/O, no clock, no state. So its 14 tests run anywhere, Windows or not:

```
python -m unittest discover -s tests -v      # 14 tests, expected: OK
```

The two pattern lists live in `config.json`, so pointing the tool at another solver is a configuration
change. When a verdict looks wrong, `--explain <log>` prints which rule matched and which text it
matched; every event carries the same note in its `why` field, so `logs/events.jsonl` can answer "why
did it tell me that" months later.


## What it costs

Measured on the machine that produced this repository (2026-10-31, same code, conda base vs a
python.org 3.14 install):

| Situation | Wall clock | Peak memory |
|---|---|---|
| idle, no logs (process list not read) | 1.7–3.1 s | 15 MB (3.14) / 48 MB (conda base) |
| 500 finished logs | 1.7–3.4 s | same |
| 500 unfinished logs (reads the process list once) | 4.2–4.6 s | same |

- **Memory is not held, and the cost barely grows with the number of logs.** A process starts, uses
  tens of megabytes and exits; 500 logs cost under a second more than none. The interpreter is the one
  thing that matters — the same script peaks at 15 MB under python.org 3.14 and 48 MB under a miniconda
  base environment, which is the single line worth changing in `sentinel_run.cmd`.

On disk only two things grow: the state record (about 88 KB for 500 logs) and the event record
(one line per notification).

## Quick start

```
<ROOT>\
├─ sim\                       engine logs, <project>_p0.log, scanned recursively
├─ sentinel\                  sentinel.py / toast.ps1 / config.json
├─ launch\                    sentinel_run.cmd / register_tasks.ps1
├─ logs\                      state.json / events.jsonl / toast.log / heartbeat
└─ _selftest_kit.ps1          end-to-end self-test
```

1. Copy `sentinel/config.example.json` to `sentinel/config.json` and set `root` to `<ROOT>`.
2. In `launch/sentinel_run.cmd`, set the interpreter on the `set PY=` line. Nothing may follow it on
   that line — `set` takes the rest of the line as the value.
3. `powershell -ExecutionPolicy Bypass -File launch\register_tasks.ps1` — add `-Preview` to see the
   configuration without registering, `-Remove` to unregister.

Three settings are not optional; drop any one and the task "looks like it is running" while doing
nothing:

| Setting | Without it |
|---|---|
| `-AllowStartIfOnBatteries` / `-DontStopIfGoingOnBatteries` | On a laptop it stops triggering once unplugged, silently |
| `-MultipleInstances IgnoreNew` | One wedged instance makes every later trigger be dropped silently |
| `-ExecutionTimeLimit <finite>` | The default limit is 72 hours, so a wedged instance never frees itself |

## What you see

One toast:

```
Simulation finished: gc_taper_p0.log
elapsed 41m 07s   progress 99.4%
sim\gc_taper\gc_taper_p0.log
```

![Example toast](docs/toast-example.png)

> *The toast as it appears on the machine named in the test. The sender reads Windows PowerShell
> because the tool reuses that built-in app identifier — nothing is installed. `elapsed 4s`
> belongs to a demo run, not to a production run; visibility still depends on the system's
> notification settings.*

One line of evidence, appended, never rewritten:

```json
{"ts": "2026-10-29 17:34:52", "kind": "FINISHED", "log": "sim\\gc_taper\\gc_taper_p0.log",
 "pct": "99.4%", "last": "total FDTD solver speed on 10 processes (Mnodes/s): 214.5", "toast_rc": 0}
```

The two strings are built in `poll()`: the verdict word changes with the state, the rest is fixed, so
translating the toast is a one-line edit. Nothing else in the tool is language-dependent.

Two counter-intuitive facts live in the verdict vocabulary; read the comment block at the top of
`sentinel/sentinel.py` before changing it. `Auto Shutoff` is an automatic-shutoff *threshold* printed
on every progress line, not a completion marker. And the closing summary line of a finished run may
sit at 99.4%, so "wait for 100%" is not a criterion either. Error words are matched anchored
(`^\s*error\s*:`) because ordinary log prose contains "error" and "cannot" as well.

## Verify it yourself

```
powershell -ExecutionPolicy Bypass -File _selftest_kit.ps1
```

It copies the kit into a temporary directory, builds four fake logs, runs the sentinel ten times in
order and asserts "silent when it should be silent, one notification when it should report". The
sandbox is deleted afterwards (`-Keep` keeps it); no toast is shown and no real state is touched.
When the `tests/` directory is present it also runs the pure verdict tests first. Expected output:

```
--- verdict tests ---
OK
PASS  finished log, FIRST sight -> silent baseline   expect=0 got=0
PASS  same log again -> still silent (dedupe)        expect=0 got=0
PASS  progress only -> no verdict                    expect=0 got=0
PASS  error appears in same log -> FAILED fires once  expect=1 got=1
PASS  FAILED again -> deduped                        expect=1 got=1
PASS  unchanged size x3 polls -> STALLED (4th run)    expect=2 got=2
PASS  pause marker -> polling skipped                 expect=2 got=2
RESULT: ALL PASS
```

## Readings

Each number carries the conditions it was taken under; without them the number means nothing here.

| Quantity | Reading | Conditions |
|---|---|---|
| verdict-rule cases | 6/6 pass | 2026-09-26, one machine |
| replay of real logs | 77 logs → FINISHED 68 / FAILED 1 / UNKNOWN 8 | same day, one-off re-judgement of that work tree |
| logs covered per poll | 503 files | health report of 2026-10-22 09:15 |
| heartbeat continuity | 13 consecutive minute timestamps (15:22:02 → 15:34:02) | that machine, unattended |
| end-to-end self-test | 7/7 assertions | 2026-10-29 and 2026-10-31, temporary directory |
| verdict unit tests | 14 pass | 2026-10-31, local Python 3.13; the same command runs in CI on Ubuntu for 3.10 and 3.12 |
| wedged-task fingerprint | `State=Running` + `Last Result=267009` | 0x00041301, an instance still running |

## Limitations and known defects

- **Windows only.** The application identifier, the task scheduler and the process list are Windows
  features. On Linux the state machine and the verdict vocabulary carry over unchanged; `cron` and
  `notify-send` replace the two outer layers.
- **Local logs only.** A cloud job (Tidy3D, for example) writes its log elsewhere, and needs a separate
  read-only poller: query task status, never submit or cancel, keep credentials in a local file outside
  any repository. This repository does not contain that channel.
- **It does not judge the physics.** "Did it finish" is a different question from "is the result right".
- **First-sight silence has a cost.** If a run finishes between two polls and its log is then removed,
  that notification never arrives. One-minute polling plus a fifteen-minute window makes this
  unlikely, not impossible.
- **No scheduled task is registered by this repository.** The tool ran for real on one Windows machine
  between September and October 2026; this repository is a rebuild that can be re-run — every path
  comes from `config.json`, so moving the directory no longer breaks it. The historical version kept
  paths in constants and died when the folder moved.
- **Whether a toast is visible depends on system settings.** Focus assist, the per-sender switch and
  policy can all swallow it. The tool can record "the call succeeded"; it cannot record "a person saw it".

## Cloud solvers (Tidy3D and similar)

A cloud job writes no local log: the solver runs on the provider's side, the client shows a progress
bar, and the authoritative state is the task's `status` (queued → … → success / error), reachable only
through the SDK with a key. So this repository does not cover cloud runs — the record-keeping part would
port to a read-only status poller unchanged, but that port needs a dependency and a credential, which is
what this tool exists to avoid.

## Troubleshooting

| Symptom | What it means |
|---|---|
| `no event (engines_alive=…, logs_watched=0)` | `root` or `watch_subdir` in `config.json` does not point at the logs |
| Task shows *Last Result 0*, nothing ever runs | the launcher's heartbeat line is stale — see "wedged-task fingerprint" above, and check the `.cmd` kept its Windows line endings |
| `Last Result 267009` with `State: Running` | an instance is wedged; end it, then trigger once by hand |
| Toast log full of `OK`, screen empty | the notification was blocked by the system, not by the script |

## Citation

Cite the **concept DOI**, which always resolves to the newest archived version:

**[10.5281/zenodo.23817306](https://doi.org/10.5281/zenodo.23817306)** — `CITATION.cff` carries it.

Version DOIs (one per release, frozen) are listed on that record page; name the version in the text if
a number matters. The archived snapshot for a given version is the repository at that release tag.

Questions and suggestions go to **[Discussions](https://github.com/55093693k-dot/sim-sentinel/discussions)**
or the issue tracker. This is a personal tool and replies are not guaranteed to be quick; if you adapt
the verdict vocabulary to another solver, paste the vocabulary together with the raw log lines it was
derived from — that is more useful than a description of the symptom.

## Licence

Code (`*.py`, `*.ps1`, `*.cmd`, `*.json`) is MIT — see `LICENSE`. The written text, including this
file, is CC BY 4.0 — see `LICENSE-docs.md`.
