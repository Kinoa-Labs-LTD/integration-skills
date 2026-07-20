"""Offline unit tests for skills/kinoa-open-session/kinoa_open_session.py.

No network — `_request` is monkeypatched; HOME is redirected so session.env
lives in a temp dir. Run from the repo root:

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
SCRIPT_PATH = os.path.join(REPO_ROOT, "skills", "kinoa-open-session", "kinoa_open_session.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("kinoa_open_session_under_test", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OpenSessionTests(unittest.TestCase):
    def setUp(self):
        self._saved_environ = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._saved_environ)))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["USERPROFILE"] = self.tmp.name
        os.environ["HOME"] = self.tmp.name
        self.mod = _load_module()
        self.mod.SESSION_DIR = self.tmp.name
        self.mod.SESSION_ENV_PATH = os.path.join(self.tmp.name, "session.env")
        os.environ["KINOA_GAME_SECRET"] = "FAKE_SECRET"
        self.requests = []

    def _run_main(self, argv, responses):
        queue = list(responses)

        def fake_request(method, url, headers=None, body=None):
            self.requests.append({"method": method, "url": url, "headers": headers, "body": body})
            return queue.pop(0)

        self.mod._request = fake_request
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(argv)
        return code, json.loads(out.getvalue())

    def _session_env(self):
        env = {}
        if not os.path.exists(self.mod.SESSION_ENV_PATH):
            return env
        with open(self.mod.SESSION_ENV_PATH, "r") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                env[k] = v
        return env

    def test_success_persists_last_ids(self):
        code, result = self._run_main(["--player-id", "p-1"], [(200, "{}")])
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertTrue(result["last_ids_persisted"])
        env = self._session_env()
        self.assertEqual(env["KINOA_LAST_PLAYER_ID"], "p-1")
        self.assertEqual(env["KINOA_LAST_SESSION_ID"], result["session_id"])

    def test_failure_does_not_persist_phantom_ids(self):
        # Decision pinned (not accident): a 401/failed open must not leave
        # KINOA_LAST_* values that Phases 4/5 would then trust as a real session.
        code, result = self._run_main(["--player-id", "p-1"], [(401, "")])
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertFalse(result["last_ids_persisted"])
        env = self._session_env()
        self.assertNotIn("KINOA_LAST_PLAYER_ID", env)
        self.assertNotIn("KINOA_LAST_SESSION_ID", env)

    def test_network_error_does_not_persist(self):
        code, result = self._run_main(["--player-id", "p-1"], [(0, "URLError: timed out")])
        self.assertEqual(code, 1)
        self.assertFalse(result["last_ids_persisted"])
        self.assertNotIn("KINOA_LAST_PLAYER_ID", self._session_env())

    def test_save_leaves_no_tmp_file(self):
        self._run_main(["--player-id", "p-1"], [(200, "{}")])
        self.assertFalse(os.path.exists(self.mod.SESSION_ENV_PATH + ".tmp"))

    def test_game_secret_header_and_body_shape(self):
        self._run_main(["--player-id", "p-1", "--level", "7", "--field", "vip=1"], [(200, "{}")])
        req = self.requests[0]
        self.assertEqual(req["headers"]["game"], "FAKE_SECRET")
        self.assertNotIn("Authorization", req["headers"])  # public surface: no bearer, ever
        state = req["body"]["player_state"]
        self.assertEqual(state["player_identifiers"]["player_id"], "p-1")
        self.assertEqual(state["level"], 7)
        self.assertEqual(state["vip"], "1")

    def test_missing_credentials_exits_2(self):
        del os.environ["KINOA_GAME_SECRET"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                self.mod.main(["--player-id", "p-1"])
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(json.loads(out.getvalue())["error"], "missing_credentials")


if __name__ == "__main__":
    unittest.main()
