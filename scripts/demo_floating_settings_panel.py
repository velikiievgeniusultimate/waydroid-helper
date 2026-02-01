#!/usr/bin/env python3
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gettext import gettext as _

from gi.repository import Adw, GLib, Gtk, Pango


class DemoWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title=_("Settings Panel Demo"))
        self.set_default_size(900, 600)
        self.mapping_mode = False
        self.settings_panel_state: dict[str, int] = {}
        self.active_settings_panel: Gtk.Widget | None = None

        overlay = Gtk.Overlay.new()
        self.set_child(overlay)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.set_margin_top(12)
        main_box.set_margin_start(12)
        main_box.set_margin_end(12)
        main_box.set_margin_bottom(12)

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        open_button = Gtk.Button(label=_("Open Settings (Edit Mode)"))
        open_button.connect("clicked", self._on_open_clicked)
        button_row.append(open_button)

        self.mode_switch = Gtk.Switch()
        self.mode_switch.connect("state-set", self._on_mode_toggle)
        button_row.append(Gtk.Label(label=_("Mapping Mode")))
        button_row.append(self.mode_switch)

        main_box.append(button_row)
        main_box.append(Gtk.Label(label=_("Drag the floating panel by its header.")))

        overlay.set_child(main_box)

        self.settings_overlay = Gtk.Fixed.new()
        self.settings_overlay.set_hexpand(True)
        self.settings_overlay.set_vexpand(True)
        overlay.add_overlay(self.settings_overlay)

    def _on_mode_toggle(self, _switch, state):
        self.mapping_mode = state
        if self.mapping_mode:
            self.close_settings_panel()
        return False

    def _on_open_clicked(self, _button):
        if self.mapping_mode:
            return
        self.open_settings_panel()

    def open_settings_panel(self):
        if self.active_settings_panel is not None:
            self.close_settings_panel()

        panel_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel_container.set_can_target(True)
        panel_container.set_focusable(True)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.set_margin_top(8)
        header.set_margin_bottom(4)
        header.set_margin_start(12)
        header.set_margin_end(12)
        header.set_hexpand(True)

        title_label = Gtk.Label()
        title_label.set_markup("<b>Demo Settings</b>")
        title_label.set_halign(Gtk.Align.START)
        title_label.set_hexpand(True)
        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        header.append(title_label)

        close_button = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_button.add_css_class("flat")
        close_button.connect("clicked", lambda _btn: self.close_settings_panel())
        header.append(close_button)

        panel_container.append(header)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        content_box.set_margin_start(12)
        content_box.set_margin_end(12)
        content_box.set_margin_bottom(12)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(360)
        scroller.set_max_content_height(720)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for index in range(20):
            content.append(Gtk.Label(label=f"Demo setting row {index + 1}"))
        scroller.set_child(content)
        content_box.append(scroller)

        panel_container.append(content_box)

        panel_width = max(self.settings_panel_state.get("width", 480), 480)
        panel_height = self.settings_panel_state.get("height", -1)
        panel_container.set_size_request(panel_width, panel_height)

        drag_controller = Gtk.GestureDrag.new()
        drag_state: dict[str, float] = {"start_x": 0.0, "start_y": 0.0}

        def on_drag_begin(_controller, _x, _y):
            drag_state["start_x"] = float(self.settings_panel_state.get("x", 0))
            drag_state["start_y"] = float(self.settings_panel_state.get("y", 0))

        def on_drag_update(_controller, offset_x, offset_y):
            target_x = int(drag_state["start_x"] + offset_x)
            target_y = int(drag_state["start_y"] + offset_y)
            panel_allocation = panel_container.get_allocation()
            max_x = max(self.get_width() - panel_allocation.width, 0)
            max_y = max(self.get_height() - panel_allocation.height, 0)
            target_x = min(max(target_x, 0), max_x)
            target_y = min(max(target_y, 0), max_y)
            self.settings_overlay.move(panel_container, target_x, target_y)
            self.settings_panel_state["x"] = target_x
            self.settings_panel_state["y"] = target_y

        drag_controller.connect("drag-begin", on_drag_begin)
        drag_controller.connect("drag-update", on_drag_update)
        header.add_controller(drag_controller)

        def on_panel_size_allocate(_widget, allocation):
            self.settings_panel_state["width"] = allocation.width
            self.settings_panel_state["height"] = allocation.height

        panel_container.connect("size-allocate", on_panel_size_allocate)

        self.settings_overlay.put(panel_container, 0, 0)
        self.active_settings_panel = panel_container

        def position_panel():
            if self.active_settings_panel is not panel_container:
                return GLib.SOURCE_REMOVE
            allocation = panel_container.get_allocation()
            if allocation.width <= 1 or allocation.height <= 1:
                return GLib.SOURCE_CONTINUE
            if "x" in self.settings_panel_state and "y" in self.settings_panel_state:
                target_x = self.settings_panel_state["x"]
                target_y = self.settings_panel_state["y"]
            else:
                target_x = max(int((self.get_width() - allocation.width) / 2), 0)
                target_y = max(int((self.get_height() - allocation.height) / 2), 0)
                self.settings_panel_state["x"] = target_x
                self.settings_panel_state["y"] = target_y
            self.settings_overlay.move(panel_container, target_x, target_y)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(position_panel)

    def close_settings_panel(self):
        if self.active_settings_panel is None:
            return
        panel = self.active_settings_panel
        if panel.get_parent() is self.settings_overlay:
            self.settings_overlay.remove(panel)
        self.active_settings_panel = None


def main():
    app = Gtk.Application(application_id="com.example.SettingsPanelDemo")

    def on_activate(application):
        window = DemoWindow(application)
        window.present()

    app.connect("activate", on_activate)
    app.run()


if __name__ == "__main__":
    main()
