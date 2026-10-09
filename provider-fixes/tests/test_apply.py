"""The overlay applied on the pristine pinned packages."""
import unittest


class AppliedTest(unittest.TestCase):
    def test_overlay_imports(self):
        import openbb_core.app.command_runner  # noqa: F401
