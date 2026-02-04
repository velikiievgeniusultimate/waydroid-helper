#!/usr/bin/env python3
"""
Circle tilt / radius calibration widget.
"""

from __future__ import annotations

import math
from gettext import pgettext
from typing import TYPE_CHECKING

from gi.repository import Gtk

from waydroid_helper.controller.core import (
    Event,
    EventType,
    EventBus,
    KeyCombination,
    PointerIdManager,
    KeyRegistry,
)
from waydroid_helper.controller.widgets.base.base_widget import BaseWidget
from waydroid_helper.controller.widgets.config import (
    create_action_config,
    create_text_config,
)
from waydroid_helper.controller.widgets.decorators import Editable

if TYPE_CHECKING:
    from cairo import Context, Surface


@Editable
class CircleTiltRadiusCalibration(BaseWidget):
    """Circle Tilt / Radius Calibration"""

    WIDGET_NAME = pgettext("Controller Widgets", "Circle Tilt / Radius Calibration")
    WIDGET_DESCRIPTION = pgettext(
        "Controller Widgets",
        "Visualize center and N/E/S/W offsets for manual calibration.",
    )

    MAPPING_MODE_WIDTH = 42
    MAPPING_MODE_HEIGHT = 42

    CENTER_X_KEY = "center_x"
    CENTER_Y_KEY = "center_y"
    UP_OFFSET_KEY = "up_offset_px"
    DOWN_OFFSET_KEY = "down_offset_px"
    LEFT_OFFSET_KEY = "left_offset_px"
    RIGHT_OFFSET_KEY = "right_offset_px"
    COMPUTE_KEY = "compute"
    CLEAR_KEY = "clear"

    QUALITY_THRESHOLD = 5.0
    MIN_RADIUS = 5.0

    def __init__(
        self,
        x: int = 0,
        y: int = 0,
        width: int = 42,
        height: int = 42,
        text: str = "",
        default_keys: set[KeyCombination] | None = None,
        event_bus: EventBus | None = None,
        pointer_id_manager: PointerIdManager | None = None,
        key_registry: KeyRegistry | None = None,
    ):
        super().__init__(
            x,
            y,
            width,
            height,
            pgettext("Controller Widgets", "Circle Tilt Calibration"),
            text,
            default_keys,
            min_width=32,
            min_height=32,
            event_bus=event_bus,
            pointer_id_manager=pointer_id_manager,
            key_registry=key_registry,
        )

        self._output_buffer: Gtk.TextBuffer | None = None

        self._setup_config()
        self._emit_overlay_event("register")

    def _setup_config(self) -> None:
        self.add_config_item(
            create_text_config(
                key=self.CENTER_X_KEY,
                label=pgettext("Controller Widgets", "Center X"),
                value="0",
                description=pgettext("Controller Widgets", "Center X coordinate."),
            )
        )
        self.add_config_item(
            create_text_config(
                key=self.CENTER_Y_KEY,
                label=pgettext("Controller Widgets", "Center Y"),
                value="0",
                description=pgettext("Controller Widgets", "Center Y coordinate."),
            )
        )
        self.add_config_item(
            create_text_config(
                key=self.UP_OFFSET_KEY,
                label=pgettext("Controller Widgets", "Up Offset (px)"),
                value="0",
                description=pgettext(
                    "Controller Widgets",
                    "Distance from center to the north point.",
                ),
            )
        )
        self.add_config_item(
            create_text_config(
                key=self.DOWN_OFFSET_KEY,
                label=pgettext("Controller Widgets", "Down Offset (px)"),
                value="0",
                description=pgettext(
                    "Controller Widgets",
                    "Distance from center to the south point.",
                ),
            )
        )
        self.add_config_item(
            create_text_config(
                key=self.LEFT_OFFSET_KEY,
                label=pgettext("Controller Widgets", "Left Offset (px)"),
                value="0",
                description=pgettext(
                    "Controller Widgets",
                    "Distance from center to the west point.",
                ),
            )
        )
        self.add_config_item(
            create_text_config(
                key=self.RIGHT_OFFSET_KEY,
                label=pgettext("Controller Widgets", "Right Offset (px)"),
                value="0",
                description=pgettext(
                    "Controller Widgets",
                    "Distance from center to the east point.",
                ),
            )
        )
        self.add_config_item(
            create_action_config(
                key=self.COMPUTE_KEY,
                label=pgettext("Controller Widgets", "Compute"),
                button_label=pgettext("Controller Widgets", "Compute"),
                description=pgettext(
                    "Controller Widgets", "Compute derived values and summary."
                ),
            )
        )
        self.add_config_item(
            create_action_config(
                key=self.CLEAR_KEY,
                label=pgettext("Controller Widgets", "Clear"),
                button_label=pgettext("Controller Widgets", "Clear"),
                description=pgettext(
                    "Controller Widgets", "Reset all inputs and output."
                ),
            )
        )

        for key in (
            self.CENTER_X_KEY,
            self.CENTER_Y_KEY,
            self.UP_OFFSET_KEY,
            self.DOWN_OFFSET_KEY,
            self.LEFT_OFFSET_KEY,
            self.RIGHT_OFFSET_KEY,
        ):
            self.add_config_change_callback(key, self._on_inputs_changed)
        self.add_config_change_callback(self.COMPUTE_KEY, self._on_compute_clicked)
        self.add_config_change_callback(self.CLEAR_KEY, self._on_clear_clicked)

    def _emit_overlay_event(self, action: str) -> None:
        self.event_bus.emit(
            Event(
                EventType.RIGHT_CLICK_TO_WALK_OVERLAY,
                self,
                {"action": action, "widget": self},
            )
        )

    def _on_inputs_changed(self, key: str, value: object, restoring: bool) -> None:
        self._emit_overlay_event("refresh")

    def _on_compute_clicked(self, key: str, value: object, restoring: bool) -> None:
        if restoring:
            return
        if self._output_buffer is None:
            return
        summary = self._build_compute_summary()
        self._output_buffer.set_text(summary)

    def _on_clear_clicked(self, key: str, value: object, restoring: bool) -> None:
        if restoring:
            return
        self.set_config_value(self.CENTER_X_KEY, "0")
        self.set_config_value(self.CENTER_Y_KEY, "0")
        self.set_config_value(self.UP_OFFSET_KEY, "0")
        self.set_config_value(self.DOWN_OFFSET_KEY, "0")
        self.set_config_value(self.LEFT_OFFSET_KEY, "0")
        self.set_config_value(self.RIGHT_OFFSET_KEY, "0")
        if self._output_buffer is not None:
            self._output_buffer.set_text("")
        self._emit_overlay_event("refresh")

    def _parse_float(self, value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, str):
            if not value.strip():
                return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed):
            return None
        return parsed

    def _get_inputs(self) -> dict[str, object]:
        return {
            "cx": self.get_config_value(self.CENTER_X_KEY),
            "cy": self.get_config_value(self.CENTER_Y_KEY),
            "up": self.get_config_value(self.UP_OFFSET_KEY),
            "down": self.get_config_value(self.DOWN_OFFSET_KEY),
            "left": self.get_config_value(self.LEFT_OFFSET_KEY),
            "right": self.get_config_value(self.RIGHT_OFFSET_KEY),
        }

    def _get_numeric_inputs(self) -> tuple[float, float, float, float, float, float]:
        inputs = self._get_inputs()
        cx = self._parse_float(inputs["cx"]) or 0.0
        cy = self._parse_float(inputs["cy"]) or 0.0
        up = self._parse_float(inputs["up"]) or 0.0
        down = self._parse_float(inputs["down"]) or 0.0
        left = self._parse_float(inputs["left"]) or 0.0
        right = self._parse_float(inputs["right"]) or 0.0
        return cx, cy, up, down, left, right

    def _build_compute_summary(self) -> str:
        inputs = self._get_inputs()
        cx, cy, up, down, left, right = self._get_numeric_inputs()
        n = (cx, cy - up)
        s = (cx, cy + down)
        w = (cx - left, cy)
        e = (cx + right, cy)
        r_x = (left + right) / 2.0
        r_y = (up + down) / 2.0
        dx_bias = (right - left) / 2.0
        dy_bias = (down - up) / 2.0
        corrected_cx = cx + dx_bias
        corrected_cy = cy + dy_bias
        ratio = "∞"
        if r_x != 0:
            ratio = f"{r_y / r_x:.4f}"

        warnings: list[str] = []
        if abs(left - right) > self.QUALITY_THRESHOLD:
            warnings.append(
                f"Left/right mismatch > {self.QUALITY_THRESHOLD:.1f}px"
            )
        if abs(up - down) > self.QUALITY_THRESHOLD:
            warnings.append(
                f"Up/down mismatch > {self.QUALITY_THRESHOLD:.1f}px"
            )
        if r_x < self.MIN_RADIUS or r_y < self.MIN_RADIUS:
            warnings.append(
                f"Radius too small (min {self.MIN_RADIUS:.1f}px)"
            )

        raw_inputs = (
            f"cx={inputs['cx']} cy={inputs['cy']}"
            f" up={inputs['up']} down={inputs['down']}"
            f" left={inputs['left']} right={inputs['right']}"
        )
        lines = [
            "Circle Tilt / Radius Calibration",
            "",
            f"Raw inputs: {raw_inputs}",
            "",
            f"Center: ({cx:.2f}, {cy:.2f})",
            f"N: ({n[0]:.2f}, {n[1]:.2f})",
            f"S: ({s[0]:.2f}, {s[1]:.2f})",
            f"W: ({w[0]:.2f}, {w[1]:.2f})",
            f"E: ({e[0]:.2f}, {e[1]:.2f})",
            "",
            f"r_x: {r_x:.2f}",
            f"r_y: {r_y:.2f}",
            f"dx_bias: {dx_bias:.2f}",
            f"dy_bias: {dy_bias:.2f}",
            f"scale ratio (s): {ratio}",
            "",
            f"corrected_cx: {corrected_cx:.2f}",
            f"corrected_cy: {corrected_cy:.2f}",
            "",
            "Quality checks:",
        ]
        if warnings:
            lines.extend([f"- {warning}" for warning in warnings])
        else:
            lines.append("- OK")
        return "\n".join(lines)

    def draw_widget_content(self, cr: "Context[Surface]", width: int, height: int):
        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) / 2 - 4
        cr.set_source_rgba(0.2, 0.6, 1.0, 0.6)
        cr.arc(center_x, center_y, radius, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(0.1, 0.3, 0.6, 0.9)
        cr.set_line_width(2)
        cr.arc(center_x, center_y, radius, 0, 2 * math.pi)
        cr.stroke()

    def draw_text_content(self, cr: "Context[Surface]", width: int, height: int):
        return None

    def create_settings_panel(self) -> Gtk.Widget:
        config_manager = self.get_config_manager()
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        panel.set_margin_top(6)
        panel.set_margin_bottom(6)
        panel.set_margin_start(6)
        panel.set_margin_end(6)

        intro = Gtk.Label(
            label=pgettext(
                "Controller Widgets",
                "Enter center and offsets, then compute derived values.",
            ),
            xalign=0,
        )
        intro.set_wrap(True)
        panel.append(intro)

        def add_config_widget(key: str) -> None:
            widget = config_manager.create_ui_widget_for_key(key)
            if widget is not None:
                panel.append(widget)

        for key in (
            self.CENTER_X_KEY,
            self.CENTER_Y_KEY,
            self.UP_OFFSET_KEY,
            self.DOWN_OFFSET_KEY,
            self.LEFT_OFFSET_KEY,
            self.RIGHT_OFFSET_KEY,
            self.COMPUTE_KEY,
            self.CLEAR_KEY,
        ):
            add_config_widget(key)

        output_label = Gtk.Label(
            label=pgettext("Controller Widgets", "Output"),
            xalign=0,
        )
        panel.append(output_label)

        text_view = Gtk.TextView()
        text_view.set_editable(False)
        text_view.set_cursor_visible(False)
        text_view.set_monospace(True)
        text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        buffer = text_view.get_buffer()
        self._output_buffer = buffer

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_min_content_height(180)
        scrolled.set_child(text_view)
        panel.append(scrolled)

        return panel

    def is_debug_boundary_enabled(self) -> bool:
        return True

    def get_effective_center(self) -> tuple[float, float] | None:
        cx, cy, _up, _down, _left, _right = self._get_numeric_inputs()
        return (cx, cy)

    def get_anchor_overlay_data(self) -> dict[str, object] | None:
        cx, cy, up, down, left, right = self._get_numeric_inputs()
        center = (cx, cy)
        anchors = {
            "up": (cx, cy - up),
            "down": (cx, cy + down),
            "left": (cx - left, cy),
            "right": (cx + right, cy),
        }
        contour = [
            center,
            anchors["up"],
            center,
            anchors["right"],
            center,
            anchors["down"],
            center,
            anchors["left"],
            center,
        ]
        return {"center": center, "anchors": anchors, "contour": contour}

    def on_delete(self) -> None:
        self._emit_overlay_event("unregister")
        super().on_delete()
