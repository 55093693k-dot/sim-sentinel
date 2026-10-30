# -*- coding: utf-8 -*-
"""Verdict tests: the pure `classify()` function, no Windows required.

Run from the repository root:

    python -m unittest discover -s tests -v

Every case below is a real log tail or a real misjudgement recorded while this
tool was being written. Nothing here touches the filesystem, the clock or a
process table; that is the point of keeping the verdict pure.
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "sentinel"))

import sentinel  # noqa: E402  (path must be set first)

# --- the four tails that decide everything ---------------------------------
DONE = ("99.3998% complete. Max time remaining: 3 hrs\n"
        "total FDTD solver speed on 10 processes (Mnodes/s): 214.504635\n")
PROGRESS = ("2.00031% complete. Elapsed simulation time: 1.20019e-13 secs. "
            "Max time remaining: 41 hrs. Auto Shutoff: 0.101703\n")
ERROR = ("Error: there was an unknown parallel error. "
         "The error code is 10, the process number is 0\n")
EME_DONE = "Overall EME run time (s): 483.773\n"
BENIGN = ("loaded material data from library; cannot find optional cache, "
          "using defaults. no error.\n")
HUNDRED = "100% complete. Auto Shutoff: 0.0005\n"


def verdict(text, alive=True, size=1000, prev=1000, stall=0, after=3, **regexes):
    """Call the pure function with explicit facts."""
    status, stall_out, ev = sentinel.classify(text, alive, size, prev, stall, after, **regexes)
    return status, stall_out, ev


class VerdictVocabulary(unittest.TestCase):
    def test_closing_summary_line_is_finished(self):
        status, _, ev = verdict(DONE, alive=True)
        self.assertEqual(status, "FINISHED")
        self.assertIn("solver speed", " ".join(d for _, d in ev))

    def test_auto_shutoff_alone_is_not_finished(self):
        status, _, ev = verdict(PROGRESS, alive=True)
        self.assertIsNone(status)
        self.assertIn("no closing summary line", " ".join(d for _, d in ev))

    def test_eme_summary_line_is_finished(self):
        self.assertEqual(verdict(EME_DONE)[0], "FINISHED")

    def test_hundred_percent_plus_threshold_is_finished(self):
        self.assertEqual(verdict(HUNDRED)[0], "FINISHED")

    def test_anchored_error_with_dead_process_is_failed(self):
        status, _, ev = verdict(ERROR, alive=False)
        self.assertEqual(status, "FAILED")
        self.assertTrue(any(r == "error" for r, _ in ev))

    def test_benign_prose_is_not_an_error(self):
        status, _, _ = verdict(BENIGN, alive=False)
        self.assertNotEqual(status, "FAILED")

    def test_error_text_with_a_live_process_is_not_failed(self):
        # an engine still running may be retrying; a log line alone is not a failure
        self.assertIsNone(verdict(ERROR, alive=True)[0])


class ProcessState(unittest.TestCase):
    def test_unknown_alive_never_becomes_a_verdict(self):
        for text in (DONE, ERROR, PROGRESS, BENIGN):
            status, _, _ = verdict(text, alive=None)
            self.assertNotIn(status, ("FAILED", "STALLED"))

    def test_unknown_alive_still_reports_finished(self):
        # FINISHED comes from the log alone, so it does not need the process table
        self.assertEqual(verdict(DONE, alive=None)[0], "FINISHED")


class StallCriterion(unittest.TestCase):
    def test_three_unchanged_polls_are_stalled_on_the_third(self):
        stall = 0
        seen = []
        for _ in range(3):
            status, stall, _ = verdict(PROGRESS, alive=False, size=500, prev=500, stall=stall)
            seen.append(status)
        self.assertEqual(seen, [None, None, "STALLED"])
        self.assertEqual(stall, 3)

    def test_growth_resets_the_counter(self):
        status, stall, _ = verdict(PROGRESS, alive=False, size=600, prev=500, stall=2)
        self.assertIsNone(status)
        self.assertEqual(stall, 0)

    def test_one_observation_is_never_enough(self):
        self.assertIsNone(verdict(PROGRESS, alive=False, size=500, prev=500, stall=0)[0])


class VocabularyIsData(unittest.TestCase):
    def test_custom_pattern_lists_are_honoured(self):
        done_re, err_re = sentinel.build_patterns(["my solver is done"], ["^boom"])
        status, _, _ = verdict("my solver is done\n", done_re=done_re, err_re=err_re)
        self.assertEqual(status, "FINISHED")
        status, _, _ = verdict("boom: give up\n", alive=False, done_re=done_re, err_re=err_re)
        self.assertEqual(status, "FAILED")

    def test_empty_lists_match_nothing(self):
        done_re, err_re = sentinel.build_patterns([], [])
        self.assertFalse(done_re.search(DONE))
        self.assertFalse(err_re.search(ERROR))
        self.assertIsNone(verdict(DONE, alive=False, done_re=done_re, err_re=err_re)[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
