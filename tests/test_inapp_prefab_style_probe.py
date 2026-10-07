"""Offline tests for probe-style (Unity prefab YAML heuristics)."""
import importlib.util
import json
import os
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO, "plugin", "skills", "kinoa-inapp-template-to-prefab")
HELPER = os.path.join(SKILL, "inapp_prefab_plan.py")
FIX = os.path.join(SKILL, "evals", "fixtures", "one-cta")

_spec = importlib.util.spec_from_file_location("inapp_prefab_plan", HELPER)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class TestProbeStyle(unittest.TestCase):
    def test_detects_legacy_text_font_root_size_close_sprite_and_base_class(self):
        probe = mod.probe_style([os.path.join(FIX, "OfferPopup.prefab")], FIX)
        self.assertEqual(probe["text_system"], "legacy")
        self.assertEqual(probe["font_guid"], "e7a63bee4e93df34ca0dd3548b336621")
        self.assertIsNone(probe["tmp_font_guid"])
        self.assertEqual(probe["root_size"], [900.0, 1400.0])
        self.assertEqual(probe["close_sprite_guid"], "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        self.assertEqual(probe["base_classes"], ["OfferPopup"])
        self.assertEqual(probe["prefabs"][0]["name"], "OfferPopup")

    def test_tmp_wins_when_present(self):
        yaml = ("--- !u!114 &1\nMonoBehaviour:\n  m_Script: {fileID: 11500000, guid: "
                + mod.TMP_TEXT_GUID + ", type: 3}\n  m_fontAsset: {fileID: 11400000, guid: "
                "cccccccccccccccccccccccccccccccc, type: 2}\n")
        path = os.path.join(self._tmp(), "Tmp.prefab")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(yaml)
        probe = mod.probe_style([path], self._tmp())
        self.assertEqual(probe["text_system"], "tmp")
        self.assertEqual(probe["tmp_font_guid"], "cccccccccccccccccccccccccccccccc")

    def test_missing_prefab_is_a_warning_not_a_crash(self):
        probe = mod.probe_style([os.path.join(FIX, "Nope.prefab")], FIX)
        self.assertEqual(probe["text_system"], "unknown")
        self.assertTrue(any("Nope.prefab" in w for w in probe["warnings"]))

    def test_cli_probe_style_prints_json(self):
        out = subprocess.run([sys.executable, HELPER, "probe-style", "--prefab",
                              os.path.join(FIX, "OfferPopup.prefab"), "--assets-root", FIX],
                             capture_output=True, text=True, check=True).stdout
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["style"]["text_system"], "legacy")

    def test_unresolved_root_script_guid_not_in_base_classes(self):
        # Prefab with root having both OfferPopup (resolved) and unknown script (unresolved)
        # Create OfferPopup.cs.meta so it resolves
        tmpdir = self._tmp()
        meta_path = os.path.join(tmpdir, "OfferPopup.cs.meta")
        with open(meta_path, "w", encoding="utf-8") as fh:
            fh.write("guid: e1e7a63bee4e93df34ca0dd3548b33662\n")
        # Prefab with root GameObject having two MonoBehaviours: OfferPopup and unknown script
        yaml = ("--- !u!1 &1\nGameObject:\n  m_Name: Root\n"
                "--- !u!224 &2\nRectTransform:\n  m_GameObject: {fileID: 1}\n"
                "  m_Father: {fileID: 0}\n  m_SizeDelta: {x: 100, y: 200}\n"
                "--- !u!114 &3\nMonoBehaviour:\n  m_GameObject: {fileID: 1}\n"
                "  m_Script: {fileID: 11500000, guid: e1e7a63bee4e93df34ca0dd3548b33662, type: 3}\n"
                "--- !u!114 &4\nMonoBehaviour:\n  m_GameObject: {fileID: 1}\n"
                "  m_Script: {fileID: 11500000, guid: ffffffffffffffffffffffffffffffff, type: 3}\n")
        path = os.path.join(tmpdir, "WithUnknown.prefab")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(yaml)
        probe = mod.probe_style([path], tmpdir)
        self.assertEqual(probe["base_classes"], ["OfferPopup"])
        self.assertTrue(any("ffffffffffffffffffffffffffffffff" in w for w in probe["warnings"]))

    def test_zero_size_blocked_by_nonzero_size(self):
        # Create stretch-anchored prefab (size [0, 0])
        yaml_zero = ("--- !u!1 &1\nGameObject:\n  m_Name: Root\n"
                     "--- !u!224 &2\nRectTransform:\n  m_GameObject: {fileID: 1}\n"
                     "  m_Father: {fileID: 0}\n  m_SizeDelta: {x: 0, y: 0}\n")
        tmpdir = self._tmp()
        path_zero = os.path.join(tmpdir, "StretchRoot.prefab")
        with open(path_zero, "w", encoding="utf-8") as fh:
            fh.write(yaml_zero)
        # Probe [zero-size, OfferPopup] in that order; aggregation should skip zero
        probe = mod.probe_style([path_zero, os.path.join(FIX, "OfferPopup.prefab")], FIX)
        self.assertEqual(probe["root_size"], [900.0, 1400.0])

    def _tmp(self):
        import tempfile
        if not hasattr(self, "_d"):
            self._d = tempfile.mkdtemp()
        return self._d
