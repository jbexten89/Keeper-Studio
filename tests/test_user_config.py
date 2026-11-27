import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from keeperstudio import engine, paths

ROOT = Path(__file__).resolve().parent.parent


class UserConfigTest(unittest.TestCase):
    """Your framing settings survive a new build of the app."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Path(self.tmp.name) / "app"
        self.app.mkdir()
        (self.app / "config.yaml").write_text((ROOT / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        self.p = [mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(Path(self.tmp.name) / "data"), "LOCALAPPDATA": str(Path(self.tmp.name) / "data")}),
                  mock.patch.object(paths, "app_dir", lambda: self.app)]
        for x in self.p:
            x.start()
        paths._user_cfg["seen"] = None

    def tearDown(self):
        for x in self.p:
            x.stop()
        paths._user_cfg["seen"] = None
        engine._extra_cache.clear()
        self.tmp.cleanup()

    def val(self, key):
        return next(t["value"] for t in engine.read_tunables() if t["key"] == key)

    def test_settings_live_in_the_user_folder_and_point_at_the_app_models(self):
        p = paths.config_path()
        self.assertEqual(p.parent, paths.data_dir())
        text = p.read_text(encoding="utf-8")
        self.assertIn(str((self.app / "models").resolve().as_posix()), text)
        engine.load_config(p)  # the engine can read it

    def test_fine_tune_survives_a_new_build(self):
        engine.write_tunables({"landscape.visible_fraction": 0.8})
        self.assertAlmostEqual(self.val("visible_fraction"), 0.8)
        # a new build: the app's config.yaml is replaced
        (self.app / "config.yaml").write_text((ROOT / "config.yaml").read_text(encoding="utf-8") + "\n# new build\n", encoding="utf-8")
        paths._user_cfg["seen"] = None
        engine._extra_cache.clear()
        self.assertIn("# new build", paths.config_path().read_text(encoding="utf-8"))
        self.assertAlmostEqual(self.val("visible_fraction"), 0.8)


if __name__ == "__main__":
    unittest.main()
