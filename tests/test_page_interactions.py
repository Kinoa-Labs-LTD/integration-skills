"""jsdom interaction layer: drives the REAL generated pages the way a user would.

The static unit suite pins the generated HTML as text; this layer executes it —
typing char-by-char across re-renders, clicking checkboxes/pencils, and asserting
on the page's own exportJson() hand-back. It caught bugs no static test can (the
enum-comma-eating regression exists only in the keystroke -> re-render -> focus
loop). Skips cleanly when Node or the jsdom package is unavailable:

    cd tests/page-harness && npm install   # one-time, installs jsdom locally
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS_DIR = os.path.join(HERE, "page-harness")
JSDOM = os.path.join(HARNESS_DIR, "node_modules", "jsdom")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
@unittest.skipUnless(os.path.isdir(JSDOM),
                     "jsdom not installed — run `npm install` in tests/page-harness")
class PageInteractionTests(unittest.TestCase):
    def test_harness_all_scenarios_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [sys.executable, os.path.join(HARNESS_DIR, "make_fixtures.py"), tmp],
                check=True, capture_output=True, text=True)
            proc = subprocess.run(
                ["node", os.path.join(HARNESS_DIR, "harness.js"), tmp],
                capture_output=True, text=True)
            if proc.returncode != 0:
                failed = "\n".join(l for l in proc.stdout.splitlines() if l.startswith("FAIL"))
                self.fail(f"jsdom harness failed:\n{failed or proc.stdout[-2000:]}\n{proc.stderr[-500:]}")


if __name__ == "__main__":
    unittest.main()
