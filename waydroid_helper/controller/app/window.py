#!/usr/bin/env python3

"""
Transparent window module
Provides implementation and window management for transparent windows
"""

import math
from gettext import gettext as _
from typing import TYPE_CHECKING, Callable
from functools import partial

import gi, signal

from waydroid_helper.controller.core.control_msg import ScreenInfo
from waydroid_helper.controller.core.utils import PointerIdManager

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

import asyncio

from gi.repository import Adw, Gdk, GLib, GObject, Gtk
from gi.events import GLibEventLoopPolicy

from waydroid_helper.compat_widget import PropertyAnimationTarget
from waydroid_helper.controller.app.workspace_manager import WorkspaceManager
from waydroid_helper.controller.core import (Event, EventType, KeyCombination,
                                             Server, EventBus,
                                             is_point_in_rect, KeyRegistry)
from waydroid_helper.controller.core.constants import APP_TITLE
from waydroid_helper.controller.core.handler import (DefaultEventHandler,
                                                     InputEvent,
                                                     InputEventHandlerChain,
                                                     KeyMappingEventHandler,
                                                     KeyMappingManager)
from waydroid_helper.controller.ui.menus import ContextMenuManager
from waydroid_helper.controller.ui.styles import StyleManager
from waydroid_helper.controller.widgets.factory import WidgetFactory
from waydroid_helper.util import AdbHelper, logger

if TYPE_CHECKING:
    from waydroid_helper.controller.widgets.base import BaseWidget

from cairo import FontSlant, FontWeight


Adw.init()

MAX_RETRY_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 3


class FloatingSettingsWindow(Adw.Window):
    """Floating, resizable settings window for widgets."""

    def __init__(
        self,
        parent: Gtk.Window,
        widget: object,
        content: Gtk.Widget,
        on_close: Callable[[], None],
        min_width: int,
        min_height: int,
    ) -> None:
        super().__init__(transient_for=parent, modal=False)
        if isinstance(parent, Gtk.Window):
            application = parent.get_application()
            if application is not None:
                self.set_application(application)
        self.set_title(f"{getattr(widget, 'WIDGET_NAME', _('Settings'))} {_('Settings')}")
        self.set_resizable(True)
        self.set_decorated(True)
        self.set_default_size(min_width, min_height)

        header = Adw.HeaderBar()
        header.set_title_widget(Gtk.Label(label=self.get_title()))
        self.set_titlebar(header)

        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        container.set_margin_top(10)
        container.set_margin_bottom(10)
        container.set_margin_start(10)
        container.set_margin_end(10)
        container.append(content)
        self.set_content(container)

        self.connect("close-request", lambda _w: on_close() or False)

        key_controller = Gtk.EventControllerKey.new()

        def on_key_pressed(controller, keyval, keycode, state):
            if hasattr(parent, "on_global_key_press"):
                return bool(parent.on_global_key_press(controller, keyval, keycode, state))
            return False

        key_controller.connect("key-pressed", on_key_pressed)
        self.add_controller(key_controller)


