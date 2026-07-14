"""Offline unit tests for skills/kinoa-csv-schema-infer/kinoa_csv_schema_infer.py.

Pure parser — no network, no mocks needed. The inference ladder's ORDER is the
spec (first match wins), so these tests pin both the individual type rules and
the precedence between them.

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
SCRIPT_PATH = os.path.join(REPO_ROOT, "skills", "kinoa-csv-schema-infer", "kinoa_csv_schema_infer.py")


def _load_module():
    spec = importlib.util.spec_from_file_location("kinoa_csv_schema_infer_under_test", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class InferTypeLadderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def test_boolean(self):
        self.assertEqual(self.mod.infer_type(["true", "FALSE", "yes", "No"]), "boolean")

    def test_integer_within_int32(self):
        self.assertEqual(self.mod.infer_type(["1", "-5", "2147483647"]), "integer")

    def test_long_when_outside_int32(self):
        self.assertEqual(self.mod.infer_type(["1", "2147483648"]), "long")

    def test_number_for_fractional(self):
        self.assertEqual(self.mod.infer_type(["1.5", "2"]), "number")

    def test_version_beats_number_ladder_order(self):
        # "1.0.0" is not a float; version is checked before number by design.
        self.assertEqual(self.mod.infer_type(["1.0.0", "2.13.4"]), "version")

    def test_two_part_version_is_not_version(self):
        # Needs >= two dots; "1.0" is a plain number.
        self.assertEqual(self.mod.infer_type(["1.0", "2.1"]), "number")

    def test_date_iso_variants(self):
        self.assertEqual(self.mod.infer_type(["2026-07-13", "2026-01-02T10:30", "2026-01-02 10:30:00"]), "date")

    def test_object_json(self):
        self.assertEqual(self.mod.infer_type(['{"a":1}', "[1,2]"]), "object")

    def test_long_string_over_threshold(self):
        self.assertEqual(self.mod.infer_type(["x" * 256]), "long_string")

    def test_string_fallback_and_empty_column(self):
        self.assertEqual(self.mod.infer_type(["hello", "world"]), "string")
        self.assertEqual(self.mod.infer_type([]), "string")
        self.assertEqual(self.mod.infer_type(["", "  "]), "string")

    def test_mixed_types_fall_through_to_string(self):
        self.assertEqual(self.mod.infer_type(["1.0.0", "2"]), "string")

    def test_bool_tokens_are_not_numbers(self):
        # "1"/"0" are integers, not booleans — BOOL_TOKENS is words only.
        self.assertEqual(self.mod.infer_type(["1", "0"]), "integer")


class CmdInferTests(unittest.TestCase):
    def setUp(self):
        self.mod = _load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write_csv(self, text):
        path = os.path.join(self.tmp.name, "input.csv")
        with open(path, "w") as f:
            f.write(text)
        return path

    def _run(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.mod.main(argv)
        return code, json.loads(out.getvalue())

    def test_full_emit_infers_and_reviews(self):
        path = self._write_csv(
            "sku,price,active,tier\n"
            "A-1,9.99,true,gold\n"
            "B-2,19.5,false,silver\n"
            "C-3,5.0,true,gold\n"
            "D-4,7.25,false,silver\n"
        )
        code, result = self._run(["infer", "--csv", path, "--name", "Shop"])
        self.assertEqual(code, 0)
        types = {f["name"]: f["type"] for f in result["fields"]}
        self.assertEqual(types, {"sku": "string", "price": "number", "active": "boolean", "tier": "string"})
        self.assertEqual(result["schema_body"]["name"], "Shop")
        self.assertEqual(result["schema_body"]["versions"][0]["version"], "1")
        # tier: 2 distinct over 4 rows → enumeration candidate flagged, type stays string
        tier_review = next(r for r in result["review"] if r["column"] == "tier")
        self.assertIn("enumeration candidate", tier_review["note"])

    def test_type_override_and_required_policy(self):
        path = self._write_csv("col,maybe\n1,a\n2,\n")
        code, result = self._run(["infer", "--csv", path, "--type", "col=enumeration"])
        self.assertEqual(code, 0)
        fields = {f["name"]: f for f in result["fields"]}
        self.assertEqual(fields["col"]["type"], "enumeration")
        # nonempty policy (default): col has no blanks → required; maybe has a blank → optional
        self.assertTrue(fields["col"]["isRequired"])
        self.assertFalse(fields["maybe"]["isRequired"])

    def test_invalid_type_override_exits_2(self):
        path = self._write_csv("a\n1\n")
        code, result = self._run(["infer", "--csv", path, "--type", "a=datetime"])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "invalid_type_override")

    def test_missing_file_and_empty_csv(self):
        code, result = self._run(["infer", "--csv", os.path.join(self.tmp.name, "nope.csv")])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "file_not_found")
        empty = self._write_csv("")
        code, result = self._run(["infer", "--csv", empty])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "empty_csv")

    def test_ragged_rows_treated_as_blank_cells(self):
        path = self._write_csv("a,b\n1,x\n2\n")
        code, result = self._run(["infer", "--csv", path])
        self.assertEqual(code, 0)
        fields = {f["name"]: f for f in result["fields"]}
        self.assertEqual(fields["b"]["type"], "string")
        self.assertFalse(fields["b"]["isRequired"])  # missing cell counts as blank

    def test_emit_body_is_pipeable_schema_dto(self):
        path = self._write_csv("a\n1\n")
        code, result = self._run(["infer", "--csv", path, "--emit", "body"])
        self.assertEqual(code, 0)
        self.assertIn("versions", result)
        self.assertEqual(result["versions"][0]["tableFields"][0]["name"], "a")


if __name__ == "__main__":
    unittest.main()
