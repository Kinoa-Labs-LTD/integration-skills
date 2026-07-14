"""Drift guards for the deliberately duplicated helper boilerplate.

The repo duplicates `_load_session_env` / `_save_session_env` / `_request`
across the self-contained helpers instead of sharing a module. That policy is
only safe if the copies cannot silently diverge — a hang-risk timeout fix
landing in one copy and not the others is exactly the failure this file pins.

Scope notes:
- kinoa_webhook.py (and its byte-identical SDK twin, guarded by
  tests/test_kinoa_webhook.py) is a deliberate variant — excluded from the
  textual-identity checks here, but still covered by the urlopen-timeout scan.
- kinoa_dashboard_feature_settings.py's `_request` legitimately differs (it
  carries a content_type parameter for JSON-patch calls) — excluded from
  `_request` identity, still covered by the timeout scan.

    python -m unittest discover tests -v
"""

import ast
import glob
import os
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")

ALL_PY = sorted(
    glob.glob(os.path.join(SKILLS_DIR, "**", "*.py"), recursive=True)
)

# Deliberate variants excluded from textual identity (see module docstring).
WEBHOOK_BASENAME = "kinoa_webhook.py"
REQUEST_VARIANT_BASENAMES = {"kinoa_dashboard_feature_settings.py", WEBHOOK_BASENAME}


def _function_sources(path):
    """Map of top-level function name -> exact source segment."""
    with open(path, "r") as f:
        source = f.read()
    tree = ast.parse(source)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out[node.name] = ast.get_source_segment(source, node)
    return out, source, tree


class UrlopenTimeoutTests(unittest.TestCase):
    def test_every_urlopen_passes_a_timeout(self):
        """A bare urlopen hangs forever on a stalled-but-open connection; the
        harness kill then violates the one-JSON-object output contract."""
        offenders = []
        for path in ALL_PY:
            _, source, tree = _function_sources(path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name != "urlopen":
                    continue
                timeout_kw = next((kw for kw in node.keywords if kw.arg == "timeout"), None)
                # timeout=None disables the timeout just as surely as omitting it.
                is_none = timeout_kw is not None and isinstance(timeout_kw.value, ast.Constant) \
                    and timeout_kw.value.value is None
                if timeout_kw is None or is_none:
                    offenders.append(f"{os.path.relpath(path, REPO_ROOT)}:{node.lineno}")
        self.assertEqual(
            offenders, [],
            "urlopen call(s) without timeout= — propagate the timeout to every copy: "
            + ", ".join(offenders),
        )


class BoilerplateIdentityTests(unittest.TestCase):
    def _collect(self, func_name, exclude_basenames=()):
        found = {}
        for path in ALL_PY:
            if os.path.basename(path) in exclude_basenames:
                continue
            funcs, _, _ = _function_sources(path)
            if func_name in funcs:
                found[os.path.relpath(path, REPO_ROOT)] = funcs[func_name]
        return found

    def _assert_identical(self, found, func_name):
        self.assertGreater(len(found), 1, f"expected {func_name} in more than one helper")
        variants = {}
        for path, src in found.items():
            variants.setdefault(src, []).append(path)
        self.assertEqual(
            len(variants), 1,
            f"{func_name} copies diverged — re-copy after edits. Variants:\n"
            + "\n---\n".join(f"{paths}" for paths in variants.values()),
        )

    def test_load_session_env_copies_identical(self):
        found = self._collect("_load_session_env", exclude_basenames={WEBHOOK_BASENAME})
        self._assert_identical(found, "_load_session_env")

    def test_save_session_env_copies_identical(self):
        found = self._collect("_save_session_env", exclude_basenames={WEBHOOK_BASENAME})
        self._assert_identical(found, "_save_session_env")

    def test_request_copies_identical(self):
        found = self._collect("_request", exclude_basenames=REQUEST_VARIANT_BASENAMES)
        self._assert_identical(found, "_request")

    def test_parse_json_copies_identical(self):
        found = self._collect("_parse_json", exclude_basenames={WEBHOOK_BASENAME})
        self._assert_identical(found, "_parse_json")


if __name__ == "__main__":
    unittest.main()