class RightClickToWalkOverlay(Gtk.DrawingArea):
    """Overlay for right-click-to-walk calibration and center markers."""

    def __init__(self):
        super().__init__()
        self.widgets: set[object] = set()
        self.active_widget: object | None = None
        self.tuning_widget: object | None = None
        self.cursor_position: tuple[int, int] | None = None
        self.mapping_mode: bool = False
        self.drag_widget: object | None = None
        self.drag_point: str | None = None
        self.drag_start_offset: tuple[int, int] | None = None
        self.set_draw_func(self._draw_overlay, None)
        self.set_can_target(False)
        self.set_visible(False)

    def register_widget(self, widget: object) -> None:
        self.widgets.add(widget)
        self.set_visible(bool(self.widgets))
        self.queue_draw()

    def unregister_widget(self, widget: object) -> None:
        if widget in self.widgets:
            self.widgets.remove(widget)
        if self.active_widget is widget:
            self.active_widget = None
        if self.tuning_widget is widget:
            self.tuning_widget = None
        if self.drag_widget is widget:
            self.drag_widget = None
            self.drag_point = None
            self.drag_start_offset = None
        if not self.widgets:
            self.set_visible(False)
        self.queue_draw()

    def set_active_widget(self, widget: object | None) -> None:
        if not self.mapping_mode:
            self.active_widget = None
            self.queue_draw()
            return
        self.active_widget = widget
        if widget is not None:
            self.register_widget(widget)
        self.queue_draw()

    def set_tuning_widget(self, widget: object | None) -> None:
        if not self.mapping_mode:
            self.tuning_widget = None
            self.queue_draw()
            return
        self.tuning_widget = widget
        if widget is not None:
            self.register_widget(widget)
        self.queue_draw()

    def set_mapping_mode(self, mapping_mode: bool) -> None:
        if self.mapping_mode == mapping_mode:
            return
        self.mapping_mode = mapping_mode
        if not mapping_mode:
            for widget in list(self.widgets):
                cancel = getattr(widget, "cancel_calibration", None)
                if callable(cancel):
                    cancel()
                cancel_tuning = getattr(widget, "cancel_tuning", None)
                if callable(cancel_tuning):
                    cancel_tuning()
            self.active_widget = None
            self.tuning_widget = None
            self.cursor_position = None
            self.drag_widget = None
            self.drag_point = None
            self.drag_start_offset = None
            self.set_visible(bool(self.widgets))
        else:
            self.set_visible(bool(self.widgets))
        self.queue_draw()

    def update_cursor(self, position: tuple[int, int]) -> None:
        self.cursor_position = position
        if self.get_visible():
            self.queue_draw()

    def handle_edit_mouse_pressed(self, x: float, y: float, button: int) -> bool:
        if self.mapping_mode or button != Gdk.BUTTON_PRIMARY:
            return False
        if self.drag_widget is not None:
            return True
        target = self._find_diagonal_handle(x, y)
        if target is None:
            return False
        widget, key_name = target
        get_offset = getattr(widget, "get_diagonal_offset", None)
        offset = get_offset(key_name) if callable(get_offset) else None
        if offset is None:
            return False
        self.drag_widget = widget
        self.drag_point = key_name
        self.drag_start_offset = offset
        self.queue_draw()
        return True

    def handle_edit_mouse_motion(self, x: float, y: float) -> bool:
        if self.mapping_mode or self.drag_widget is None or self.drag_point is None:
            return False
        get_center = getattr(self.drag_widget, "get_effective_center", None)
        update_offset = getattr(self.drag_widget, "update_diagonal_offset", None)
        if not callable(get_center) or not callable(update_offset):
            return False
        center = get_center()
        if center is None:
            return False
        dx = x - center[0]
        dy = y - center[1]
        updated = update_offset(self.drag_point, dx, dy)
        if updated:
            self.queue_draw()
        return updated

    def handle_edit_mouse_released(self, button: int) -> bool:
        if self.mapping_mode or button != Gdk.BUTTON_PRIMARY:
            return False
        if self.drag_widget is None:
            return False
        self.drag_widget = None
        self.drag_point = None
        self.drag_start_offset = None
        self.queue_draw()
        return True

    def handle_edit_key(self, keyval: int) -> bool:
        if keyval != Gdk.KEY_Escape or self.drag_widget is None:
            return False
        if self.drag_widget is not None and self.drag_point is not None and self.drag_start_offset is not None:
            update_offset = getattr(self.drag_widget, "update_diagonal_offset", None)
            if callable(update_offset):
                update_offset(self.drag_point, *self.drag_start_offset)
        self.drag_widget = None
        self.drag_point = None
        self.drag_start_offset = None
        self.queue_draw()
        return True

    def _find_diagonal_handle(self, x: float, y: float) -> tuple[object, str] | None:
        closest = None
        min_distance_sq = None
        for widget in self.widgets:
            get_handles = getattr(widget, "get_diagonal_handle_positions", None)
            get_radius = getattr(widget, "get_diagonal_handle_radius", None)
            if not callable(get_handles):
                continue
            handles = get_handles()
            if not handles:
                continue
            radius = get_radius() if callable(get_radius) else 10
            radius_sq = radius * radius
            for key_name, (hx, hy) in handles.items():
                dx = x - hx
                dy = y - hy
                distance_sq = dx * dx + dy * dy
                if distance_sq <= radius_sq and (
                    min_distance_sq is None or distance_sq < min_distance_sq
                ):
                    min_distance_sq = distance_sq
                    closest = (widget, key_name)
        return closest

    def handle_tuning_key(self, keyval: int, state: Gdk.ModifierType) -> bool:
        if not self.mapping_mode or self.tuning_widget is None:
            return False
        handler = getattr(self.tuning_widget, "handle_tuning_key", None)
        if callable(handler):
            return bool(handler(keyval, state))
        return False

    @property
    def is_tuning_active(self) -> bool:
        return (
            self.mapping_mode
            and self.tuning_widget is not None
            and bool(getattr(self.tuning_widget, "is_tuning", False))
        )

    def _draw_crosshair(self, cr, x: float, y: float) -> None:
        cr.set_source_rgba(0.2, 0.8, 1.0, 0.9)
        cr.set_line_width(1.5)
        cr.move_to(x - 8, y)
        cr.line_to(x + 8, y)
        cr.stroke()
        cr.move_to(x, y - 8)
        cr.line_to(x, y + 8)
        cr.stroke()
        cr.set_source_rgba(0.2, 0.8, 1.0, 0.6)
        cr.set_line_width(1.2)
        cr.arc(x, y, 10, 0, 2 * math.pi)
        cr.stroke()

    def _draw_anchor_shape(self, cr, widget: object, data: dict[str, object]) -> None:
        contour = data.get("contour")
        anchors = data.get("anchors")
        diagonals = data.get("diagonals")
        if not contour or not anchors:
            return
        points = list(contour)
        if not points:
            return
        cr.set_source_rgba(0.2, 0.9, 0.5, 0.8)
        cr.set_line_width(2.0)
        cr.move_to(points[0][0], points[0][1])
        for x, y in points[1:]:
            cr.line_to(x, y)
        cr.stroke()

        cr.set_source_rgba(1.0, 0.9, 0.2, 0.9)
        for anchor in anchors.values():
            cr.arc(anchor[0], anchor[1], 4, 0, 2 * math.pi)
            cr.fill()

        if diagonals:
            for key_name, point in diagonals.items():
                radius = 5
                if self.drag_widget is widget and self.drag_point == key_name:
                    radius = 7
                cr.set_source_rgba(0.2, 0.8, 1.0, 0.9)
                cr.arc(point[0], point[1], radius, 0, 2 * math.pi)
                cr.fill()

    def _get_ideal_calibration_overlay(self) -> tuple[object, dict[str, object]] | None:
        for widget in self.widgets:
            getter = getattr(widget, "get_ideal_calibration_overlay_data", None)
            if callable(getter):
                data = getter()
                if isinstance(data, dict) and data.get("active"):
                    return widget, data
        return None

    def _draw_ideal_calibration_overlay(self, cr, data: dict[str, object], width: int, height: int) -> None:
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        target = data.get("target")
        center = data.get("center")
        if target and center:
            tx, ty = target
            cr.set_source_rgba(1.0, 0.6, 0.2, 0.9)
            cr.set_line_width(2.0)
            cr.arc(tx, ty, 8, 0, 2 * math.pi)
            cr.stroke()
            cr.set_source_rgba(1.0, 0.8, 0.3, 0.4)
            cr.arc(tx, ty, 14, 0, 2 * math.pi)
            cr.stroke()

        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.select_font_face("Sans", FontSlant.NORMAL, FontWeight.NORMAL)
        cr.set_font_size(14)
        margin = 16
        line_height = 18
        lines = [
            data.get("title", ""),
            data.get("progress", ""),
            data.get("instruction", ""),
        ]
        if data.get("awaiting_confirmation"):
            lines.append(data.get("confirmation", ""))
        for index, text in enumerate(line for line in lines if line):
            cr.move_to(margin, margin + line_height * (index + 1))
            cr.show_text(text)

    def _draw_overlay(self, widget, cr, width, height, user_data):
        if not self.widgets:
            return

        calibration = self._get_ideal_calibration_overlay()
        if calibration is not None:
            _, data = calibration
            self._draw_ideal_calibration_overlay(cr, data, width, height)
            return

        if not self.mapping_mode:
            for center_widget in self.widgets:
                get_debug = getattr(center_widget, "is_debug_boundary_enabled", None)
                if callable(get_debug) and not get_debug():
                    continue
                get_center = getattr(center_widget, "get_effective_center", None)
                if not callable(get_center):
                    continue
                center = get_center()
                if center is None:
                    continue
                self._draw_crosshair(cr, center[0], center[1])
                get_anchor_overlay = getattr(center_widget, "get_anchor_overlay_data", None)
                if callable(get_anchor_overlay):
                    anchor_data = get_anchor_overlay()
                    if anchor_data is not None:
                        self._draw_anchor_shape(cr, center_widget, anchor_data)
            return

        is_calibrating = False
        if self.active_widget is not None:
            is_calibrating = bool(getattr(self.active_widget, "is_calibrating", False))

        tuning_active = False
        tuning_widget = self.tuning_widget
        if tuning_widget is not None:
            tuning_active = bool(getattr(tuning_widget, "is_tuning", False))

        if is_calibrating or tuning_active:
            cr.set_source_rgba(0, 0, 0, 0.45)
            cr.rectangle(0, 0, width, height)
            cr.fill()

        if not (self.active_widget and is_calibrating) and not tuning_active:
            return

        if is_calibrating and self.cursor_position is not None:
            cursor_x, cursor_y = self.cursor_position
            cr.set_source_rgba(1.0, 0.7, 0.2, 0.9)
            cr.arc(cursor_x, cursor_y, 6, 0, 2 * math.pi)
            cr.stroke()

            cursor_text = f"Cursor: {self.cursor_position[0]}, {self.cursor_position[1]}"

            get_effective_center = getattr(self.active_widget, "get_effective_center", None)
            center_text = "Center: -,-"
            center = None
            if callable(get_effective_center):
                center = get_effective_center()
                if center is not None:
                    center_text = f"Center: {int(center[0])}, {int(center[1])}"

            get_stored_center = getattr(self.active_widget, "get_calibrated_center", None)
            stored_center = get_stored_center() if callable(get_stored_center) else None
            if stored_center is None and center is not None:
                center_text = f"Center (default): {int(center[0])}, {int(center[1])}"
            elif stored_center is not None:
                center_text = f"Center (stored): {int(center[0])}, {int(center[1])}"

            cr.set_source_rgba(1, 1, 1, 0.95)
            cr.select_font_face("Sans", FontSlant.NORMAL, FontWeight.NORMAL)
            cr.set_font_size(14)
            margin = 16
            line_height = 18
            cr.move_to(margin, margin + line_height)
            cr.show_text(cursor_text)
            cr.move_to(margin, margin + line_height * 2)
            cr.show_text(center_text)

        if tuning_active and tuning_widget is not None:
            tuning_data = getattr(tuning_widget, "get_tuning_overlay_data", None)
            data = tuning_data(self.cursor_position) if callable(tuning_data) else {}
            x_gain = data.get("x_gain", 1.0)
            y_gain = data.get("y_gain", 1.0)
            raw_angle = data.get("raw_angle")
            corrected_angle = data.get("corrected_angle")
            raw_vector = data.get("raw_vector")
            corrected_vector = data.get("corrected_vector")
            center = data.get("center")

            if center and raw_vector and corrected_vector:
                center_x, center_y = center
                raw_dx, raw_dy = raw_vector
                corrected_dx, corrected_dy = corrected_vector
                raw_len = math.hypot(raw_dx, raw_dy)
                corrected_len = math.hypot(corrected_dx, corrected_dy)
                line_length = 60
                if raw_len > 0:
                    cr.set_source_rgba(0.9, 0.5, 0.2, 0.9)
                    cr.set_line_width(2)
                    cr.move_to(center_x, center_y)
                    cr.line_to(
                        center_x + raw_dx / raw_len * line_length,
                        center_y + raw_dy / raw_len * line_length,
                    )
                    cr.stroke()
                if corrected_len > 0:
                    cr.set_source_rgba(0.2, 0.8, 1.0, 0.9)
                    cr.set_line_width(2)
                    cr.move_to(center_x, center_y)
                    cr.line_to(
                        center_x + corrected_dx / corrected_len * line_length,
                        center_y + corrected_dy / corrected_len * line_length,
                    )
                    cr.stroke()

            raw_angle_text = "--"
            corrected_angle_text = "--"
            if raw_angle is not None:
                raw_angle_text = f"{raw_angle:.1f}°"
            if corrected_angle is not None:
                corrected_angle_text = f"{corrected_angle:.1f}°"

            cr.set_source_rgba(1, 1, 1, 0.95)
            cr.select_font_face("Sans", FontSlant.NORMAL, FontWeight.NORMAL)
            cr.set_font_size(14)
            margin = 16
            line_height = 18
            cr.move_to(margin, margin + line_height)
            cr.show_text(f"Raw angle: {raw_angle_text}")
            cr.move_to(margin, margin + line_height * 2)
            cr.show_text(f"Corrected angle: {corrected_angle_text}")
            cr.move_to(margin, margin + line_height * 3)
            cr.show_text(f"X Gain: {x_gain:.2f}  Y Gain: {y_gain:.2f}")


