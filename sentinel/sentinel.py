# -*- coding: utf-8 -*-
r"""sentinel.py -- simulation sentinel: toast when a run finishes, fails or stalls.

WHY IT IS WRITTEN THIS WAY (read before changing anything):

  1. EVIDENCE ONLY. It never queries the solver. It reads the engine log the
     solver wrote itself (`<project>_p0.log`). No log -> no verdict.
  2. TRANSITIONS ONLY. State is remembered per log file, so one run produces
     exactly one notification, no matter how many times it polls.
  3. THREE-STATE PROCESS CHECK. alive = True / False / None. None means "cannot
     read the process table" and must NEVER be turned into a verdict.

THE VERDICT ITSELF IS A PURE FUNCTION (`classify`): text in, verdict plus the
evidence that produced it out. No I/O, no clock, no state. That is what lets
`tests/test_verdict.py` run the same logic on any operating system, and what
lets `--explain` print why a log was judged the way it was.

USAGE
  python sentinel.py --once          one poll (what the scheduled task runs)
  python sentinel.py --loop 30       resident mode
  python sentinel.py --test          send one test toast and exit
  python sentinel.py --no-toast      detect + log, notify nothing (dry run)
  python sentinel.py --all           ignore the mtime window (replay everything)
  python sentinel.py --explain [LOG] print the verdict and the matching lines for
                                     one log, or for every watched log (read-only)

FILES (relative to the configured root)
  <root>/<watch_subdir>/...        engine logs, scanned recursively
  <root>/logs/state.json           one record per log file (survives restarts)
  <root>/logs/events.jsonl         append-only evidence
  <root>/logs/toast.log            one line per toast attempt
  <root>/sentinel.pause            while present, polling is skipped
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import time

# A Chinese Windows console may use cp950. A non-ASCII config path must not crash the
# check while it is explaining a different problem.
try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")

#: The verdict vocabulary is DATA, not code: `config.json` may replace either list
#: with whole regex fragments. Every default below was checked against real logs; a
#: bare word such as `error` must never appear on its own (see the note below).
DEFAULTS = {
    "root": r"D:\SimWorkbench",
    "watch_subdir": "sim",
    "log_glob": "**/*_p0.log",
    "tail_bytes": 6000,
    "mtime_window_s": 900,
    "stall_after": 3,
    "toast_aumid": "",
    "toast_sound": "",
    "done_patterns": [
        "solver speed",
        r"overall\s+\w+\s+run time",
        "total simulation time",
        "simulation completed",
        r"100(?:\.0+)?\s*%\s*complete",
    ],
    "error_patterns": [
        r"^\s*error\s*:",
        r"^\s*fatal",
        "unknown parallel error",
        r"error code\s+\d+",
        "not enough memory",
        "license error",
        "could not be started",
        "aborted",
    ],
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG, "r", encoding="utf-8-sig") as fh:
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass                      # missing/broken config -> defaults, never crash
    return cfg


CFG = load_config()
ROOT = CFG["root"]
WATCH = os.path.join(ROOT, CFG["watch_subdir"])
LOGDIR = os.path.join(ROOT, "logs")
STATE = os.path.join(LOGDIR, "state.json")
EVENTS = os.path.join(LOGDIR, "events.jsonl")
TOASTLOG = os.path.join(LOGDIR, "toast.log")
TOASTPS1 = os.path.join(HERE, "toast.ps1")
PAUSE = os.path.join(ROOT, "sentinel.pause")
POWERSHELL = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                          r"System32\WindowsPowerShell\v1.0\powershell.exe")


def build_patterns(done_list, error_list):
    """Compile the two lists into regexes. An empty list matches nothing."""
    def _one(items):
        items = [p for p in (items or []) if p]
        if not items:
            return re.compile(r"(?!)")
        return re.compile("|".join("(?:%s)" % p for p in items), re.I | re.M)

    return _one(done_list), _one(error_list)


# 'Auto Shutoff: 0.101703' is printed on EVERY progress line by some Lumerical
# versions, so it is NOT a completion marker. A finished run is identified by the
# engine's closing summary line, and it may stop at 99.4% -- so "wait for 100%"
# does not work either.
#
# The error list is anchored on purpose: benign prose contains 'error' and
# 'cannot' too, and a bare word match produced FAILED verdicts on runs that had
# already finished.
DONE_RE, ERR_RE = build_patterns(CFG["done_patterns"], CFG["error_patterns"])


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def append(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_state():
    try:
        with open(STATE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False, indent=1)


def engines_alive():
    """True = an engine is running, False = definitely none, None = cannot tell.

    Returning None on failure is the whole point: an unknown must never become a
    FAILED or STALLED verdict.
    """
    try:
        out = subprocess.run(["tasklist", "/fo", "csv", "/nh"],
                             capture_output=True, timeout=25).stdout.decode("utf-8", "replace")
    except Exception:
        return None
    names = re.findall(r'"([^"]+\.exe)"', out)
    return bool([n for n in names if n.lower().endswith("-engine.exe")])


def tail(path, n=None):
    n = n or CFG["tail_bytes"]
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.seek(max(0, size - n))
            return fh.read().decode("utf-8", "replace"), size
    except OSError:
        return "", 0


def notify(title, body):
    """Toast via toast.ps1. The text goes through a UTF-8 FILE, never argv."""
    if "--no-toast" in sys.argv:
        append(EVENTS, {"ts": now(), "kind": "NO_TOAST", "title": title, "body": body})
        return 0
    os.makedirs(LOGDIR, exist_ok=True)
    tmp = os.path.join(LOGDIR, "_toast_msg.txt")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(title + "\n" + body + "\n")
    try:
        cmd = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", TOASTPS1, "-TextFile", tmp, "-LogFile", TOASTLOG]
        if CFG.get("toast_aumid"):
            cmd += ["-AppId", str(CFG["toast_aumid"])]
        if CFG.get("toast_sound"):
            sound = os.path.expandvars(os.path.expanduser(str(CFG["toast_sound"])))
            cmd += ["-SoundFile", sound]
        r = subprocess.run(cmd, capture_output=True, timeout=40)
        return r.returncode
    except Exception as e:
        append(EVENTS, {"ts": now(), "kind": "toast_error", "err": str(e)})
        return -1


def watched():
    return glob.glob(os.path.join(WATCH, CFG["log_glob"]), recursive=True)


#: What the last poll learned about the process table, so `main()` can print it without
#: asking the operating system a second time. Reading the process list is the single most
#: expensive call in a poll (measured: about 2 s on a loaded machine), and it is only needed
#: for a log that does not already show a closing summary line.
_LAST_ALIVE = {"value": "not queried"}


def classify(tail_text, alive, size, prev_size, stall_count, stall_after,
             done_re=None, err_re=None):
    """Verdict for ONE log file, from text and facts only.

    Pure on purpose: no file I/O, no clock, no state mutation. Everything that can
    be wrong about a verdict is decided here, and therefore testable anywhere.

    Returns (status, stall_count, evidence):
      status       None | "FINISHED" | "FAILED" | "STALLED"
      stall_count  the counter to store for the next poll
      evidence     [(rule, detail), ...] in the order the rules were applied
    """
    done_re = DONE_RE if done_re is None else done_re
    err_re = ERR_RE if err_re is None else err_re
    ev = []

    m = done_re.search(tail_text)
    if m:
        ev.append(("done", "matched %r" % m.group(0).strip()))
        return "FINISHED", stall_count, ev
    ev.append(("done", "no closing summary line"))

    e = err_re.search(tail_text)
    if e:
        ev.append(("error", "matched %r" % e.group(0).strip()))
    else:
        ev.append(("error", "no anchored error pattern"))

    if alive is False:
        ev.append(("alive", "False -- no engine process"))
        if e:
            return "FAILED", stall_count, ev
        stall_count = stall_count + 1 if size == prev_size else 0
        ev.append(("stall", "size %d, unchanged for %d of %d polls"
                   % (size, stall_count, stall_after)))
        if stall_count >= stall_after:
            return "STALLED", stall_count, ev
        return None, stall_count, ev

    ev.append(("alive", "None -- cannot read the process table"
               if alive is None else "True -- an engine is running"))
    return None, stall_count, ev


def explain(arg=None):
    """Print the verdict and its evidence. Read-only: no toast, no state written."""
    if arg:
        targets = [arg]
    else:
        targets = watched()[:20]
        if not targets:
            print("no logs matched %s under %s" % (CFG["log_glob"], WATCH))
            return 0
    st = load_state()
    alive = engines_alive()
    for lg in targets:
        txt, size = tail(lg)
        rec = st.get(os.path.normcase(lg), {"size": -1, "stall": 0})
        status, stall, ev = classify(txt, alive, size, rec.get("size", -1),
                                     rec.get("stall", 0), CFG["stall_after"])
        print("log      : %s" % lg)
        print("size     : %d  (previous %s)" % (size, rec.get("size", -1)))
        print("alive    : %s" % alive)
        print("verdict  : %s" % (status or "no verdict (state unchanged or unknown)"))
        for rule, detail in ev:
            print("  %-7s %s" % (rule, detail))
        print("")
    return 0


def poll():
    """One detection pass. Returns the events raised."""
    if os.path.exists(PAUSE):
        return []
    st = load_state()
    alive = None
    alive_known = False
    events = []
    for lg in watched():
        try:
            age = time.time() - os.path.getmtime(lg)
        except OSError:
            continue
        if age > CFG["mtime_window_s"] and "--all" not in sys.argv:
            continue                # historical runs stay silent, so a lost or
                                    # corrupt state file cannot spam you
        key = os.path.normcase(lg)
        rec = st.get(key, {"size": -1, "stall": 0, "announced": ""})
        if "first_seen" not in rec:
            rec["first_seen"] = time.time()
        fresh = key not in st        # first time we ever see this log
        txt, size = tail(lg)
        last_line = ""
        for line in reversed(txt.splitlines()):
            if line.strip():
                last_line = line.strip()
                break
        pct = ""
        hits = list(re.finditer(r"(\d+(?:\.\d+)?)\s*%\s*complete", txt, re.I))
        if hits:
            pct = hits[-1].group(1) + "%"

        # Ask for the process list only when the log does not already say "finished":
        # the closing summary line is enough on its own, and the process list is the
        # expensive part of a poll.
        if DONE_RE.search(txt) is None and not alive_known:
            alive, alive_known = engines_alive(), True
            _LAST_ALIVE["value"] = alive

        status, rec["stall"], ev = classify(txt, alive, size, rec.get("size", -1),
                                            rec.get("stall", 0), CFG["stall_after"])
        rec["size"] = size
        st[key] = rec

        if status and fresh:
            # First sighting: adopt it as the baseline and stay SILENT. Without
            # this, the very first run toasts every already-finished log.
            rec["announced"] = status + os.path.basename(lg)
        elif status and rec.get("announced") != status + os.path.basename(lg):
            rec["announced"] = status + os.path.basename(lg)
            rel = os.path.relpath(lg, ROOT)
            name = os.path.basename(lg)
            label = {"FINISHED": "finished", "FAILED": "failed", "STALLED": "stalled"}[status]
            elapsed = ""
            try:
                secs = time.time() - float(rec.get("first_seen", 0) or 0)
                if secs > 0:
                    elapsed = ("%dm %02ds" % (int(secs // 60), int(secs % 60))
                               if secs >= 60 else ("%ds" % int(secs)))
            except Exception:
                elapsed = ""
            title = "Simulation %s: %s" % (label, name)
            body = "elapsed %s%s\n%s" % (elapsed or "not observed",
                                         "   progress " + pct if pct else "", rel)
            rc = notify(title, body)
            why = "; ".join("%s: %s" % (r, d) for r, d in ev)[:200]
            event = {"ts": now(), "kind": status, "log": rel, "pct": pct,
                     "last": last_line[:200], "toast_rc": rc, "why": why}
            events.append(event)
            append(EVENTS, event)
    try:
        save_state(st)
    except Exception as e:
        append(EVENTS, {"ts": now(), "kind": "state_save_error", "err": str(e)})
    return events


def main():
    args = sys.argv[1:]
    if "--test" in args:
        rc = notify("Sentinel self-test", "toast channel OK; the scheduled task is enabled.\n" + now())
        append(EVENTS, {"ts": now(), "kind": "TEST", "toast_rc": rc})
        print("test toast rc=%s" % rc)
        return 0
    if "--explain" in args:
        i = args.index("--explain")
        rest = [a for a in args[i + 1:] if not a.startswith("--")]
        return explain(rest[0] if rest else None)
    if not os.path.isdir(WATCH):
        print("%s watch directory does not exist: %s" % (now(), WATCH))
        print("  fix `root` / `watch_subdir` in %s" % CONFIG)
        return 0
    if "--loop" in args:
        i = args.index("--loop")
        secs = int(args[i + 1]) if len(args) > i + 1 else 30
        print("resident mode, poll every %ds (Ctrl+C to stop)" % secs)
        while True:
            for e in poll():
                print("%s %s %s" % (e["ts"], e["kind"], e["log"]))
            time.sleep(secs)
    ev = poll()
    for e in ev:
        print("%s %s %s toast_rc=%s" % (e["ts"], e["kind"], e["log"], e.get("toast_rc")))
    if not ev:
        print("%s no event (engines_alive=%s, logs_watched=%d)"
              % (now(), _LAST_ALIVE["value"], len(watched())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



