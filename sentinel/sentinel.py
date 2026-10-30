# -*- coding: utf-8 -*-
r"""sentinel.py -- simulation sentinel: toast when a run finishes, fails or stalls.

WHY IT IS WRITTEN THIS WAY (read before changing anything):

  1. EVIDENCE ONLY. It never queries the solver. It reads the engine log the
     solver wrote itself (`<project>_p0.log`). No log -> no verdict.
  2. TRANSITIONS ONLY. State is remembered per log file, so one run produces
     exactly one notification, no matter how many times it polls.
  3. THREE-STATE PROCESS CHECK. alive = True / False / None. None means "cannot
     read the process table" and must NEVER be turned into a verdict.

USAGE
  python sentinel.py --once        one poll (this is what the scheduled task runs)
  python sentinel.py --loop 30     resident mode
  python sentinel.py --test        send one test toast and exit
  python sentinel.py --no-toast    detect + log, notify nothing (dry run)
  python sentinel.py --all         ignore the mtime window (replay everything)

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

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")

DEFAULTS = {
    "root": r"D:\SimWorkbench",
    "watch_subdir": "sim",
    "log_glob": "**/*_p0.log",
    "tail_bytes": 6000,
    "mtime_window_s": 900,
    "stall_after": 3,
}

# ---------------------------------------------------------------------------
# VERDICT VOCABULARY -- these two regexes are the whole "brain" of the tool.
#
# 'Auto Shutoff: 0.101703' is printed on EVERY progress line by some Lumerical
# versions, so it is NOT a completion marker. A finished run is identified by
# the engine's closing summary line, and it may stop at 99.4% -- so "wait for
# 100%" does not work either.
# ---------------------------------------------------------------------------
DONE_RE = re.compile(r"(solver speed|overall\s+\w+\s+run time|total simulation time|"
                     r"simulation completed|100(?:\.0+)?\s*%\s*complete)", re.I)
# Anchored on purpose: benign prose contains 'error' and 'cannot' too, and a bare
# word match produced FAILED verdicts on runs that had already finished.
ERR_RE = re.compile(r"(^\s*error\s*:|^\s*fatal|unknown parallel error|error code\s+\d+|"
                    r"not enough memory|license error|could not be started|aborted)",
                    re.I | re.M)
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*complete", re.I)


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG, "r", encoding="utf-8") as fh:
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
        r = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", TOASTPS1, "-TextFile", tmp, "-LogFile", TOASTLOG],
                           capture_output=True, timeout=40)
        return r.returncode
    except Exception as e:
        append(EVENTS, {"ts": now(), "kind": "toast_error", "err": str(e)})
        return -1


def watched():
    return glob.glob(os.path.join(WATCH, CFG["log_glob"]), recursive=True)


def poll():
    """One detection pass. Returns the events raised."""
    if os.path.exists(PAUSE):
        return []
    st = load_state()
    alive = engines_alive()
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
        hits = list(PCT_RE.finditer(txt))
        if hits:
            pct = hits[-1].group(1) + "%"
        done = bool(DONE_RE.search(txt))
        err = bool(ERR_RE.search(txt))

        status = None
        if done:
            status = "FINISHED"
        elif alive is False and err:
            status = "FAILED"
        elif alive is False:
            # a stall verdict needs a CHANGE criterion, not one observation
            rec["stall"] = rec.get("stall", 0) + 1 if size == rec.get("size") else 0
            if rec["stall"] >= CFG["stall_after"]:
                status = "STALLED"
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
            zh = {"FINISHED": "完成", "FAILED": "失败", "STALLED": "疑似中断"}[status]
            elapsed = ""
            try:
                secs = time.time() - float(rec.get("first_seen", 0) or 0)
                if secs > 0:
                    elapsed = ("%d分%02d秒" % (int(secs // 60), int(secs % 60))
                               if secs >= 60 else ("%d秒" % int(secs)))
            except Exception:
                elapsed = ""
            title = "仿真" + zh + "：" + name
            body = "耗时 " + (elapsed or "未观测") + ("　进度 " + pct if pct else "") + "\n" + rel
            rc = notify(title, body)
            ev = {"ts": now(), "kind": status, "log": rel, "pct": pct,
                  "last": last_line[:200], "toast_rc": rc}
            events.append(ev)
            append(EVENTS, ev)
    try:
        save_state(st)
    except Exception as e:
        append(EVENTS, {"ts": now(), "kind": "state_save_error", "err": str(e)})
    return events


def main():
    args = sys.argv[1:]
    if "--test" in args:
        rc = notify("哨兵自检 ✓", "toast 通路正常；计划任务已启用。\n" + now())
        append(EVENTS, {"ts": now(), "kind": "TEST", "toast_rc": rc})
        print("test toast rc=%s" % rc)
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
              % (now(), engines_alive(), len(watched())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