class TransparentWindow(Adw.Window):
    """Transparent window"""

    # __gtype_name__ = 'TransparentWindow'

    # Define mode constants
    EDIT_MODE = "edit"
    MAPPING_MODE = "mapping"

    # Define current_mode as a GObject property
    current_mode = GObject.Property(
        type=str,
        default=EDIT_MODE,
        nick="Current Mode",
        blurb="The current operating mode (edit or mapping)",
    )

    def __init__(self, app, display_name: str):
        super().__init__(application=app)

        # 添加关闭状态标志，避免重复关闭
        self._is_closing = False

        if self.get_display().get_name() != display_name:
            display = Gdk.Display.open(display_name)
            if display:
                self.set_display(display)
            else:
                raise ValueError("Failed to open display")

        self.connect("close-request", self._on_close_request)

        self.set_title(APP_TITLE)

        # Create main container (Overlay)
        overlay = Gtk.Overlay.new()
        self.overlay = overlay
        self.set_content(overlay)

        self.fixed = Gtk.Fixed.new()
        self.fixed.set_name("mapping-widget")
        overlay.set_child(self.fixed)

        self.event_bus = EventBus()

        # Create mode switching hint
        self.notification_label = Gtk.Label.new("")
        self.notification_label.set_name("mode-notification-label")

        self.notification_box = Gtk.Box()
        self.notification_box.set_name("mode-notification-box")
        self.notification_box.set_halign(Gtk.Align.CENTER)
        self.notification_box.set_valign(Gtk.Align.START)
        self.notification_box.set_margin_top(60)
        self.notification_box.append(self.notification_label)
        self.notification_box.set_opacity(0.0)
        self.notification_box.set_can_target(False)  # Ignore mouse events

        overlay.add_overlay(self.notification_box)

        # Initialize components
        self.widget_factory = WidgetFactory()
        self.style_manager = StyleManager(self.get_display())
        self.menu_manager = ContextMenuManager(self)
        self.workspace_manager = WorkspaceManager(self, self.fixed, self.event_bus)

        # Subscribe to events
        self.event_bus.subscribe(
            EventType.SETTINGS_WIDGET,
            self._on_widget_settings_requested,
            subscriber=self,
        )
        self.event_bus.subscribe(
            EventType.RIGHT_CLICK_TO_WALK_OVERLAY,
            self._on_right_click_to_walk_overlay,
            subscriber=self,
        )
        self.event_bus.subscribe(
            EventType.DELETE_WIDGET,
            self._on_widget_deleted,
            subscriber=self,
        )

        self.right_click_overlay = RightClickToWalkOverlay()
        overlay.add_overlay(self.right_click_overlay)

        self.active_settings_window: FloatingSettingsWindow | None = None
        self.active_settings_panel: Gtk.Widget | None = None
        self.active_settings_widget: object | None = None
        self.active_mask_layer: Gtk.Widget | None = None
        self._mask_disabled_controllers: list[tuple[Gtk.EventController, Gtk.PropagationPhase]] | None = None

        self.pointer_id_manager = PointerIdManager()
        self.key_registry = KeyRegistry()
        self.key_mapping_manager = KeyMappingManager(self.event_bus)
        # Create global event handler chain
        self.event_handler_chain = InputEventHandlerChain()
        # Import and add default handler
        self.server = Server("0.0.0.0", 10721, self.event_bus)  # 使用单例模式
        self.adb_helper = AdbHelper()
        self.scrcpy_setup_task = asyncio.create_task(self.setup_scrcpy())
        self.key_mapping_handler = KeyMappingEventHandler(self.key_mapping_manager)
        self.default_handler = DefaultEventHandler(self.event_bus)

        self.event_handler_chain.add_handler(self.key_mapping_handler)
        self.event_handler_chain.add_handler(self.default_handler)

        # Initialize dual mode system
        self.setup_mode_system()

        # Initialize event handlers
        self.setup_event_handlers()

        # Set fullscreen
        self.setup_window()

        # Set UI (mainly event controllers)
        self.setup_controllers()

        # Load saved widget profile
        self.menu_manager.load_current_profile(self.widget_factory)

        # Initial hint
        GLib.idle_add(self.show_notification, _("Edit Mode (F1: Switch Mode)"))

    def _on_widget_settings_requested(self, event: "Event[bool]"):
        """Callback when a widget requests settings, opens a floating window."""
        widget = event.source
        self._open_settings_window(widget)

    def _open_settings_window(self, widget: object) -> None:
        if self.active_settings_window is not None:
            self._close_settings_window()

        config_manager = widget.get_config_manager()
        min_width = getattr(widget, "SETTINGS_PANEL_MIN_WIDTH", 320)
        min_height = getattr(widget, "SETTINGS_PANEL_MIN_HEIGHT", 360)
        max_height = getattr(widget, "SETTINGS_PANEL_MAX_HEIGHT", 800)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        if not config_manager.configs:
            label = Gtk.Label(label=_("This widget has no settings."))
            content.append(label)
        else:
            try:
                config_panel = widget.create_settings_panel()
            except Exception as exc:
                logger.exception("Failed to build settings panel: %s", exc)
                config_panel = Gtk.Label(
                    label=_("Unable to load settings. Please reopen the panel.")
                )
            scroller = Gtk.ScrolledWindow()
            scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroller.set_min_content_height(min_height)
            scroller.set_max_content_height(max_height)
            scroller.set_child(config_panel)
            content.append(scroller)

            confirm_button = Gtk.Button(label=_("Close"), halign=Gtk.Align.END)
            confirm_button.add_css_class("suggested-action")

            def on_confirm_clicked(_btn):
                config_manager.emit("confirmed")
                self._close_settings_window()

            confirm_button.connect("clicked", on_confirm_clicked)
            content.append(confirm_button)

        self.active_settings_panel = content
        self.active_settings_widget = widget

        def on_close():
            config_manager.emit("confirmed")
            self._close_settings_window()

        try:
            self.active_settings_window = FloatingSettingsWindow(
                self,
                widget,
                content,
                on_close,
                min_width,
                min_height,
            )
            self.active_settings_window.present()
        except Exception as exc:
            logger.exception("Failed to open settings window: %s", exc)
            self.active_settings_window = None
            self.active_settings_panel = None
            self.active_settings_widget = None

    def _ensure_mask_layer(self) -> None:
        if self.active_mask_layer is not None:
            return
        overlay = self.get_content()
        if not isinstance(overlay, Gtk.Overlay):
            return
        mask_layer = Gtk.Box()
        mask_layer.set_hexpand(True)
        mask_layer.set_vexpand(True)
        mask_layer.set_name("mask-layer")
        mask_layer.set_visible(True)
        mask_layer.set_cursor_from_name("default")
        mask_layer.add_css_class("calibration-mask")
        mask_layer.set_opacity(0.0)
        mask_layer.set_can_target(False)
        mask_layer.set_focusable(False)

        click_controller = Gtk.GestureClick()
        click_controller.set_button(0)

        def on_mask_clicked(controller, n_press, x, y):
            self.event_bus.emit(
                Event(EventType.MASK_CLICKED, self, {"x": int(x), "y": int(y)})
            )
            controller.set_state(Gtk.EventSequenceState.CLAIMED)
            return True

        click_controller.connect("pressed", on_mask_clicked)
        click_controller.connect("released", lambda c, n, x, y: True)
        mask_layer.add_controller(click_controller)

        motion_controller = Gtk.EventControllerMotion.new()

        def on_mask_motion(_controller, x, y):
            if (
                self.right_click_overlay.active_widget is not None
                and getattr(self.right_click_overlay.active_widget, "is_calibrating", False)
            ):
                self.right_click_overlay.update_cursor((int(x), int(y)))

        motion_controller.connect("motion", on_mask_motion)
        mask_layer.add_controller(motion_controller)

        key_controller = Gtk.EventControllerKey.new()

        def on_mask_key_press(_controller, keyval, keycode, state):
            if keyval != Gdk.KEY_Escape:
                return False
            widget_to_cancel = self.active_settings_widget
            if (
                self.right_click_overlay.active_widget is not None
                and getattr(self.right_click_overlay.active_widget, "is_calibrating", False)
            ):
                widget_to_cancel = self.right_click_overlay.active_widget
            if widget_to_cancel is None:
                return False
            cancel = getattr(widget_to_cancel, "cancel_calibration", None)
            if callable(cancel) and getattr(widget_to_cancel, "is_calibrating", False):
                cancel()
                return True
            cancel_anchor_set = getattr(widget_to_cancel, "cancel_anchor_set", None)
            if callable(cancel_anchor_set):
                cancel_anchor_set()
                return True
            cancel_wizard = getattr(widget_to_cancel, "cancel_ideal_calibration", None)
            if callable(cancel_wizard):
                cancel_wizard()
                return True
            return False

        key_controller.connect("key-pressed", on_mask_key_press)
        mask_layer.add_controller(key_controller)

        overlay.add_overlay(mask_layer)
        self.active_mask_layer = mask_layer

    def _disable_window_controllers(self) -> list[tuple[Gtk.EventController, Gtk.PropagationPhase]]:
        window_controllers = []
        for controller in self.observe_controllers():
            if isinstance(
                controller,
                (
                    Gtk.EventControllerKey,
                    Gtk.GestureClick,
                    Gtk.EventControllerMotion,
                    Gtk.EventControllerScroll,
                ),
            ):
                original_state = controller.get_propagation_phase()
                controller.set_propagation_phase(Gtk.PropagationPhase.NONE)
                window_controllers.append((controller, original_state))
        return window_controllers

    def _restore_window_controllers(
        self, window_controllers: list[tuple[Gtk.EventController, Gtk.PropagationPhase]]
    ) -> None:
        for controller, original_state in window_controllers:
            controller.set_propagation_phase(original_state)

    def _close_settings_window(self) -> None:
        if self.active_settings_window is not None:
            self.active_settings_window.destroy()
            self.active_settings_window = None
        if self.active_settings_panel is not None:
            self.active_settings_panel = None
        if self.active_settings_widget is not None:
            config_manager = self.active_settings_widget.get_config_manager()
            config_manager.clear_ui_references()
            self.active_settings_widget = None
        if self.active_mask_layer is not None:
            overlay = self.get_content()
            if (
                isinstance(overlay, Gtk.Overlay)
                and self.active_mask_layer.get_parent()
                and not self.active_mask_layer.get_can_target()
            ):
                overlay.remove_overlay(self.active_mask_layer)
                self.active_mask_layer = None
        if self._mask_disabled_controllers:
            self._restore_window_controllers(self._mask_disabled_controllers)
            self._mask_disabled_controllers = None

    def _on_right_click_to_walk_overlay(self, event: "Event[dict[str, object]]") -> None:
        data = event.data or {}
        action = data.get("action")
        widget = data.get("widget")
        if action == "register":
            self.right_click_overlay.register_widget(widget)
            return
        if action == "unregister":
            self.right_click_overlay.unregister_widget(widget)
            return
        if action == "start":
            self.right_click_overlay.set_active_widget(widget)
            self._set_mask_interactive(True)
            self._set_mask_dimmed(True)
            return
        if action == "stop":
            if self.right_click_overlay.active_widget is widget:
                self.right_click_overlay.set_active_widget(None)
            self._set_mask_interactive(False)
            self._set_mask_dimmed(False)
            return
        if action == "tune_start":
            self.right_click_overlay.set_tuning_widget(widget)
            return
        if action == "tune_stop":
            if self.right_click_overlay.tuning_widget is widget:
                self.right_click_overlay.set_tuning_widget(None)
            return
        if action == "refresh":
            self.right_click_overlay.queue_draw()

    def _on_widget_deleted(self, event: "Event[object]") -> None:
        widget = event.source
        self.right_click_overlay.unregister_widget(widget)

    def _set_settings_panel_visible(self, visible: bool, widget: object | None) -> None:
        if widget is None or self.active_settings_widget is not widget:
            return
        if self.active_settings_window is not None:
            self.active_settings_window.set_visible(visible)

    def _set_mask_interactive(self, interactive: bool) -> None:
        if interactive and self.active_mask_layer is None:
            self._ensure_mask_layer()
        if self.active_mask_layer is None:
            return
        self.active_mask_layer.set_can_target(interactive)
        self.active_mask_layer.set_focusable(interactive)
        if interactive:
            self.active_mask_layer.grab_focus()
            if self._mask_disabled_controllers is None:
                self._mask_disabled_controllers = self._disable_window_controllers()
        elif self._mask_disabled_controllers:
            self._restore_window_controllers(self._mask_disabled_controllers)
            self._mask_disabled_controllers = None

    def _set_mask_dimmed(self, dimmed: bool) -> None:
        if self.active_mask_layer is None:
            return
        # Dimming is handled by the overlay drawing layer.
        self.active_mask_layer.set_opacity(0.0)

    def _on_close_request(self, window):
        async def close():
            await self.close_server()
            await self.cleanup_scrcpy()
        asyncio.create_task(close())
        return False

    # def close(self):
    #     # 避免重复关闭
    #     if self._is_closing:
    #         return
    #     self._is_closing = True

    #     # Clean up workspace manager first
    #     if hasattr(self, "workspace_manager"):
    #         self.workspace_manager.cleanup()

    #     # Clean up window's own event subscriptions
    #     self.event_bus.unsubscribe_by_subscriber(self)

    #     # 关闭服务器
    #     self.server.close()
    #     if not self.scrcpy_setup_task.done():
    #         self.scrcpy_setup_task.cancel()

    #     asyncio.create_task(self.cleanup_scrcpy())

    #     super().close()

    async def close_server(self):
        await self.server.close()

    async def cleanup_scrcpy(self):
        if not self.scrcpy_setup_task.done():
            self.scrcpy_setup_task.cancel()
        await self.adb_helper.remove_reverse_tunnel()

    async def setup_scrcpy(self):
        """Pushes scrcpy-server and starts it on the device, with retry logic."""
        await self.server.wait_started()

        if not self.server.server:
            return


        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                # 1. Connect to ADB device first
                if not await self.adb_helper.connect():
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    continue

                # 2. Get screen resolution. Not critical, so no retry on failure.
                screen_resolution = await self.adb_helper.get_screen_resolution()
                if screen_resolution:
                    ScreenInfo().set_resolution(screen_resolution[0], screen_resolution[1])

                # 3. Push server to device
                if not await self.adb_helper.push_scrcpy_server():
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    continue

                # 4. Generate SCID and setup reverse tunnel
                scid, socket_name = self.adb_helper.generate_scid()
                if not await self.adb_helper.reverse_tunnel(
                    socket_name, self.server.port
                ):
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    continue

                # 5. Start scrcpy-server on device
                if not await self.adb_helper.start_scrcpy_server(scid):
                    await asyncio.sleep(RETRY_DELAY_SECONDS)
                    continue

                return  # Exit on success

            except asyncio.CancelledError:
                return  # Use return to exit immediately on cancellation
            except Exception as e:
                await asyncio.sleep(RETRY_DELAY_SECONDS)


    def setup_mode_system(self):
        """Initializes the dual mode system"""
        # Listen for current_mode property changes
        self.connect("notify::current-mode", self._on_mode_changed)


    def setup_event_handlers(self):
        """Sets up event handlers"""
        # Example mappings for default handler
        # default_handler.add_key_mapping("T", lambda: print("🎮 Default: T key test"))
        # default_handler.add_key_mapping("G", lambda: print("🎮 Default: G key test"))
        # default_handler.add_mouse_mapping(2, lambda: print("🖱️ Default: middle click"))  # middle click
        pass


    def setup_window(self):
        """Sets window properties"""
        self.realize()
        self.set_decorated(False)
        self.maximize()

        self.set_name("transparent-window")

    def do_size_allocate(self, width:int, height:int, baseline:int):
        # Call parent's size_allocate first
        Adw.Window().do_size_allocate(self, width, height, baseline)
        sc = ScreenInfo()
        if self.is_maximized() and sc.host_width == 0 and sc.host_height == 0:
            width = self.get_allocated_width()
            height = self.get_allocated_height()
            
            self.set_default_size(width, height)
            self.set_size_request(width, height)
            sc.set_host_resolution(width, height)
            self.fixed.set_size_request(width, height)
            self.set_resizable(False)
            logger.info(f"Window maximized: {width} x {height}")

    def setup_ui(self):
        """Sets up the user interface"""
        # Main container is created and set in __init__

    def setup_controllers(self):
        """Sets up event controllers"""
        # Global keyboard events
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self.on_global_key_press)
        key_controller.connect("key-released", self.on_global_key_release)
        self.add_controller(key_controller)

        # Window-level mouse scroll events
        scroll_controller = Gtk.EventControllerScroll.new(
            flags=Gtk.EventControllerScrollFlags.BOTH_AXES
        )
        scroll_controller.connect("scroll-begin", self.on_window_mouse_scroll)
        scroll_controller.connect("scroll", self.on_window_mouse_scroll)
        scroll_controller.connect("scroll-end", self.on_window_mouse_scroll)
        self.add_controller(scroll_controller)

        # Window-level mouse event controller
        click_controller = Gtk.GestureClick()
        click_controller.set_button(0)  # All buttons
        click_controller.connect("pressed", self.on_window_mouse_pressed)
        click_controller.connect("released", self.on_window_mouse_released)
        self.add_controller(click_controller)

        # Window-level mouse motion events
        motion_controller = Gtk.EventControllerMotion.new()
        motion_controller.connect("motion", self.on_window_mouse_motion)
        self.add_controller(motion_controller)

        zoom_controller = Gtk.GestureZoom()
        zoom_controller.connect("begin", partial(self.on_window_mouse_zoom, status="begin"))
        zoom_controller.connect("scale-changed", partial(self.on_window_mouse_zoom, status="scale-changed"))
        zoom_controller.connect("end", partial(self.on_window_mouse_zoom, status="end"))
        self.add_controller(zoom_controller)

        # Initialize drag and resize states
        self.dragging_widget = None
        self.resizing_widget = None
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.resize_start_x = 0
        self.resize_start_y = 0
        self.resize_direction = None

        # Initialize interaction states
        self.selected_widget = None
        self.interaction_start_x = 0
        self.interaction_start_y = 0
        self.pending_resize_direction = None

    def on_window_mouse_pressed(self, controller, n_press, x, y):
        """Window-level mouse press event"""
        button = controller.get_current_button()

        # Use event handler chain in mapping mode
        if self.current_mode == self.MAPPING_MODE:

            # Create Key object for mouse button
            mouse_key = self.key_registry.create_mouse_key(button)

            # Create input event
            event = InputEvent(
                event_type="mouse_press",
                key=mouse_key,
                button=button,
                position=(int(x), int(y)),
                raw_data={"controller": controller, "n_press": n_press, "x": x, "y": y},
            )

            # Process with event handler chain
            handled = self.event_handler_chain.process_event(event)
            if handled:
                return True
            return

        # Mouse event handling in edit mode
        if button == Gdk.BUTTON_SECONDARY:  # Right click
            widget_at_position = self.workspace_manager.get_widget_at_position(x, y)
            if not widget_at_position:
                # Right click on blank area, show create menu
                self.menu_manager.show_widget_creation_menu(x, y, self.widget_factory)
            else:
                # Right click on widget, call widget's right-click callback
                local_x, local_y = self.workspace_manager.global_to_local_coords(
                    widget_at_position, x, y
                )
                if hasattr(widget_at_position, "on_widget_right_clicked"):
                    widget_at_position.on_widget_right_clicked(local_x, local_y)

        elif button == Gdk.BUTTON_PRIMARY:  # Left click
            if self.right_click_overlay.handle_edit_mouse_pressed(x, y, button):
                return True
            self.workspace_manager.handle_mouse_press(controller, n_press, x, y)

    def on_window_mouse_motion(self, controller, x, y):
        """Window-level mouse motion event"""
        if (
            self.right_click_overlay.active_widget is not None
            and getattr(self.right_click_overlay.active_widget, "is_calibrating", False)
        ):
            self.right_click_overlay.update_cursor((int(x), int(y)))
        elif self.right_click_overlay.is_tuning_active:
            self.right_click_overlay.update_cursor((int(x), int(y)))

        if self.current_mode == self.MAPPING_MODE:
            event = controller.get_current_event()
            state = event.get_modifier_state()
            # FIXME This mouse_key should actually be None, this is just for compatibility.
            # Right-click walking can be triggered when moving in the right-click down state.
            mouse_key = None
            button = None
            if state & Gdk.ModifierType.BUTTON1_MASK:
                mouse_key = self.key_registry.create_mouse_key(Gdk.BUTTON_PRIMARY)
                button = Gdk.BUTTON_PRIMARY
            elif state & Gdk.ModifierType.BUTTON2_MASK:
                mouse_key = self.key_registry.create_mouse_key(Gdk.BUTTON_MIDDLE)
                button = Gdk.BUTTON_MIDDLE
            elif state & Gdk.ModifierType.BUTTON3_MASK:
                mouse_key = self.key_registry.create_mouse_key(Gdk.BUTTON_SECONDARY)
                button = Gdk.BUTTON_SECONDARY

            event = InputEvent(
                event_type="mouse_motion",
                position=(int(x), int(y)),
                key=mouse_key,
                button=button,
                raw_data={"controller": controller, "x": x, "y": y},
            )
            # Skill casting and right-click walking
            self.event_bus.emit(Event(EventType.MOUSE_MOTION, self, event))
            self.event_handler_chain.process_event(event)
            return

        # In edit mode, delegate to workspace_manager
        if self.right_click_overlay.handle_edit_mouse_motion(x, y):
            return
        self.workspace_manager.handle_mouse_motion(controller, x, y)

    def on_window_mouse_scroll(
        self,
        controller: Gtk.EventControllerScroll,
        dx: float | None = None,
        dy: float | None = None,
    ):
        if self.current_mode == self.MAPPING_MODE:
            event = InputEvent(
                event_type="mouse_scroll",
                raw_data={"controller": controller, "dx": dx, "dy": dy},
            )
            self.event_handler_chain.process_event(event)

    def on_window_mouse_zoom(self, controller, zoom, status:str):
        event = InputEvent(
            event_type="mouse_zoom",
            raw_data={"controller": controller, "zoom": zoom, "status": status},
        )
        self.event_handler_chain.process_event(event)

    def fixed_put(self, widget, x, y):
        self.fixed.put(widget, x, y)
        widget.x = x
        widget.y = y

    def fixed_move(self, widget, x, y):
        self.fixed.move(widget, x, y)
        widget.x = x
        widget.y = y

    def get_widget_at_position(self, x, y):
        """Gets the component at the specified position"""
        child = self.fixed.get_first_child()
        while child:
            # Get component position and size
            child_x, child_y = self.fixed.get_child_position(child)
            child_width = child.get_allocated_width()
            child_height = child.get_allocated_height()

            # Check if click is within component bounds
            if is_point_in_rect(x, y, child_x, child_y, child_width, child_height):
                return child

            child = child.get_next_sibling()
        return None

    def global_to_local_coords(self, widget, global_x, global_y):
        """Converts global coordinates to widget internal coordinates"""
        widget_x, widget_y = self.fixed.get_child_position(widget)
        return global_x - widget_x, global_y - widget_y

    def handle_widget_interaction(self, widget, x, y, n_press=1):
        """Handles widget interaction - supports double-click detection"""

        # Convert to widget internal coordinates for edit state check
        local_x, local_y = self.global_to_local_coords(widget, x, y)

        # Check if widget has edit decorator and should keep edit state
        should_keep_editing = False
        if hasattr(widget, "should_keep_editing_on_click"):
            should_keep_editing = widget.should_keep_editing_on_click(local_x, local_y)

        if should_keep_editing:
            # If it should keep editing state, don't change selection state, and don't trigger bring to front
            # Set skip flag to avoid breaking edit state with delayed bring to front
            widget._skip_delayed_bring_to_front = True
            return  # Return directly, do not execute subsequent selection and bring to front logic
        else:
            # Normal selection logic
            # Unselect other widgets
            self.clear_all_selections()

            # Select current widget
            if hasattr(widget, "set_selected"):
                widget.set_selected(True)

        # Selection brings to front - using delayed method
        # Clear skip flag (if it exists), ensure normal bring to front works
        if hasattr(widget, "_skip_delayed_bring_to_front"):
            delattr(widget, "_skip_delayed_bring_to_front")

        self.schedule_bring_to_front(widget)

        # Convert to widget internal coordinates
        local_x, local_y = self.global_to_local_coords(widget, x, y)

        # Handle double-click event
        if n_press == 2:
            # When double-clicking, mark widget to avoid delayed bring to front operation
            if not hasattr(widget, "_skip_delayed_bring_to_front"):
                widget._skip_delayed_bring_to_front = True

            if hasattr(widget, "on_widget_double_clicked"):
                widget.on_widget_double_clicked(local_x, local_y)
            # Double click does not trigger bring to front when entering edit, to avoid interference with edit state
            return

        # Record the operation to be performed, but do not execute immediately
        self.selected_widget = widget
        self.interaction_start_x = x
        self.interaction_start_y = y

        # Check if it's a resize area
        if hasattr(widget, "check_resize_direction"):
            resize_direction = widget.check_resize_direction(local_x, local_y)
            if resize_direction:
                # When starting to resize, if the widget is in edit state, force exit edit
                if hasattr(widget, "should_keep_editing_on_click"):
                    # This means the widget has an edit decorator, force trigger selection change to exit edit
                    self.clear_all_selections()
                    widget.set_selected(True)

                self.pending_resize_direction = resize_direction
                return

        # Otherwise, prepare for drag
        self.pending_resize_direction = None

        # Call widget's click callback
        if hasattr(widget, "on_widget_clicked"):
            widget.on_widget_clicked(local_x, local_y)

    def on_window_mouse_released(self, controller, n_press, x, y):
        """Window-level mouse release event"""
        button = controller.get_current_button()

        # Use event handler chain in mapping mode
        if self.current_mode == self.MAPPING_MODE:

            # Create Key object for mouse button
            mouse_key = self.key_registry.create_mouse_key(button)

            # Create input event
            event = InputEvent(
                event_type="mouse_release",
                key=mouse_key,
                button=button,
                position=(int(x), int(y)),
                raw_data={"controller": controller, "n_press": n_press, "x": x, "y": y},
            )

            # Process with event handler chain
            handled = self.event_handler_chain.process_event(event)
            if handled:
                return True
            return

        # Mouse release handling in edit mode, delegate to workspace_manager
        if self.right_click_overlay.handle_edit_mouse_released(button):
            return True
        self.workspace_manager.handle_mouse_release(controller, n_press, x, y)

    def start_widget_drag(self, widget, x, y):
        """Starts dragging widget"""
        self.dragging_widget = widget
        self.drag_start_x = x
        self.drag_start_y = y

        # Bring widget to front when dragging - using safe method
        self.bring_widget_to_front_safe(widget)

    def start_widget_resize(self, widget, x, y, direction):
        """Starts resizing widget"""
        self.resizing_widget = widget
        self.resize_start_x = x
        self.resize_start_y = y
        self.resize_direction = direction

        if hasattr(widget, "start_resize"):
            local_x, local_y = self.global_to_local_coords(widget, x, y)
            widget.start_resize(local_x, local_y, direction)

    def handle_widget_drag(self, x, y):
        """Handles widget dragging"""
        if not self.dragging_widget:
            return

        dx = x - self.drag_start_x
        dy = y - self.drag_start_y

        # Get current position
        current_x, current_y = self.fixed.get_child_position(self.dragging_widget)
        new_x = current_x + dx
        new_y = current_y + dy

        # Limit within window bounds
        widget_bounds = self.dragging_widget.get_widget_bounds()
        window_width = self.get_allocated_width()
        window_height = self.get_allocated_height()

        new_x = max(0, min(new_x, window_width - widget_bounds[2]))
        new_y = max(0, min(new_y, window_height - widget_bounds[3]))

        # Move widget
        self.fixed_move(self.dragging_widget, new_x, new_y)

        # Update drag start point
        self.drag_start_x = x
        self.drag_start_y = y

    def handle_widget_resize(self, x, y):
        """Handles widget resizing"""
        if not self.resizing_widget or not hasattr(
            self.resizing_widget, "handle_resize_motion"
        ):
            return

        self.resizing_widget.handle_resize_motion(x, y)

    def bring_widget_to_front(self, widget):
        """Brings widget to front - using simple safe method"""
        # Simple method: only bring to front when dragging starts, to avoid bringing to front when selecting

    def bring_widget_to_front_safe(self, widget):
        """Safely brings widget to front - only used when dragging"""
        try:
            # Get current position
            x, y = self.fixed.get_child_position(widget)

            # Remove and re-add (only do this safely when dragging)
            self.fixed.remove(widget)
            self.fixed_put(widget, x, y)

            # Ensure drag state is correct
            self.dragging_widget = widget

        except Exception as e:
            logger.error(f"Error bringing widget to front: {e}")

    def schedule_bring_to_front(self, widget):
        """Delays bringing to front - to avoid state issues with immediate operations"""
        # Use GLib.idle_add to delay the bring to front operation
        GLib.idle_add(self._delayed_bring_to_front, widget)

    def _delayed_bring_to_front(self, widget):
        """Delays the bring to front operation"""
        try:
            # Check if delayed bring to front should be skipped (double-click to enter edit)
            if (
                hasattr(widget, "_skip_delayed_bring_to_front")
                and widget._skip_delayed_bring_to_front
            ):
                # Clear flag
                delattr(widget, "_skip_delayed_bring_to_front")
                return False

            # Check if widget still exists
            if widget.get_parent() != self.fixed:
                return False

            # Get current position
            x, y = self.fixed.get_child_position(widget)

            # Save selection state
            selected_state = getattr(widget, "is_selected", False)

            # Remove and re-add
            self.fixed.remove(widget)
            self.fixed_put(widget, x, y)

            # Restore selection state (only call if state actually changed, to avoid triggering unnecessary signals)
            if hasattr(widget, "set_selected"):
                current_state = getattr(widget, "is_selected", False)
                if current_state != selected_state:
                    widget.set_selected(selected_state)

        except Exception as e:
            logger.error(f"Error bringing widget to front: {e}")

        return False  # Do not repeat execution

    # def update_cursor_for_position(self, x, y):
    #     """Updates mouse cursor based on position - moved to workspace_manager"""
    #     pass  # This method has been moved to workspace_manager, keep empty method for compatibility

    # def get_cursor_name_for_resize_direction(self, direction):
    #     """Gets mouse cursor name based on resize direction"""
    #     cursor_map = {
    #         "se": "se-resize",
    #         "sw": "sw-resize",
    #         "ne": "ne-resize",
    #         "nw": "nw-resize",
    #         "e": "e-resize",
    #         "w": "w-resize",
    #         "s": "s-resize",
    #         "n": "n-resize",
    #     }
    #     return cursor_map.get(direction, "default")

    def clear_all_selections(self):
        """Clears the selected state of all components"""
        self.workspace_manager.clear_all_selections()

    def set_all_widgets_mapping_mode(self, mapping_mode: bool):
        """Sets the mapping mode for all widgets"""
        widget_count = 0
        child = self.fixed.get_first_child()
        while child:
            if hasattr(child, "set_mapping_mode"):
                child.set_mapping_mode(mapping_mode)
                widget_count += 1
            child = child.get_next_sibling()


    def create_widget_at_position(self, widget: "BaseWidget", x: int, y: int):
        """Creates a component at the specified position"""
        # Place component directly at the specified position
        self.fixed_put(widget, x, y)

        # Check if it's a multi-key mapping component (e.g., DirectionalPad)
        if hasattr(widget, "get_all_key_mappings"):
            # Register all keys for multi-key mapping components
            key_mappings = widget.get_all_key_mappings()
            success_count = 0
            total_count = len(key_mappings)

            for key_combination, direction in key_mappings.items():
                success = self.register_widget_key_mapping(widget, key_combination)
                if success:
                    success_count += 1

        elif hasattr(widget, "final_keys") and widget.final_keys:
            # Traditional single-key mapping components
            # Register directly using KeyCombination objects
            for key_combination in widget.final_keys:
                success = self.register_widget_key_mapping(widget, key_combination)
                if success:
                    # Update component display text to reflect registered keys
                    if hasattr(widget, "text") and not widget.text:
                        widget.text = str(key_combination)

    def on_clear_widgets(self, button: Gtk.Button | None):
        """Clears all components"""
        widgets_to_delete = []
        child = self.fixed.get_first_child()
        while child:
            widgets_to_delete.append(child)
            child = child.get_next_sibling()

        # Clean up key mappings for each widget, then remove from UI
        for widget in widgets_to_delete:
            # Clean up widget's key mappings
            self.unregister_widget_key_mapping(widget)
            # Remove widget from UI
            self.fixed.remove(widget)
            widget.on_delete()

        # Clear interaction states
        self.workspace_manager.dragging_widget = None
        self.workspace_manager.resizing_widget = None


    def get_physical_keyval(self, keycode):
        """Gets the standard keyval for the physical key (independent of modifier keys)"""
        try:
            display = self.get_display()
            if display:
                success, keyval, _, _, _ = display.translate_key(
                    keycode=keycode, state=Gdk.ModifierType(0), group=0
                )
                if success:
                    return Gdk.keyval_to_upper(keyval)
        except Exception as e:
            logger.error(f"Failed to get physical keyval: {e}")
        return 0

    def on_global_key_press(self, controller, keyval, keycode, state):
        """Global keyboard event - supports dual mode, uses event handler chain"""
        if self.right_click_overlay.handle_tuning_key(keyval, state):
            return True
        if self.right_click_overlay.handle_edit_key(keyval):
            return True
        if (
            keyval == Gdk.KEY_Escape
            and self.right_click_overlay.active_widget is not None
            and getattr(self.right_click_overlay.active_widget, "is_calibrating", False)
        ):
            cancel = getattr(self.right_click_overlay.active_widget, "cancel_calibration", None)
            if callable(cancel):
                cancel()
                return True
        if keyval == Gdk.KEY_Escape and self.active_settings_widget is not None:
            cancel_wizard = getattr(self.active_settings_widget, "cancel_ideal_calibration", None)
            if callable(cancel_wizard):
                cancel_wizard()
                return True
        if keyval == Gdk.KEY_Escape and self.active_settings_widget is not None:
            cancel_anchor_set = getattr(self.active_settings_widget, "cancel_anchor_set", None)
            if callable(cancel_anchor_set):
                cancel_anchor_set()
                return True

        # Special keys: mode switching and debug functions - these are directly judged by original keyval
        if keyval == Gdk.KEY_F1:
            # F1 switches between two modes
            if self.current_mode == self.EDIT_MODE:
                self.switch_mode(self.MAPPING_MODE)
            else:
                self.switch_mode(self.EDIT_MODE)
            return True
        # elif keyval == Gdk.KEY_F2:
        #     self.switch_mode(self.MAPPING_MODE)
        #     return True
        # elif keyval == Gdk.KEY_F3:
        #     # F3 displays current key mapping status
        #     self.print_key_mappings()
        #     return True
        # elif keyval == Gdk.KEY_F4:
        #     # F4 displays event handler status
        #     self.print_event_handlers_status()
        #     return True

        # Use event handler chain in mapping mode
        if self.current_mode == self.MAPPING_MODE:

            # Get standard keyval for physical key
            physical_keyval = self.get_physical_keyval(keycode)
            if physical_keyval == 0:
                # If failed to get, fallback to original keyval
                physical_keyval = keyval

            # Process modifier keys themselves
            if self._is_modifier_key(keyval):
                main_key = self.key_registry.create_from_keyval(keyval)
            else:
                main_key = self.key_registry.create_from_keyval(physical_keyval)

            if main_key:
                # Collect modifier keys
                modifiers = []
                if state & Gdk.ModifierType.CONTROL_MASK:
                    ctrl_key = self.key_registry.get_by_name("Ctrl_L")
                    if ctrl_key:
                        modifiers.append(ctrl_key)
                if state & Gdk.ModifierType.ALT_MASK:
                    alt_key = self.key_registry.get_by_name("Alt_L")
                    if alt_key:
                        modifiers.append(alt_key)
                if state & Gdk.ModifierType.SHIFT_MASK:
                    shift_key = self.key_registry.get_by_name("Shift_L")
                    if shift_key:
                        modifiers.append(shift_key)
                if state & Gdk.ModifierType.SUPER_MASK:
                    super_key = self.key_registry.get_by_name("Super_L")
                    if super_key:
                        modifiers.append(super_key)

                # Create input event
                event = InputEvent(
                    event_type="key_press",
                    key=main_key,
                    modifiers=modifiers,
                    raw_data={
                        "controller": controller,
                        "keyval": keyval,
                        "keycode": keycode,
                        "state": state,
                    },
                )

                # Process with event handler chain
                handled = self.event_handler_chain.process_event(event)
                if handled:
                    return True

        # General key handling in edit mode or mapping mode
        if keyval == Gdk.KEY_Escape:
            if self.current_mode == self.EDIT_MODE:
                # Edit mode: cancel all selections
                self.clear_all_selections()
            return True

        # Only handle edit-related keys in edit mode
        if self.current_mode == self.EDIT_MODE:
            if keyval == Gdk.KEY_Delete:
                # Delete key deletes selected widget
                self.workspace_manager.delete_selected_widgets()
                return True

        return False

    def delete_selected_widgets(self):
        """Deletes all selected widgets"""
        self.workspace_manager.delete_selected_widgets()

    # ===================Hint Information Methods====================

    def show_notification(self, text: str):
        """Shows a hint message with fade-out effect"""
        self.notification_label.set_label(text)

        # Stop any ongoing animations
        if (
            hasattr(self, "_notification_fade_out_timer")
            and self._notification_fade_out_timer > 0
        ):
            GLib.source_remove(self._notification_fade_out_timer)
        if hasattr(self, "_notification_animation"):
            self._notification_animation.reset()

        # Fade-in animation
        self.notification_box.set_opacity(0)
        animation_target = PropertyAnimationTarget(
            self.notification_box, "opacity"
        )
        self._notification_animation = Adw.TimedAnimation.new(
            self.notification_box, 0.0, 1.0, 300, animation_target
        )
        self._notification_animation.set_easing(Adw.Easing.LINEAR)
        self._notification_animation.play()

        # Plan fade-out
        self._notification_fade_out_timer = GLib.timeout_add(
            1500, self._fade_out_notification
        )

    def _fade_out_notification(self):
        """Executes fade-out animation"""
        animation_target = PropertyAnimationTarget(
            self.notification_box, "opacity"
        )
        self._notification_animation = Adw.TimedAnimation.new(
            self.notification_box, 1.0, 0.0, 500, animation_target
        )
        self._notification_animation.set_easing(Adw.Easing.LINEAR)
        self._notification_animation.play()
        self._notification_fade_out_timer = 0
        return GLib.SOURCE_REMOVE

    # ===================Dual Mode System Methods====================

    def _on_mode_changed(self, widget, pspec):
        """Callback when mode property changes"""
        new_mode = self.current_mode

        # Notify all widgets to switch drawing mode
        mapping_mode = new_mode == self.MAPPING_MODE
        self.set_all_widgets_mapping_mode(mapping_mode)
        self.right_click_overlay.set_mapping_mode(mapping_mode)

        # Adjust UI state based on new mode
        if new_mode == self.MAPPING_MODE:
            # Enter mapping mode: cancel all selections, disable edit functions
            self.clear_all_selections()

            self.show_notification(_("Mapping Mode (F1: Switch Mode)"))

            # Add more UI adjustments for mapping mode here
            # e.g., change window title, display status indicator, etc.
            self.set_title(f"{APP_TITLE} - Mapping Mode (F1: Switch Mode)")
            self.set_cursor_from_name("default")


        else:
            # Enter edit mode: restore edit functions
            self.show_notification(_("Edit Mode (F1: Switch Mode)"))
            self.set_title(f"{APP_TITLE} - Edit Mode (F1: Switch Mode)")

            # Display edit mode help information
            self.event_bus.emit(Event(EventType.EXIT_STARING, self, None))

    def switch_mode(self, new_mode):
        """Switches mode"""
        if new_mode not in [self.EDIT_MODE, self.MAPPING_MODE]:
            return False

        if self.current_mode == new_mode:
            return True


        # Use property system to set mode, which will trigger _on_mode_changed callback
        self.set_property("current-mode", new_mode)

        return True

    def format_key_combination(self, keyval, state) -> KeyCombination:
        """Formats key event into KeyCombination"""
        keys = []

        # Add modifier keys
        if state & Gdk.ModifierType.CONTROL_MASK:
            ctrl_key = self.key_registry.get_by_name("Ctrl")
            if ctrl_key:
                keys.append(ctrl_key)
        if state & Gdk.ModifierType.ALT_MASK:
            alt_key = self.key_registry.get_by_name("Alt")
            if alt_key:
                keys.append(alt_key)
        if state & Gdk.ModifierType.SHIFT_MASK:
            shift_key = self.key_registry.get_by_name("Shift")
            if shift_key:
                keys.append(shift_key)
        if state & Gdk.ModifierType.SUPER_MASK:
            super_key = self.key_registry.get_by_name("Super")
            if super_key:
                keys.append(super_key)

        # Get main key
        main_key = self.key_registry.create_from_keyval(keyval, state)
        if main_key:
            keys.append(main_key)

        return KeyCombination(keys)

    def register_widget_key_mapping(
        self, widget, key_combination: KeyCombination
    ) -> bool:
        """Registers widget's key mapping"""
        # Automatically read widget's reentrant attribute
        reentrant = getattr(widget, "IS_REENTRANT", False)
        return self.key_mapping_manager.subscribe(
            widget, key_combination, reentrant=reentrant
        )

    def unregister_widget_key_mapping(self, widget) -> bool:
        """Unsubscribes all key mappings for a widget"""
        return self.key_mapping_manager.unsubscribe(widget)

    def unregister_single_widget_key_mapping(
        self, widget, key_combination: KeyCombination
    ) -> bool:
        """Unsubscribes a single key mapping for a widget"""
        return self.key_mapping_manager.unsubscribe_key(widget, key_combination)

    def get_widget_key_mapping(self, widget) -> list[KeyCombination]:
        """Gets the list of key mappings for a specified widget"""
        return self.key_mapping_manager.get_subscriptions(widget)

    def print_key_mappings(self):
        """Prints all current key mappings (for debugging)"""
        self.key_mapping_manager.print_mappings()

    def clear_all_key_mappings(self):
        """Clears all key mappings"""
        return self.key_mapping_manager.clear()

    def on_global_key_release(self, controller, keyval, keycode, state):
        """Global key release event - uses event handler chain"""
        if self.current_mode == self.MAPPING_MODE:
            # Get standard keyval for physical key
            physical_keyval = self.get_physical_keyval(keycode)
            if physical_keyval == 0:
                # If failed to get, fallback to original keyval
                physical_keyval = keyval

            # Process modifier keys themselves
            if self._is_modifier_key(keyval):
                main_key = self.key_registry.create_from_keyval(keyval)
            else:
                main_key = self.key_registry.create_from_keyval(physical_keyval)

            if main_key:
                # Collect modifier keys
                modifiers = []
                if state & Gdk.ModifierType.CONTROL_MASK:
                    ctrl_key = self.key_registry.get_by_name("Ctrl_L")
                    if ctrl_key:
                        modifiers.append(ctrl_key)
                if state & Gdk.ModifierType.ALT_MASK:
                    alt_key = self.key_registry.get_by_name("Alt_L")
                    if alt_key:
                        modifiers.append(alt_key)
                if state & Gdk.ModifierType.SHIFT_MASK:
                    shift_key = self.key_registry.get_by_name("Shift_L")
                    if shift_key:
                        modifiers.append(shift_key)
                if state & Gdk.ModifierType.SUPER_MASK:
                    super_key = self.key_registry.get_by_name("Super_L")
                    if super_key:
                        modifiers.append(super_key)

                # Create input event
                event = InputEvent(
                    event_type="key_release",
                    key=main_key,
                    modifiers=modifiers,
                    raw_data={
                        "controller": controller,
                        "keyval": keyval,
                        "keycode": keycode,
                        "state": state,
                    },
                )

                # Process with event handler chain
                handled = self.event_handler_chain.process_event(event)
                if handled:
                    return True

        return False

    def _is_modifier_key(self, keyval):
        """Checks if it's a modifier key"""
        modifier_keys = {
            Gdk.KEY_Control_L,
            Gdk.KEY_Control_R,
            Gdk.KEY_Alt_L,
            Gdk.KEY_Alt_R,
            Gdk.KEY_Shift_L,
            Gdk.KEY_Shift_R,
            Gdk.KEY_Super_L,
            Gdk.KEY_Super_R,
            Gdk.KEY_Meta_L,
            Gdk.KEY_Meta_R,
            Gdk.KEY_Hyper_L,
            Gdk.KEY_Hyper_R,
        }
        return keyval in modifier_keys

    def get_key_mapping_size(self):
        return self._key_mapping_width, self._key_mapping_height
    # def print_event_handlers_status(self):
    #     """Prints event handler status (for debugging)"""
    #     print(f"\n[DEBUG] ==================Event handler status==================")
    #     print(
    #         f"[DEBUG] Event handler chain status: {'Enabled' if self.event_handler_chain.enabled else 'Disabled'}"
    #     )

    #     handlers_info = self.event_handler_chain.get_handlers_info()
    #     for info in handlers_info:
    #         status = "Enabled" if info["enabled"] else "Disabled"
    #         print(f"[DEBUG] - {info['name']}: Priority={info['priority']}, Status={status}")

    #     # Display default handler's mappings
    #     print(
    #         f"[DEBUG] Default handler key mappings: {list(self.default_handler.key_mappings.keys())}"
    #     )
    #     print(
    #         f"[DEBUG] Default handler mouse mappings: {list(self.default_handler.mouse_mappings.keys())}"
    #     )
    #     print(f"[DEBUG] ================================================\n")


class KeyMapper(Adw.Application):
    def __init__(self, display_name: str):
        # 将 display_name 转换为有效的 application ID 格式
        # 替换无效字符并确保符合 D-Bus 规范
        sanitized_display = display_name.replace(":", "_").replace("/", "_").replace("-", "_")
        super().__init__(application_id=f"com.jaoushingan.WaydroidHelper.KeyMapper.{sanitized_display}")
        self.display_name = display_name
        self.window = None

    def do_activate(self):
        self.window = TransparentWindow(self, self.display_name)
        self.window.present()
    
        # 捕获 SIGTERM
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.on_sigterm)

    async def _do_shutdown(self) -> None:
        if self.window:
            self.window.on_clear_widgets(None)
            await self.window.close_server()
            await self.window.cleanup_scrcpy()
        self.quit()   # 在清理结束后再退出

    def on_sigterm(self):
        # 只调度异步任务，不要直接退出
        asyncio.create_task(self._do_shutdown())
        return True

def create_keymapper(display_name: str):
    asyncio.set_event_loop_policy(
        GLibEventLoopPolicy()  # pyright:ignore[reportUnknownArgumentType]
    )
    app = KeyMapper(display_name)
    app.run()
