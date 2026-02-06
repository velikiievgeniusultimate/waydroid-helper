import importlib.util
import math
import pathlib
import unittest


_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "waydroid_helper"
    / "controller"
    / "widgets"
    / "components"
    / "skill_casting_v2.py"
)
_MODULE_NAME = "skill_casting_v2"
_SPEC = importlib.util.spec_from_file_location(_MODULE_NAME, _MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load module at {_MODULE_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
import sys
sys.modules[_MODULE_NAME] = _MODULE
_SPEC.loader.exec_module(_MODULE)

SkillCastingCalibration = _MODULE.SkillCastingCalibration
map_pointer_to_widget_target = _MODULE.map_pointer_to_widget_target


class SkillCastingV2MappingTests(unittest.TestCase):
    def test_vertical_ratio_changes_mapping(self) -> None:
        widget_center_x = 0.0
        widget_center_y = 0.0
        widget_radius = 50.0
        mouse_x = 0.0
        mouse_y = 100.0

        default_ratio = SkillCastingCalibration(
            center_x=0.0,
            center_y=0.0,
            radius=100.0,
            vertical_scale_ratio=1.0,
        )
        boosted_ratio = SkillCastingCalibration(
            center_x=0.0,
            center_y=0.0,
            radius=100.0,
            vertical_scale_ratio=2.0,
        )

        default_target = map_pointer_to_widget_target(
            mouse_x,
            mouse_y,
            default_ratio,
            widget_center_x,
            widget_center_y,
            widget_radius,
        )
        boosted_target = map_pointer_to_widget_target(
            mouse_x,
            mouse_y,
            boosted_ratio,
            widget_center_x,
            widget_center_y,
            widget_radius,
        )

        self.assertAlmostEqual(default_target[0], 0.0)
        self.assertAlmostEqual(default_target[1], 50.0)
        self.assertAlmostEqual(boosted_target[0], 0.0)
        self.assertTrue(boosted_target[1] < default_target[1])
        self.assertFalse(math.isclose(default_target[1], boosted_target[1]))


if __name__ == "__main__":
    unittest.main()
