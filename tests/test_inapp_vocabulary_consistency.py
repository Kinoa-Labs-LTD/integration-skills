"""Drift guard for the in-app template vocabulary.

`generate_confirm_page.py` hand-mirrors the constants from
`inapp_template_build.py` because helpers in this repo never import each
other. That duplication is safe only while something checks it — this file is
that something, in the same spirit as `test_boilerplate_consistency.py`.

If this fails, the confirmation page is offering the developer a vocabulary the
builder will not accept. Re-copy the constant, do not relax the test.
"""

import importlib.util
import os
import unittest

_SKILL = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "plugin",
    "skills",
    "kinoa-inapp-template-from-image",
)


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_SKILL, filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_mod = _load("inapp_template_build", "inapp_template_build.py")
page_mod = _load("generate_confirm_page", "generate_confirm_page.py")


class TestVocabularyMirrors(unittest.TestCase):
    def test_click_actions(self):
        self.assertEqual(list(page_mod.CLICK_ACTIONS), list(build_mod.CLICK_ACTIONS))

    def test_item_bearing_actions(self):
        self.assertEqual(list(page_mod.ITEM_BEARING_ACTIONS), list(build_mod.ITEM_BEARING_ACTIONS))

    def test_kinds(self):
        self.assertEqual(list(page_mod.KINDS), list(build_mod.KINDS))

    def test_feature_types(self):
        self.assertEqual(list(page_mod.FEATURE_TYPES), list(build_mod.FEATURE_TYPES))

    def test_buckets(self):
        self.assertEqual(list(page_mod.BUCKETS), list(build_mod.BUCKETS))

    def test_bucket_labels_cover_every_bucket(self):
        self.assertEqual(set(page_mod.BUCKET_LABELS), set(build_mod.BUCKETS))

    def test_invented_defaults_stay_gone(self):
        # Operator decision (2026-08-31): a field is either on the page or
        # required by the API — the builder must NOT resurrect these constants.
        for name in ("DEFAULT_IMAGE_SIZE", "DEFAULT_BUTTON_BG", "DEFAULT_TEXT_LIMIT"):
            self.assertFalse(hasattr(build_mod, name), name)
            # the confirm page mirrored them, so it must not resurrect them either
            self.assertFalse(hasattr(page_mod, name), "page_mod." + name)

    def test_key_patterns(self):
        self.assertEqual(page_mod.ELEMENT_KEY_RE, build_mod.KEY_RE.pattern)
        self.assertEqual(page_mod.TEMPLATE_KEY_RE, build_mod.TEMPLATE_KEY_RE.pattern)


class TestFeatureSeedsMirror(unittest.TestCase):
    """The page seeds a feature block when the developer switches featureType.
    Those seeds must be what the builder would have produced."""

    @staticmethod
    def _public(block):
        return {k: v for k, v in block.items() if not k.startswith("_")}

    def test_mission_seed(self):
        self.assertEqual(page_mod.MISSION_DEFAULTS, self._public(build_mod._mission_feature({})))

    def test_milestone_seed(self):
        self.assertEqual(page_mod.MILESTONE_DEFAULTS, self._public(build_mod._milestone_feature({})))


if __name__ == "__main__":
    unittest.main()
