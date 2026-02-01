import gi
import unittest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GLib, Gtk

from scripts.demo_floating_settings_panel import DemoWindow


class DemoSettingsPanelTest(unittest.TestCase):
    def setUp(self):
        self.app = Gtk.Application()
        self.window = DemoWindow(self.app)
        self.window.present()
        self._drain_events()

    def tearDown(self):
        if self.window:
            self.window.close()
        self._drain_events()

    def _drain_events(self):
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def test_open_and_close_panel(self):
        self.window.open_settings_panel()
        self._drain_events()
        self.assertIsNotNone(self.window.active_settings_panel)
        self.window.mapping_mode = True
        self.window.close_settings_panel()
        self._drain_events()
        self.assertIsNone(self.window.active_settings_panel)


if __name__ == "__main__":
    unittest.main()
