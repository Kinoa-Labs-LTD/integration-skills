# tests/test_inapp_prefab_fixtures.py
"""Fixture sanity for kinoa-inapp-template-to-prefab. Offline."""
import json
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(REPO, "plugin", "skills", "kinoa-inapp-template-to-prefab")
FIX = os.path.join(SKILL, "evals", "fixtures", "one-cta")


class TestFixtures(unittest.TestCase):
    def test_template_record_has_all_four_buckets(self):
        with open(os.path.join(FIX, "template_one_cta.json"), encoding="utf-8") as fh:
            rec = json.load(fh)
        self.assertEqual(rec["key"], "one_cta_offer")
        for bucket in ("images", "buttons", "texts", "customs"):
            self.assertIn(bucket, rec)
        self.assertEqual({b["key"] for b in rec["buttons"]}, {"close_button", "cta_button"})

    def test_build_result_elements_carry_bboxes(self):
        with open(os.path.join(FIX, "build_result_one_cta.json"), encoding="utf-8") as fh:
            br = json.load(fh)
        keys = {e["key"] for e in br["report"]["elements"]}
        self.assertIn("header", keys)
        self.assertTrue(all("bbox" in e for e in br["report"]["elements"]))
        self.assertEqual({c["role"] for c in br["report"]["client_rendered"]},
                         {"resource_area", "price_before_sale", "timer"})

    def test_frontmatter(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as fh:
            head = fh.read(2000)   # the description paragraph is long
        self.assertTrue(head.startswith("---\nname: kinoa-inapp-template-to-prefab\n"))
        self.assertIn("allowed-tools:", head)
        self.assertIn("ToolSearch", head)

    def test_prefab_fixture_is_legacy_text_with_font(self):
        with open(os.path.join(FIX, "OfferPopup.prefab"), encoding="utf-8") as fh:
            yaml = fh.read()
        self.assertIn("guid: 5f7201a12d95ffc409449d95f23cf332", yaml)   # UnityEngine.UI.Text
        self.assertIn("m_Font: {fileID: 12800000, guid: e7a63bee4e93df34ca0dd3548b336621", yaml)


class TestSkillDoc(unittest.TestCase):
    def test_phases_commands_and_rules_present(self):
        with open(os.path.join(SKILL, "SKILL.md"), encoding="utf-8") as fh:
            doc = fh.read()
        for phase in ("## Phase 1 — Preflight", "## Phase 2 — Reference popups", "## Phase 3 — Layout source",
                      "## Phase 4 — Plan", "## Phase 5 — Generate", "## Phase 6 — Build in Unity", "## Phase 7 — Hand-off"):
            self.assertIn(phase, doc)
        for cmd in ("inapp_prefab_plan.py\" probe-style", "inapp_prefab_plan.py\" plan", "inapp_prefab_plan.py\" generate",
                    "--layout-artifact", "layout-artifact.md", "kinoa_init.py\" show",
                    "kinoa_dashboard_inapp_template.py\" get"):
            self.assertIn(cmd, doc)
        self.assertIn("Tools/Kinoa/In-Apps/Build Prefabs From Plans", doc)
        self.assertIn("references/unity-mcp-capabilities.md", doc)
        self.assertIn("TODO(kinoa-prefab)", doc)
        self.assertIn("never write", doc.lower())
        self.assertIn("Never `cat ~/.kinoa/session.env`", doc)   # the doc forbids it, never instructs it
        for ref in ("prefab-plan-schema.md", "generated-code-contract.md"):
            self.assertTrue(os.path.isfile(os.path.join(SKILL, "references", ref)))


class TestRepoWiring(unittest.TestCase):
    def _read(self, *parts):
        with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
            return fh.read()

    def test_evals_exist_and_cover_the_gates(self):
        with open(os.path.join(SKILL, "evals", "evals.json"), encoding="utf-8") as fh:
            evals = json.load(fh)
        self.assertEqual(evals["skill_name"], "kinoa-inapp-template-to-prefab")
        names = {e["name"] for e in evals["evals"]}
        for needed in ("stops-without-unity-mcp", "never-writes-image-download", "prefers-layout-recognition-output",
                       "no-trigger-for-template-creation"):
            self.assertIn(needed, names)

    def test_claude_md_changelog_and_handoffs(self):
        self.assertIn("kinoa-inapp-template-to-prefab", self._read("CLAUDE.md"))
        self.assertIn("kinoa-inapp-template-to-prefab", self._read("CHANGELOG.md"))
        self.assertIn("kinoa-inapp-template-to-prefab", self._read("plugin", "skills", "kinoa-inapp-template-from-image", "SKILL.md"))
        self.assertIn("Unity prefab", self._read("docs", "inapp-template-generation-guide.md"))
