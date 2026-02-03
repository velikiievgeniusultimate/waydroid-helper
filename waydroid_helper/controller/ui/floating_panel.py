#!/usr/bin/env python3
"""Reusable in-window floating panel widget."""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk


class FloatingPanel(Gtk.Box):
    """Draggable floating panel rendered inside the main window."""

    def __init__(
        self,
        title: str,
        on_close: Callable[[], None],
        bounds_provider: Callable[[], tuple[int, int]],
        position_callback: Callable[[int, int], None],
        min_width: int = 260,
        min_height: int = 300,
        max_height: int = 600,
        default_width: int = 700,
        default_height: int = 600,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_size_request(default_width, default_height)
        self.set_hexpand(False)
        self.set_vexpand(False)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.add_css_class("floating-panel")
        self.add_css_class("card")

        self._bounds_provider = bounds_provider
        self._position_callback = position_callback
        self._on_close = on_close
        self._position: tuple[int, int] | None = None
        self._drag_start: tuple[float, float] | None = None
        self._drag_origin: tuple[int, int] | None = None
        self._default_width = default_width
        self._default_height = default_height

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        header.set_hexpand(True)
        header.add_css_class("floating-panel-header")

        self._title_label = Gtk.Label()
        self._title_label.set_xalign(0.0)
        self._title_label.set_hexpand(True)
        self._title_label.add_css_class("heading")
        header.append(self._title_label)

        close_button = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close_button.add_css_class("flat")
        close_button.connect("clicked", lambda *_: self.close())
        header.append(close_button)

        drag_controller = Gtk.GestureDrag.new()
        drag_controller.connect("drag-begin", self._on_drag_begin)
        drag_controller.connect("drag-update", self._on_drag_update)
        header.add_controller(drag_controller)

        header_motion = Gtk.EventControllerMotion.new()
        header_motion.connect(
            "enter", lambda *_: header.set_cursor_from_name("grab")
        )
        header_motion.connect("leave", lambda *_: header.set_cursor(None))
        header.add_controller(header_motion)

        self.append(header)

        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self._content_box.set_hexpand(True)
        self._content_box.set_vexpand(True)

        self._scroller = Gtk.ScrolledWindow()
        self._scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroller.set_min_content_height(min_height)
        self._scroller.set_max_content_height(max_height)
        self._scroller.set_child(self._content_box)

        self.append(self._scroller)

        self.set_title(title)

        self.connect("size-allocate", self._on_size_allocate)

    def set_title(self, title: str) -> None:
        self._title_label.set_markup(f"<b>{title}</b>")

    def set_body(self, body: Gtk.Widget) -> None:
        for child in list(self._content_box):
            self._content_box.remove(child)
        self._content_box.append(body)

    def set_position(self, x: int, y: int, clamp: bool = True) -> None:
        if clamp:
            x, y = self._clamp_position(x, y)
        self._position = (x, y)
        self._position_callback(x, y)

    def ensure_centered(self) -> None:
        if self._position is not None:
            return
        bounds_width, bounds_height = self._bounds_provider()
        panel_width = self.get_allocated_width() or self._default_width
        panel_height = self.get_allocated_height() or self._default_height
        x = max(0, int((bounds_width - panel_width) / 2))
        y = max(0, int((bounds_height - panel_height) / 2))
        self.set_position(x, y, clamp=True)

    def close(self) -> None:
        self._on_close()

    def _clamp_position(self, x: int, y: int) -> tuple[int, int]:
        bounds_width, bounds_height = self._bounds_provider()
        panel_width = self.get_allocated_width() or self._default_width
        panel_height = self.get_allocated_height() or self._default_height
        max_x = max(0, bounds_width - panel_width)
        max_y = max(0, bounds_height - panel_height)
        return max(0, min(x, max_x)), max(0, min(y, max_y))

    def _on_drag_begin(self, _controller, start_x: float, start_y: float) -> None:
        self._drag_start = (start_x, start_y)
        self._drag_origin = self._position or (0, 0)

    def _on_drag_update(self, _controller, offset_x: float, offset_y: float) -> None:
        if self._drag_origin is None:
            return
        new_x = int(self._drag_origin[0] + offset_x)
        new_y = int(self._drag_origin[1] + offset_y)
        self.set_position(new_x, new_y, clamp=True)

    def _on_size_allocate(self, *_args) -> None:
        if self._position is None:
            return
        self.set_position(self._position[0], self._position[1], clamp=True)
