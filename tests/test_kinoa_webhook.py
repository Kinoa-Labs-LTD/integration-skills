"""Offline unit tests for skills/kinoa-api-integration/kinoa_webhook.py
(and its verbatim copy in kinoa-sdk-dashboard-sync).

No network — `_post` is monkeypatched. Run from the repo root:

    python -m unittest discover tests -v
"""

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIMARY = os.path.join(REPO_ROOT, "skills", "kinoa-api-integration", "kinoa_webhook.py")
COPY = os.path.join(REPO_ROOT, "skills", "kinoa-sdk-dashboard-sync", "kinoa_webhook.py")


def _load_module(path):
    spec = importlib.util.spec_from_file_location("kinoa_webhook_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class WebhookQaTests(unittest.TestCase):
    def setUp(self):
        # Isolate HOME so flag-less tests can't load a real ~/.kinoa/session.env into the
        # process env, and snapshot/restore os.environ so nothing leaks across modules.
        self._saved_environ = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._saved_environ)))
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        os.environ["USERPROFILE"] = self._home.name
        os.environ["HOME"] = self._home.name
        self.mod = _load_module(PRIMARY)
        self.mod.SESSION_ENV_PATH = os.path.join(self._home.name, "session.env")
        os.environ["KINOA_GAME_ID"] = "11111111-1111-1111-1111-111111111111"
        self.posted = []
        self.mod._post = lambda payload: (self.posted.append(payload) or {"ok": True, "http_status": 200, "response": {"id": 1}})

    def _run(self, argv):
        out = io.StringIO()
        import sys
        old_argv = sys.argv
        sys.argv = ["kinoa_webhook.py"] + argv
        try:
            with contextlib.redirect_stdout(out):
                code = self.mod.main()
        finally:
            sys.argv = old_argv
        return code, json.loads(out.getvalue())

    def test_qa_answer_arg_backward_compatible(self):
        code, result = self._run(["qa", "--question", "Which?", "--answer", "Recommended (1-17)"])
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(self.posted[0]["prompt"], "Recommended (1-17)")
        self.assertEqual(self.posted[0]["lastQuestion"], "Which?")

    def test_qa_answer_file_reads_and_normalizes_crlf(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, newline="", encoding="utf-8") as f:
            f.write("## Round 4 — 2026-06-12\r\n\r\nline two\r\nline three")
            path = f.name
        self.addCleanup(os.unlink, path)
        code, result = self._run(["qa", "--question", "", "--answer-file", path])
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertNotIn("\r", self.posted[0]["prompt"])
        self.assertEqual(self.posted[0]["prompt"], "## Round 4 — 2026-06-12\n\nline two\nline three")

    def test_qa_answer_file_unreadable_reports_and_exits_zero(self):
        code, result = self._run(["qa", "--question", "", "--answer-file", os.path.join(tempfile.gettempdir(), "no-such-file-xyz.md")])
        self.assertEqual(code, 0)  # telemetry never aborts the run
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "answer_file_unreadable")
        self.assertEqual(self.posted, [])

    def test_game_id_flag_overrides_env_and_session(self):
        code, result = self._run(["qa", "--question", "q", "--answer", "a",
                                  "--game-id", "22222222-2222-2222-2222-222222222222"])
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(self.posted[0]["gameId"], "22222222-2222-2222-2222-222222222222")

    def test_game_id_flag_works_without_env(self):
        os.environ.pop("KINOA_GAME_ID", None)
        # _load_session_env must not run when the flag is given — make it explode if it does.
        self.mod._load_session_env = lambda: (_ for _ in ()).throw(AssertionError("session.env consulted despite --game-id"))
        code, result = self._run(["phase-start", "--phase", "Phase 7 — dashboard sync",
                                  "--game-id", "33333333-3333-3333-3333-333333333333"])
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(self.posted[0]["gameId"], "33333333-3333-3333-3333-333333333333")
        self.assertEqual(self.posted[0]["prompt"], "Phase started: Phase 7 — dashboard sync")

    def test_qa_requires_exactly_one_answer_source(self):
        import sys
        for argv in (["qa", "--question", "q"],
                     ["qa", "--question", "q", "--answer", "a", "--answer-file", "f"]):
            old_argv = sys.argv
            sys.argv = ["kinoa_webhook.py"] + argv
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        self.mod.main()
                self.assertEqual(ctx.exception.code, 2)  # argparse usage error
            finally:
                sys.argv = old_argv

    def test_qa_answer_file_non_utf8_degrades_not_crash(self):
        # The whole point of errors="replace": a mis-encoded byte must degrade the payload,
        # never crash the helper. A regression to errors="strict" raises UnicodeDecodeError
        # (a ValueError, NOT caught by `except OSError`) and this test would fail loudly.
        with tempfile.NamedTemporaryFile("wb", suffix=".md", delete=False) as f:
            f.write(b"## Round X\r\nbad byte: \xff here\r\ntail")
            path = f.name
        self.addCleanup(os.unlink, path)
        code, result = self._run(["qa", "--question", "", "--answer-file", path,
                                  "--game-id", "44444444-4444-4444-4444-444444444444"])
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        prompt = self.posted[0]["prompt"]
        self.assertNotIn("\r", prompt)              # CRLF normalized
        self.assertIn("�", prompt)             # invalid byte replaced, not crashed
        self.assertIn("bad byte:", prompt)

    def test_qa_answer_file_strips_utf8_bom(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".md", delete=False) as f:
            f.write(b"\xef\xbb\xbf# Heading\nbody")   # UTF-8 BOM prefix
            path = f.name
        self.addCleanup(os.unlink, path)
        code, result = self._run(["qa", "--question", "", "--answer-file", path,
                                  "--game-id", "44444444-4444-4444-4444-444444444444"])
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(self.posted[0]["prompt"], "# Heading\nbody")  # BOM stripped by utf-8-sig

    def test_qa_empty_answer_file_path_reports_unreadable(self):
        # --answer-file "" satisfies the required group; it must surface as unreadable,
        # not silently post an empty answer.
        code, result = self._run(["qa", "--question", "q", "--answer-file", "",
                                  "--game-id", "44444444-4444-4444-4444-444444444444"])
        self.assertEqual(code, 0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "answer_file_unreadable")
        self.assertEqual(self.posted, [])

    def test_qa_missing_game_id_everywhere_skips_and_exits_zero(self):
        # No --game-id, no env (popped), no session.env (HOME isolated) → the terminal
        # branch of the resolution chain: report missing_game_id, post nothing, exit 0.
        os.environ.pop("KINOA_GAME_ID", None)
        code, result = self._run(["qa", "--question", "q", "--answer", "a"])
        self.assertEqual(code, 0)
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("skipped"))
        self.assertEqual(result["error"], "missing_game_id")
        self.assertEqual(self.posted, [])

    def test_phase_end_game_id_and_prompt(self):
        code, result = self._run(["phase-end", "--phase", "Phase 7 — dashboard sync (plugin)",
                                  "--summary", "applied=2 status=completed",
                                  "--game-id", "55555555-5555-5555-5555-555555555555"])
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(self.posted[0]["gameId"], "55555555-5555-5555-5555-555555555555")
        self.assertEqual(self.posted[0]["prompt"],
                         "Phase ended: Phase 7 — dashboard sync (plugin) — applied=2 status=completed")

    def test_copies_are_identical(self):
        with open(PRIMARY, "rb") as a, open(COPY, "rb") as b:
            self.assertEqual(a.read(), b.read(), "kinoa_webhook.py copies diverged — re-copy after edits")


if __name__ == "__main__":
    unittest.main()
