"""Offline unit tests for skills/kinoa-init/kinoa_init.py.

No network, no real ~/.kinoa — `_request` is monkeypatched and the session.env
paths are redirected into a temp dir. Run from the repo root:

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
SCRIPT_PATH = os.path.join(REPO_ROOT, "skills", "kinoa-init", "kinoa_init.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("kinoa_init_under_test", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class KinoaInitTests(unittest.TestCase):
    def setUp(self):
        # Redirect HOME BEFORE loading the module: the import-time expanduser("~/.kinoa")
        # must not resolve to a real session.env. Snapshot/restore os.environ too.
        self._saved_environ = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(self._saved_environ)))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["USERPROFILE"] = self.tmp.name
        os.environ["HOME"] = self.tmp.name
        self.mod = _load_module()
        self.mod.SESSION_DIR = self.tmp.name
        self.mod.SESSION_ENV_PATH = os.path.join(self.tmp.name, "session.env")
        self.requests = []

    def _mock_request(self, responses):
        """responses: list of (status, raw_body) consumed in call order."""
        queue = list(responses)

        def fake_request(method, url, headers=None, body=None):
            self.requests.append({"method": method, "url": url, "headers": headers, "body": body})
            return queue.pop(0)

        self.mod._request = fake_request

    def _run_main(self, argv, responses):
        self._mock_request(responses)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(argv)
        return code, json.loads(out.getvalue())

    def _read_session_env(self):
        env = {}
        with open(self.mod.SESSION_ENV_PATH, "r") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                env[k] = v
        return env

    BASE_ARGS = ["--game-id", "11111111-1111-1111-1111-111111111111",
                 "--game-secret", "FAKE_SECRET", "--bearer-token", "FAKE_TOKEN"]

    def test_default_expected_type_is_api(self):
        code, result = self._run_main(
            self.BASE_ARGS,
            [(200, json.dumps({"integration_type": "API"}))],
        )
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["expected_integration_type"], "API")
        self.assertEqual(self._read_session_env()["KINOA_INTEGRATION_TYPE"], "API")

    def test_sdk_mode_validates_sdk(self):
        code, result = self._run_main(
            self.BASE_ARGS + ["--integration-type", "SDK"],
            [(200, json.dumps({"integration_type": "SDK"}))],
        )
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["expected_integration_type"], "SDK")
        self.assertEqual(self._read_session_env()["KINOA_INTEGRATION_TYPE"], "SDK")

    def test_sdk_mode_flags_wrong_type_without_fix(self):
        code, result = self._run_main(
            self.BASE_ARGS + ["--integration-type", "SDK"],
            [(200, json.dumps({"integration_type": "API"}))],
        )
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "wrong_integration_type")
        # No mutation without --fix-integration-type: single GET only.
        self.assertEqual([r["method"] for r in self.requests], ["GET"])

    def test_fix_posts_expected_type_sdk(self):
        code, result = self._run_main(
            self.BASE_ARGS + ["--integration-type", "SDK", "--fix-integration-type"],
            [
                (200, json.dumps({"integration_type": "API"})),   # initial validate
                (200, json.dumps({})),                            # POST fix
                (200, json.dumps({"integration_type": "SDK"})),   # re-validate
            ],
        )
        self.assertEqual(code, 0)
        self.assertTrue(result["fix_attempted"])
        self.assertTrue(result["fix_succeeded"])
        post = self.requests[1]
        self.assertEqual(post["method"], "POST")
        self.assertEqual(post["body"], {"integrationType": "SDK"})

    def test_fix_posts_expected_type_api_legacy_flow(self):
        code, result = self._run_main(
            self.BASE_ARGS + ["--fix-integration-type"],
            [
                (200, json.dumps({"integration_type": "SDK"})),
                (200, json.dumps({})),
                (200, json.dumps({"integration_type": "API"})),
            ],
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[1]["body"], {"integrationType": "API"})
        # The legacy bare-flag form still works but is loudly flagged: a defaulted flip
        # direction in an SDK flow papers over the mismatch instead of fixing it.
        self.assertTrue(result["integration_type_defaulted"])
        self.assertIn("--integration-type SDK", result["warning"])

    def test_invalid_integration_type_rejected_exit_2(self):
        # argparse choices gate: a bad/lowercase value fails closed (exit 2), no HTTP call.
        import sys
        for bad in ("sdk", "FOO"):
            old_argv = sys.argv
            sys.argv = ["kinoa_init.py"] + self.BASE_ARGS + ["--integration-type", bad]
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as ctx:
                        self.mod.main(self.BASE_ARGS + ["--integration-type", bad])
                self.assertEqual(ctx.exception.code, 2)
            finally:
                sys.argv = old_argv

    def test_fix_posts_api_explicit_no_warning(self):
        # The documented canonical API-mode fix: explicit --integration-type API emits no
        # defaulted-warning keys (symmetric to the SDK direction).
        code, result = self._run_main(
            self.BASE_ARGS + ["--integration-type", "API", "--fix-integration-type"],
            [
                (200, json.dumps({"integration_type": "SDK"})),
                (200, json.dumps({})),
                (200, json.dumps({"integration_type": "API"})),
            ],
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.requests[1]["body"], {"integrationType": "API"})
        self.assertNotIn("integration_type_defaulted", result)
        self.assertNotIn("warning", result)

    def test_fix_post_failure_reports_not_succeeded_and_skips_recheck(self):
        code, result = self._run_main(
            self.BASE_ARGS + ["--integration-type", "SDK", "--fix-integration-type"],
            [
                (200, json.dumps({"integration_type": "API"})),  # initial validate
                (500, ""),                                       # POST fix fails
            ],
        )
        self.assertEqual(code, 1)
        self.assertTrue(result["fix_attempted"])
        self.assertFalse(result["fix_succeeded"])
        self.assertEqual(result["fix_http_status"], 500)
        # No recheck GET after a failed POST: exactly two calls (GET, POST).
        self.assertEqual([r["method"] for r in self.requests], ["GET", "POST"])

    def test_failed_sdk_alignment_still_persists_sdk_in_session_env(self):
        # Decision pinned (not accident): session.env carries the EXPECTED type even when
        # validation fails, so a later re-run resumes against the intended type.
        code, result = self._run_main(
            self.BASE_ARGS + ["--integration-type", "SDK"],
            [(200, json.dumps({"integration_type": "API"}))],
        )
        self.assertEqual(code, 1)
        self.assertEqual(self._read_session_env()["KINOA_INTEGRATION_TYPE"], "SDK")

    def test_fix_with_explicit_type_emits_no_defaulted_warning(self):
        code, result = self._run_main(
            self.BASE_ARGS + ["--integration-type", "SDK", "--fix-integration-type"],
            [
                (200, json.dumps({"integration_type": "API"})),
                (200, json.dumps({})),
                (200, json.dumps({"integration_type": "SDK"})),
            ],
        )
        self.assertEqual(code, 0)
        self.assertNotIn("integration_type_defaulted", result)
        self.assertNotIn("warning", result)

    def test_unauthorized_reason(self):
        code, result = self._run_main(self.BASE_ARGS, [(401, "")])
        self.assertEqual(code, 1)
        self.assertEqual(result["reason"], "unauthorized")

    def test_admin_headers_present_on_validate(self):
        self._run_main(self.BASE_ARGS, [(200, json.dumps({"integration_type": "API"}))])
        headers = self.requests[0]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer FAKE_TOKEN")
        self.assertEqual(headers["Game"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(headers["Game-Id"], "11111111-1111-1111-1111-111111111111")


if __name__ == "__main__":
    unittest.main()
