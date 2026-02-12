#!/usr/bin/env python3
"""
动态菜单管理
根据发现的组件自动生成菜单项
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from gettext import gettext as _
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import gi
from gi.repository import Adw, Gdk, Gtk, GLib, Pango, GObject

from waydroid_helper.controller.core.control_msg import ScreenInfo
from waydroid_helper.controller.core.key_system import Key, KeyCombination, KeyRegistry
from waydroid_helper.util.log import logger
from waydroid_helper.controller.widgets.base import BaseWidget
from waydroid_helper.config.file_manager import ConfigManager as FileConfigManager

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")

if TYPE_CHECKING:
    from waydroid_helper.controller.app.window import TransparentWindow
    from waydroid_helper.controller.widgets.factory import WidgetFactory


class ContextMenuManager:
    """动态上下文菜单管理器"""

    DEFAULT_PROFILE_NAME = "Default"
    CURRENT_PROFILE_STATE_NAME = "current_profile"

    def __init__(self, parent_window: "TransparentWindow"):
        self.parent_window: "TransparentWindow" = parent_window
        self._popover: "Gtk.Popover | None" = None
        self._main_box: "Gtk.Box | None" = None
        self._flow_box: "Gtk.FlowBox | None" = None
        self._tool_flow: "Gtk.FlowBox | None" = None
        self.screen_info = ScreenInfo()
        self._config_manager = FileConfigManager()
        self._current_profile = self._load_current_profile()
        self._profile_manager_window: "Adw.Window | None" = None
        self._profile_hotkey: "KeyCombination | None" = self._load_profile_hotkey()
        self._profile_manager_css_provider: "Gtk.CssProvider | None" = None

    def show_widget_creation_menu(
        self, x: int, y: int, widget_factory: "WidgetFactory"
    ):
        """显示动态生成的组件创建菜单（网格布局）"""
        # 如果 popover 不存在，创建一个新的
        if self._popover is None:
            self._create_popover()

        # 更新菜单内容
        self._update_menu_content(x, y, widget_factory)

        # 设置菜单位置
        rect = Gdk.Rectangle()
        # https://gitlab.gnome.org/GNOME/gtk/-/issues/4563#note_1711746
        rect.x = int(x)
        rect.y = int(y)
        rect.width = 1
        rect.height = 1
        self._popover.set_pointing_to(rect)
        self._popover.popup()

    def _create_popover(self):
        """创建可复用的 popover 结构"""
        self._popover = Gtk.Popover()
        self._popover.set_parent(self.parent_window)
        self._popover.set_has_arrow(False)
        self._popover.set_autohide(True)

        # 创建主容器
        self._main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._popover.set_child(self._main_box)

        # 创建滚动窗口
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_max_content_height(300)  # 限制最大高度
        scrolled.set_max_content_width(400)  # 限制最大宽度
        scrolled.set_propagate_natural_height(True)
        scrolled.set_propagate_natural_width(True)
        self._main_box.append(scrolled)

        # 创建网格容器
        self._flow_box = Gtk.FlowBox()
        self._flow_box.set_orientation(Gtk.Orientation.HORIZONTAL)
        self._flow_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self._flow_box.set_column_spacing(4)
        self._flow_box.set_row_spacing(4)
        self._flow_box.set_margin_top(8)
        self._flow_box.set_margin_bottom(8)
        self._flow_box.set_margin_start(8)
        self._flow_box.set_margin_end(8)
        self._flow_box.set_min_children_per_line(2)
        self._flow_box.set_max_children_per_line(4)  # 最多4列
        scrolled.set_child(self._flow_box)

        # 添加分隔线
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(4)
        separator.set_margin_bottom(4)
        self._main_box.append(separator)

        # 创建工具菜单容器
        tool_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        tool_box.set_margin_top(4)
        tool_box.set_margin_bottom(8)
        tool_box.set_margin_start(8)
        tool_box.set_margin_end(8)
        self._main_box.append(tool_box)

        # 创建工具按钮的网格
        self._tool_flow = Gtk.FlowBox()
        self._tool_flow.set_orientation(Gtk.Orientation.HORIZONTAL)
        self._tool_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self._tool_flow.set_column_spacing(4)
        self._tool_flow.set_row_spacing(4)
        self._tool_flow.set_min_children_per_line(3)
        self._tool_flow.set_max_children_per_line(5)
        tool_box.append(self._tool_flow)

    def _clear_flow_box(self, flow_box: "Gtk.FlowBox | None"):
        """清空 FlowBox 中的所有子组件"""
        if flow_box is None:
            return
        child = flow_box.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            flow_box.remove(child)
            child = next_child

    def _update_menu_content(self, x: int, y: int, widget_factory: "WidgetFactory"):
        """更新菜单内容"""
        # 清空现有内容
        self._clear_flow_box(self._flow_box)
        self._clear_flow_box(self._tool_flow)

        # 确保组件已初始化
        if self._flow_box is None or self._tool_flow is None or self._popover is None:
            return

        # 动态生成组件菜单项
        available_types = widget_factory.get_available_types()

        # 过滤掉不允许通过右键菜单创建的组件
        filtered_types = []
        for widget_type in available_types:
            widget_class = widget_factory.widget_classes.get(widget_type)
            if widget_class and getattr(
                widget_class, "ALLOW_CONTEXT_MENU_CREATION", True
            ):
                filtered_types.append(widget_type)

        if not filtered_types:
            # 如果没有发现任何可创建的组件，显示提示
            label = Gtk.Label(label=_("No widgets found"))
            label.set_margin_top(20)
            label.set_margin_bottom(20)
            self._flow_box.append(label)
        else:
            # 为每个发现的组件类型创建紧凑的按钮
            for widget_type in sorted(filtered_types):
                metadata = widget_factory.get_widget_metadata(widget_type)

                # 使用metadata中的名称，如果没有则使用类型名
                display_name = metadata.get("name", widget_type.title())

                # 创建紧凑的按钮
                button = Gtk.Button(label=str(display_name))
                button.set_size_request(100, 40)  # 固定大小，更紧凑
                button.connect(
                    "clicked",
                    lambda btn, wtype=widget_type: [
                        self._create_widget_callback(wtype, x, y, widget_factory),
                        self._popover.popdown(),
                    ],
                )

                # 添加到网格
                self._flow_box.append(button)

        # 添加工具菜单项（使用更紧凑的布局）
        tool_items = [
            (_("Refresh widgets"), lambda: self._refresh_widgets(widget_factory)),
            # (_("Show widget info"), lambda: self._show_widget_info(widget_factory)),
            (_("Clear all"), lambda: self._clear_all_widgets()),
            (_("Profiles"), lambda: self._show_profile_manager(widget_factory)),
        ]

        for label, callback in tool_items:
            button = Gtk.Button(label=label)
            button.set_size_request(70, 35)  # 更小的工具按钮
            button.connect(
                "clicked", lambda btn, cb=callback: [cb(), self._popover.popdown()]
            )
            self._tool_flow.append(button)

    def _create_widget_callback(
        self, widget_type: str, x: int, y: int, widget_factory: "WidgetFactory"
    ):
        """创建组件的回调函数"""
        try:
            widget = widget_factory.create_widget(
                widget_type,
                x=x,
                y=y,
                event_bus=self.parent_window.event_bus,
                pointer_id_manager=self.parent_window.pointer_id_manager,
                key_registry=self.parent_window.key_registry,
            )
            if widget:
                self.parent_window.create_widget_at_position(widget, x, y)
        except Exception as e:
            logger.error(f"Error creating {widget_type} widget: {e}")

    def _refresh_widgets(self, widget_factory: "WidgetFactory"):
        """刷新组件列表"""
        widget_factory.reload_widgets()
        widget_factory.print_discovered_widgets()

    def _show_widget_info(self, widget_factory: "WidgetFactory"):
        """显示组件信息"""
        widget_factory.print_discovered_widgets()

    def _clear_all_widgets(self):
        """清空所有组件"""
        self.parent_window.on_clear_widgets(None)

    def _get_available_screen_size(self):
        return self.screen_info.get_host_resolution()

    def _serialize_key_combination(self, key_combination: KeyCombination) -> list[str]:
        """序列化按键组合为字符串列表"""
        if not key_combination:
            return []
        return [str(key) for key in key_combination.keys]

    def _ensure_profile_manager_css(self) -> None:
        if self._profile_manager_css_provider is not None:
            return
        display = self.parent_window.get_display()
        if display is None:
            return

        css = """
        button.profile-hotkey-input {
            background-color: rgba(128, 128, 128, 0.42);
            background-image: none;
            border-radius: 999px;
            border: 1px solid rgba(80, 80, 80, 0.30);
            box-shadow: none;
        }
        button.profile-hotkey-input:hover {
            background-color: rgba(96, 96, 96, 0.52);
            background-image: none;
        }
        """

        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_display(
            display,
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self._profile_manager_css_provider = provider

    def _deserialize_key_combination(
        self, key_names: list[str]
    ) -> "KeyCombination | None":
        """从字符串列表反序列化按键组合"""
        keys: list[Key] = []
        for key_name in key_names:
            key = self.parent_window.key_registry.deserialize_key(key_name)
            if key:
                keys.append(key)
        return KeyCombination(keys) if keys else None

    # TODO 在每个 widget 内部单独实现序列化/反序列化

    def _get_profiles_dir(self) -> str:
        """获取默认的配置文件目录"""
        config_dir = os.getenv("XDG_CONFIG_HOME", GLib.get_user_config_dir())
        profiles_dir = os.path.join(config_dir, "waydroid-helper", "Profiles")
        os.makedirs(profiles_dir, exist_ok=True)
        return profiles_dir

    def _profile_config_key(self) -> str:
        return "controller.widget_profiles.current"

    def _profile_hotkey_config_key(self) -> str:
        return "controller.widget_profiles.hotkey"

    def _load_profile_hotkey(self) -> "KeyCombination | None":
        raw_value = self._config_manager.get_value(self._profile_hotkey_config_key(), [])
        if not isinstance(raw_value, list):
            return None
        key_names = [name for name in raw_value if isinstance(name, str)]
        hotkey = self._deserialize_key_combination(key_names)
        return hotkey if hotkey and len(hotkey) > 0 else None

    def _save_profile_hotkey(self, hotkey: "KeyCombination | None") -> None:
        serialized = self._serialize_key_combination(hotkey)
        self._config_manager.set_value(self._profile_hotkey_config_key(), serialized)
        self._profile_hotkey = hotkey if hotkey and len(hotkey) > 0 else None

    def _get_hotkey_display_text(self) -> str:
        if self._profile_hotkey is None or len(self._profile_hotkey) == 0:
            return ""
        return self._profile_hotkey.display_text

    def _build_key_combination_from_event(
        self, keyval: int, keycode: int, state: int
    ) -> "KeyCombination | None":
        main_keyval = keyval
        get_physical = getattr(self.parent_window, "get_physical_keyval", None)
        if callable(get_physical):
            physical_keyval = get_physical(keycode)
            if physical_keyval:
                if keyval in (Gdk.KEY_Control_L, Gdk.KEY_Control_R, Gdk.KEY_Alt_L, Gdk.KEY_Alt_R,
                              Gdk.KEY_Shift_L, Gdk.KEY_Shift_R, Gdk.KEY_Super_L, Gdk.KEY_Super_R):
                    main_keyval = keyval
                else:
                    main_keyval = physical_keyval

        keys: list[Key] = []
        if state & Gdk.ModifierType.CONTROL_MASK:
            ctrl_key = self.parent_window.key_registry.get_by_name("Ctrl_L")
            if ctrl_key:
                keys.append(ctrl_key)
        if state & Gdk.ModifierType.ALT_MASK:
            alt_key = self.parent_window.key_registry.get_by_name("Alt_L")
            if alt_key:
                keys.append(alt_key)
        if state & Gdk.ModifierType.SHIFT_MASK:
            shift_key = self.parent_window.key_registry.get_by_name("Shift_L")
            if shift_key:
                keys.append(shift_key)
        if state & Gdk.ModifierType.SUPER_MASK:
            super_key = self.parent_window.key_registry.get_by_name("Super_L")
            if super_key:
                keys.append(super_key)

        main_key = self.parent_window.key_registry.create_from_keyval(main_keyval)
        if main_key and main_key not in keys:
            keys.append(main_key)

        if not keys:
            return None
        return KeyCombination(keys)

    def handle_profile_hotkey_press(
        self, keyval: int, keycode: int, state: int, widget_factory: "WidgetFactory"
    ) -> bool:
        if self._profile_hotkey is None or len(self._profile_hotkey) == 0:
            return False

        pressed = self._build_key_combination_from_event(keyval, keycode, state)
        if pressed is None or str(pressed) != str(self._profile_hotkey):
            return False

        self._show_profile_manager(widget_factory)
        return True

    def _current_profile_state_path(self) -> Path:
        return Path(self._get_profiles_dir()) / f"{self.CURRENT_PROFILE_STATE_NAME}.json"

    def _write_current_profile_state(self, profile_name: str) -> None:
        ordered_profiles = [
            name
            for name in self._get_profile_order()
            if name and name != self.CURRENT_PROFILE_STATE_NAME
        ]
        state_path = self._current_profile_state_path()
        payload = {
            "current_profile": profile_name,
            "profile_order": ordered_profiles,
        }
        temp_path = state_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, state_path)
        except Exception as e:
            logger.error(f"Failed to save profile state: {e}")

    def _load_current_profile(self) -> str:
        state_path = self._current_profile_state_path()
        if state_path.exists():
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                saved_profile = self._normalize_profile_name(
                    data.get("current_profile", "")
                )
                if saved_profile:
                    return saved_profile
            except Exception as e:
                logger.error(f"Failed to load profile state: {e}")

        profile = self.DEFAULT_PROFILE_NAME
        self._write_current_profile_state(profile)
        return profile

    def _get_profile_order(self) -> list[str]:
        state_path = self._current_profile_state_path()
        if not state_path.exists():
            return []
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stored_order = data.get("profile_order")
            if isinstance(stored_order, list):
                return [
                    name
                    for name in stored_order
                    if isinstance(name, str)
                    and name
                    and name != self.CURRENT_PROFILE_STATE_NAME
                ]
        except Exception as e:
            logger.error(f"Failed to load profile order: {e}")
        return []

    def _set_current_profile(self, profile_name: str) -> None:
        self._current_profile = profile_name
        self._config_manager.set_value(self._profile_config_key(), profile_name)
        self._write_current_profile_state(profile_name)

    def _normalize_profile_name(self, profile_name: str) -> str | None:
        cleaned = "".join(ch for ch in profile_name if ch not in "/\\").strip()
        if cleaned == self.CURRENT_PROFILE_STATE_NAME:
            return None
        return cleaned or None

    def _profile_path(self, profile_name: str) -> Path:
        return Path(self._get_profiles_dir()) / f"{profile_name}.json"

    def _list_profiles(self) -> list[str]:
        profiles_dir = Path(self._get_profiles_dir())
        profile_names = {
            path.stem
            for path in profiles_dir.glob("*.json")
            if path.is_file() and path.stem != self.CURRENT_PROFILE_STATE_NAME
        }
        profile_names.add(self.DEFAULT_PROFILE_NAME)

        saved_order = self._get_profile_order()
        ordered = [name for name in saved_order if name in profile_names]
        ordered.extend(name for name in sorted(profile_names) if name not in ordered)
        return ordered

    def _save_profile_order(self, ordered_profiles: list[str]) -> None:
        existing_profiles = set(self._list_profiles())
        sanitized = [
            name for name in ordered_profiles if name in existing_profiles and name
        ]
        for name in self._list_profiles():
            if name not in sanitized:
                sanitized.append(name)

        state_path = self._current_profile_state_path()
        payload = {
            "current_profile": self._current_profile,
            "profile_order": sanitized,
        }
        temp_path = state_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, state_path)
        except Exception as e:
            logger.error(f"Failed to save profile order: {e}")

    def _build_layout_data(self) -> dict[str, Any]:
        """Collect layout data from current widgets."""
        screen_width, screen_height = self._get_available_screen_size()
        widgets_data = []
        child = self.parent_window.fixed.get_first_child()
        while child:
            if hasattr(child, "get_widget_bounds"):
                x, y, width, height = child.get_widget_bounds()
            else:
                if hasattr(self.parent_window.fixed, "get_child_position"):
                    x, y = self.parent_window.fixed.get_child_position(child)
                else:
                    x, y = child.x, child.y
                width = child.get_allocated_width()
                height = child.get_allocated_height()
                if width <= 0:
                    width = child.width
                if height <= 0:
                    height = child.height
            widget_type = type(child).__name__.lower()

            widget_data: dict[str, Any] = {
                "type": widget_type,
                "x": float(x),
                "y": float(y),
                "width": float(width),
                "height": float(height),
            }

            if hasattr(child, "text") and child.text:
                widget_data["text"] = str(child.text)

            if widget_type == "directionalpad":
                if hasattr(child, "direction_keys") and child.direction_keys:
                    widget_data["direction_keys"] = {
                        "up": self._serialize_key_combination(
                            child.direction_keys["up"]
                        ),
                        "down": self._serialize_key_combination(
                            child.direction_keys["down"]
                        ),
                        "left": self._serialize_key_combination(
                            child.direction_keys["left"]
                        ),
                        "right": self._serialize_key_combination(
                            child.direction_keys["right"]
                        ),
                    }
            else:
                if hasattr(child, "final_keys") and child.final_keys:
                    widget_data["default_keys"] = [
                        self._serialize_key_combination(kc)
                        for kc in child.final_keys
                    ]

            if hasattr(child, "get_config_manager"):
                config_manager = child.get_config_manager()
                if config_manager.configs:
                    widget_data["config"] = config_manager.serialize()

            widgets_data.append(widget_data)
            child = child.get_next_sibling()

        return {
            "version": BaseWidget.WIDGET_VERSION,
            "screen_resolution": {"width": screen_width, "height": screen_height},
            "widgets": widgets_data,
            "created_at": datetime.now().isoformat(),
        }

    def _apply_layout_data(
        self, layout_data: dict[str, Any], widget_factory: "WidgetFactory"
    ) -> None:
        """Apply layout data to current canvas."""
        if "widgets" not in layout_data:
            logger.error("Invalid layout file format")
            return

        if layout_data.get("version") != BaseWidget.WIDGET_VERSION:
            logger.warning(
                "Layout file version mismatch: %s != %s",
                layout_data.get("version"),
                BaseWidget.WIDGET_VERSION,
            )

        current_screen_width, current_screen_height = (
            self._get_available_screen_size()
        )

        scale_x = 1.0
        scale_y = 1.0
        saved_resolution = layout_data.get("screen_resolution")

        if saved_resolution:
            saved_width = saved_resolution.get("width", current_screen_width)
            saved_height = saved_resolution.get("height", current_screen_height)
            scale_x = current_screen_width / saved_width
            scale_y = current_screen_height / saved_height

        if hasattr(self.parent_window, "on_clear_widgets"):
            self.parent_window.on_clear_widgets(None)

        for widget_data in layout_data.get("widgets", []):
            try:
                widget_type = widget_data.get("type", "")
                original_x = widget_data.get("x", 0)
                original_y = widget_data.get("y", 0)
                original_width = widget_data.get("width", 100)
                original_height = widget_data.get("height", 100)
                text = widget_data.get("text", "")

                x = int(original_x * scale_x)
                y = int(original_y * scale_y)
                width = int(original_width * scale_x)
                height = int(original_height * scale_y)

                create_kwargs = {
                    "width": width,
                    "height": height,
                    "text": text,
                    "event_bus": self.parent_window.event_bus,
                    "pointer_id_manager": self.parent_window.pointer_id_manager,
                    "key_registry": self.parent_window.key_registry,
                }

                if widget_type == "directionalpad":
                    if "direction_keys" in widget_data:
                        create_kwargs["direction_keys"] = {
                            "up": self._deserialize_key_combination(
                                widget_data["direction_keys"]["up"]
                            ),
                            "down": self._deserialize_key_combination(
                                widget_data["direction_keys"]["down"]
                            ),
                            "left": self._deserialize_key_combination(
                                widget_data["direction_keys"]["left"]
                            ),
                            "right": self._deserialize_key_combination(
                                widget_data["direction_keys"]["right"]
                            ),
                        }
                else:
                    default_keys = []
                    if "default_keys" in widget_data:
                        for key_names in widget_data["default_keys"]:
                            key_combo = self._deserialize_key_combination(key_names)
                            if key_combo:
                                default_keys.append(key_combo)
                    create_kwargs["default_keys"] = default_keys

                widget = widget_factory.create_widget(widget_type, **create_kwargs)

                if widget:
                    if hasattr(self.parent_window, "create_widget_at_position"):
                        self.parent_window.create_widget_at_position(widget, x, y)

                        if "config" in widget_data and hasattr(
                            widget, "get_config_manager"
                        ):
                            config_manager = widget.get_config_manager()
                            config_manager.deserialize(widget_data["config"])

            except Exception as e:
                logger.error(f"Failed to create widget: {e}")
                continue

    def _save_layout_to_path(
        self, file_path: str, profile_name: str | None = None
    ) -> None:
        """Save layout data to a file path."""
        try:
            layout_data = self._build_layout_data()
            if profile_name:
                layout_data["profile_name"] = profile_name
                layout_data["updated_at"] = datetime.now().isoformat()
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(layout_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save layout: {e}")

    def _load_layout_from_path(
        self, file_path: str, widget_factory: "WidgetFactory"
    ) -> None:
        """Load layout data from a file path."""
        if not Path(file_path).exists():
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                layout_data = json.load(f)
            self._apply_layout_data(layout_data, widget_factory)
        except Exception as e:
            logger.error(f"Failed to load layout: {e}")

    def save_current_profile(self) -> None:
        """Persist current layout to the active profile."""
        profile_name = self._normalize_profile_name(self._current_profile)
        if not profile_name:
            return
        self._save_layout_to_path(
            str(self._profile_path(profile_name)), profile_name=profile_name
        )

    def load_current_profile(self, widget_factory: "WidgetFactory") -> None:
        """Load the active profile if it exists."""
        profile_name = self._normalize_profile_name(self._current_profile)
        if not profile_name:
            return
        profile_path = self._profile_path(profile_name)
        if profile_path.exists():
            self._load_layout_from_path(str(profile_path), widget_factory)
        else:
            self._set_current_profile(profile_name)

    def _switch_profile(self, profile_name: str, widget_factory: "WidgetFactory") -> None:
        normalized = self._normalize_profile_name(profile_name)
        if not normalized:
            self.parent_window.show_notification(_("Profile name cannot be empty"))
            return

        if normalized == self._current_profile:
            self.parent_window.show_notification(_("Profile already selected"))
            return
        profile_path = self._profile_path(normalized)
        if profile_path.exists():
            self._load_layout_from_path(str(profile_path), widget_factory)
        else:
            self.parent_window.on_clear_widgets(None)
        self._set_current_profile(normalized)
        self.parent_window.show_notification(
            _("Switched to profile: %s") % normalized
        )

    def _update_profile(self, profile_name: str) -> None:
        normalized = self._normalize_profile_name(profile_name)
        if not normalized:
            self.parent_window.show_notification(_("Profile name cannot be empty"))
            return
        self._save_layout_to_path(
            str(self._profile_path(normalized)), profile_name=normalized
        )
        self._set_current_profile(normalized)
        self.parent_window.show_notification(_("Profile updated"))

    def _create_profile(self, profile_name: str, widget_factory: "WidgetFactory") -> None:
        normalized = self._normalize_profile_name(profile_name)
        if not normalized:
            self.parent_window.show_notification(_("Profile name cannot be empty"))
            return
        profile_path = self._profile_path(normalized)
        if profile_path.exists():
            self.parent_window.show_notification(_("Profile already exists"))
            return
        self._save_layout_to_path(str(profile_path), profile_name=normalized)
        self._set_current_profile(normalized)
        self.parent_window.show_notification(
            _("Profile created: %s") % normalized
        )
        self._load_layout_from_path(str(profile_path), widget_factory)

    def _rename_profile(self, old_name: str, new_name: str) -> None:
        normalized_old = self._normalize_profile_name(old_name)
        normalized_new = self._normalize_profile_name(new_name)
        if not normalized_old or not normalized_new:
            self.parent_window.show_notification(_("Profile name cannot be empty"))
            return
        old_path = self._profile_path(normalized_old)
        new_path = self._profile_path(normalized_new)
        if not old_path.exists():
            self.parent_window.show_notification(_("Profile not found"))
            return
        if new_path.exists():
            self.parent_window.show_notification(_("Profile already exists"))
            return
        old_path.rename(new_path)
        if normalized_old == self._current_profile:
            self._set_current_profile(normalized_new)
        self.parent_window.show_notification(
            _("Profile renamed to: %s") % normalized_new
        )

    def _delete_profile(self, profile_name: str) -> None:
        normalized = self._normalize_profile_name(profile_name)
        if not normalized:
            self.parent_window.show_notification(_("Profile name cannot be empty"))
            return
        if normalized == self.DEFAULT_PROFILE_NAME:
            self.parent_window.show_notification(_("Default profile cannot be deleted"))
            return

        profile_path = self._profile_path(normalized)
        if not profile_path.exists():
            self.parent_window.show_notification(_("Profile not found"))
            return

        profile_path.unlink(missing_ok=True)

        if normalized == self._current_profile:
            self._set_current_profile(self.DEFAULT_PROFILE_NAME)
            self.parent_window.on_clear_widgets(None)

        self._save_profile_order(self._list_profiles())
        self.parent_window.show_notification(_("Profile deleted"))

    def _show_profile_manager(self, widget_factory: "WidgetFactory") -> None:
        if self._open_external_profile_manager_window(widget_factory):
            return

        try:
            dialog = Gtk.Dialog(title=_("Profile Manager"), transient_for=self.parent_window)
            dialog.set_modal(True)
            dialog.set_default_size(520, 420)
            dialog.add_button(_("Close"), Gtk.ResponseType.CLOSE)

            content = dialog.get_content_area()
            profile_content = self._build_profile_manager_content(widget_factory)
            content.append(profile_content)

            def on_dialog_close(_dialog, _response_id):
                dialog.destroy()

            dialog.connect("response", on_dialog_close)
            dialog.show()
        except Exception as exc:
            logger.error("Failed to open profile manager dialog: %s", exc)
            self.parent_window.show_notification(_("Failed to open Profile Manager"))

    def _show_create_profile_dialog(
        self, widget_factory: "WidgetFactory", on_done: Callable[[], None] | None = None
    ) -> None:
        dialog = Gtk.Dialog(title=_("Create new profile"), transient_for=self.parent_window)
        dialog.set_modal(True)
        dialog.set_default_size(320, 120)
        dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Create"), Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        entry = Gtk.Entry()
        entry.set_placeholder_text(_("New profile name"))
        entry.set_margin_top(12)
        entry.set_margin_bottom(12)
        entry.set_margin_start(12)
        entry.set_margin_end(12)
        content.append(entry)

        def on_response(_dialog: Gtk.Dialog, response_id: int) -> None:
            if response_id == Gtk.ResponseType.OK:
                self._create_profile(entry.get_text(), widget_factory)
                if on_done:
                    on_done()
            dialog.destroy()

        dialog.connect("response", on_response)
        dialog.show()

    def _show_profile_context_menu(
        self,
        tile: Gtk.Box,
        profile_name: str,
        refresh_tiles: Callable[[], None],
        request_rename: Callable[[str], None],
    ) -> None:
        popover = Gtk.Popover()
        popover.set_has_arrow(True)
        popover.set_parent(tile)

        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        menu_box.set_margin_top(8)
        menu_box.set_margin_bottom(8)
        menu_box.set_margin_start(8)
        menu_box.set_margin_end(8)

        change_profile_button = Gtk.Button(label=_("Change profile"))
        change_profile_button.add_css_class("flat")
        change_profile_button.connect(
            "clicked",
            lambda _btn: (
                self._update_profile(profile_name),
                refresh_tiles(),
                popover.popdown(),
            ),
        )
        menu_box.append(change_profile_button)

        change_name_button = Gtk.Button(label=_("Change name"))
        change_name_button.add_css_class("flat")
        change_name_button.connect(
            "clicked",
            lambda _btn: (
                request_rename(profile_name),
                popover.popdown(),
            ),
        )
        menu_box.append(change_name_button)

        delete_button = Gtk.Button(label=_("Delete"))
        delete_button.add_css_class("flat")
        delete_button.add_css_class("destructive-action")
        delete_button.connect(
            "clicked",
            lambda _btn: (
                self._delete_profile(profile_name),
                refresh_tiles(),
                popover.popdown(),
            ),
        )
        menu_box.append(delete_button)

        popover.set_child(menu_box)
        popover.popup()

    def _create_profile_tile(
        self,
        profile_name: str,
        widget_factory: "WidgetFactory",
        refresh_tiles: Callable[[], None],
        request_rename: Callable[[str], None],
    ) -> Gtk.Box:
        tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        tile.set_halign(Gtk.Align.CENTER)
        tile.set_valign(Gtk.Align.START)
        tile.add_css_class("profile-tile")

        icon_button = Gtk.Button()
        icon_button.set_size_request(88, 88)
        icon_button.set_focus_on_click(False)
        icon_button.add_css_class("circular")
        if profile_name == self._current_profile:
            icon_button.add_css_class("suggested-action")

        letter = Gtk.Label(label=profile_name[:1].upper())
        letter.add_css_class("title-2")
        icon_button.set_child(letter)
        icon_button.connect(
            "clicked", lambda _btn: (self._switch_profile(profile_name, widget_factory), refresh_tiles())
        )
        tile.append(icon_button)

        name_label = Gtk.Label(label=profile_name)
        name_label.set_max_width_chars(14)
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        tile.append(name_label)

        right_click = Gtk.GestureClick()
        right_click.set_button(3)
        right_click.connect(
            "pressed",
            lambda _gesture, _n_press, _x, _y: self._show_profile_context_menu(
                tile, profile_name, refresh_tiles, request_rename
            ),
        )
        tile.add_controller(right_click)

        try:
            press_time = {"value": 0.0}

            hold_click = Gtk.GestureClick()
            hold_click.set_button(1)
            hold_click.connect(
                "pressed", lambda *_args: press_time.__setitem__("value", time.monotonic())
            )
            hold_click.connect("released", lambda *_args: press_time.__setitem__("value", 0.0))
            icon_button.add_controller(hold_click)

            drag_source = Gtk.DragSource()
            drag_source.set_actions(Gdk.DragAction.MOVE)
            drag_source.connect(
                "prepare",
                lambda _source, _x, _y: Gdk.ContentProvider.new_for_value(profile_name)
                if (time.monotonic() - press_time["value"]) >= 0.35
                else None,
            )
            icon_button.add_controller(drag_source)

            drop_target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)

            def on_drop(_target, value, _x, _y):
                source_name = value if isinstance(value, str) else None
                if not source_name or source_name == profile_name:
                    return False
                ordered = self._list_profiles()
                if source_name not in ordered or profile_name not in ordered:
                    return False
                ordered.remove(source_name)
                insert_index = ordered.index(profile_name)
                ordered.insert(insert_index, source_name)
                self._save_profile_order(ordered)
                refresh_tiles()
                return True

            drop_target.connect("drop", on_drop)
            tile.add_controller(drop_target)
        except Exception as exc:
            logger.error("Failed to initialize profile tile drag-and-drop: %s", exc)
        return tile

    def _build_profile_manager_content(self, widget_factory: "WidgetFactory") -> Gtk.Box:
        self._ensure_profile_manager_css()
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        hotkey_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        hotkey_row.set_hexpand(True)

        hotkey_label = Gtk.Label(label=_("Select a hotkey"), xalign=0)
        hotkey_label.set_hexpand(True)
        hotkey_row.append(hotkey_label)

        hotkey_button = Gtk.Button(label=self._get_hotkey_display_text())
        hotkey_button.set_hexpand(True)
        hotkey_button.set_halign(Gtk.Align.FILL)
        hotkey_button.set_valign(Gtk.Align.CENTER)
        hotkey_button.add_css_class("profile-hotkey-input")
        hotkey_button.set_tooltip_text(_("Click and press a key combination"))
        hotkey_row.append(hotkey_button)

        capture_state = {"active": False}

        def finish_capture(hotkey: "KeyCombination | None") -> None:
            self._save_profile_hotkey(hotkey)
            capture_state["active"] = False
            hotkey_button.set_label(self._get_hotkey_display_text())

        def on_hotkey_pressed(_controller, keyval, keycode, state):
            if not capture_state["active"]:
                return False

            if keyval == Gdk.KEY_Escape:
                finish_capture(None)
                return True

            combo = self._build_key_combination_from_event(keyval, keycode, state)
            finish_capture(combo)
            return True

        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", on_hotkey_pressed)
        hotkey_button.add_controller(key_controller)

        hotkey_button.connect(
            "clicked",
            lambda _btn: (
                capture_state.__setitem__("active", True),
                hotkey_button.set_label(_("Press keys...")),
                hotkey_button.grab_focus(),
            ),
        )

        content.append(hotkey_row)

        profile_grid = Gtk.FlowBox()
        profile_grid.set_selection_mode(Gtk.SelectionMode.NONE)
        profile_grid.set_orientation(Gtk.Orientation.HORIZONTAL)
        profile_grid.set_column_spacing(12)
        profile_grid.set_row_spacing(12)
        profile_grid.set_min_children_per_line(4)
        profile_grid.set_max_children_per_line(6)
        profile_grid.set_homogeneous(True)

        editor_state: dict[str, str | None] = {"mode": None, "target": None}

        def build_inline_editor(
            initial_text: str,
            placeholder: str,
            accept_icon: str,
            on_confirm: Callable[[str], None],
            on_cancel: Callable[[], None],
        ) -> Gtk.Box:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            row.set_margin_top(4)

            cancel_button = Gtk.Button()
            cancel_button.set_icon_name("window-close-symbolic")
            cancel_button.add_css_class("flat")
            cancel_button.connect("clicked", lambda _btn: on_cancel())
            row.append(cancel_button)

            entry = Gtk.Entry()
            entry.set_hexpand(True)
            entry.set_text(initial_text)
            entry.set_placeholder_text(placeholder)
            row.append(entry)

            accept_button = Gtk.Button()
            accept_button.set_icon_name(accept_icon)
            accept_button.add_css_class("flat")
            accept_button.connect("clicked", lambda _btn: on_confirm(entry.get_text()))
            row.append(accept_button)

            entry.connect("activate", lambda _entry: on_confirm(entry.get_text()))
            return row

        def request_rename(profile_name: str) -> None:
            editor_state["mode"] = "rename"
            editor_state["target"] = profile_name
            refresh_tiles()

        def clear_editor() -> None:
            editor_state["mode"] = None
            editor_state["target"] = None

        def refresh_tiles() -> None:
            child = profile_grid.get_first_child()
            while child:
                next_child = child.get_next_sibling()
                profile_grid.remove(child)
                child = next_child

            for profile_name in self._list_profiles():
                tile = self._create_profile_tile(
                    profile_name, widget_factory, refresh_tiles, request_rename
                )

                if editor_state["mode"] == "rename" and editor_state["target"] == profile_name:
                    tile.append(
                        build_inline_editor(
                            initial_text=profile_name,
                            placeholder=_("New profile name"),
                            accept_icon="emblem-ok-symbolic",
                            on_confirm=lambda text, old=profile_name: (
                                self._rename_profile(old, text),
                                clear_editor(),
                                refresh_tiles(),
                            ),
                            on_cancel=lambda: (
                                clear_editor(),
                                refresh_tiles(),
                            ),
                        )
                    )

                profile_grid.append(tile)

            add_tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            add_tile.set_halign(Gtk.Align.CENTER)
            add_tile.set_valign(Gtk.Align.START)

            add_button = Gtk.Button()
            add_button.set_size_request(88, 88)
            add_button.add_css_class("suggested-action")
            add_button.set_icon_name("list-add-symbolic")
            add_button.connect(
                "clicked",
                lambda _btn: (
                    editor_state.__setitem__("mode", "add"),
                    editor_state.__setitem__("target", None),
                    refresh_tiles(),
                ),
            )
            add_tile.append(add_button)

            add_label = Gtk.Label(label=_("Add profile"))
            add_tile.append(add_label)

            if editor_state["mode"] == "add":
                add_tile.append(
                    build_inline_editor(
                        initial_text="",
                        placeholder=_("New profile name"),
                        accept_icon="list-add-symbolic",
                        on_confirm=lambda text: (
                            self._create_profile(text, widget_factory),
                            clear_editor(),
                            refresh_tiles(),
                        ),
                        on_cancel=lambda: (
                            clear_editor(),
                            refresh_tiles(),
                        ),
                    )
                )

            profile_grid.append(add_tile)

        refresh_tiles()
        content.append(profile_grid)
        return content

    def _open_external_profile_manager_window(self, widget_factory: "WidgetFactory") -> bool:
        if self._profile_manager_window is not None:
            self._profile_manager_window.present()
            return True

        host_display_name = getattr(self.parent_window, "_host_display_name", None)
        if not host_display_name:
            return False

        display = Gdk.Display.open(host_display_name)
        if display is None:
            logger.error(
                "Failed to open host display for profile manager window: %s",
                host_display_name,
            )
            return False

        try:
            window = Adw.Window(application=self.parent_window.get_application())
            window.set_display(display)
            window.set_title(_("Profile Manager"))
            if hasattr(window, "set_resizable"):
                window.set_resizable(True)
            if hasattr(window, "set_decorated"):
                window.set_decorated(True)

            header_bar = Gtk.HeaderBar()
            header_bar.set_show_title_buttons(False)
            header_bar.set_title_widget(Gtk.Label(label=_("Profile Manager")))

            minimize_button = Gtk.Button.new()
            minimize_button.set_icon_name("window-minimize-symbolic")
            minimize_button.add_css_class("flat")
            minimize_button.add_css_class("dim-label")
            minimize_button.connect(
                "clicked",
                lambda _button: window.minimize()
                if hasattr(window, "minimize")
                else window.set_visible(False),
            )

            close_button = Gtk.Button.new()
            close_button.set_icon_name("window-close-symbolic")
            close_button.add_css_class("flat")
            close_button.add_css_class("destructive-action")
            close_button.connect("clicked", lambda _button: window.close())

            header_bar.pack_end(minimize_button)
            header_bar.pack_end(close_button)

            title_handle = Gtk.WindowHandle()
            title_handle.set_child(header_bar)

            window.set_default_size(420, 420)

            scrolled = Gtk.ScrolledWindow()
            scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scrolled.set_hexpand(True)
            scrolled.set_vexpand(True)
            scrolled.set_child(self._build_profile_manager_content(widget_factory))

            content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            content_box.set_hexpand(True)
            content_box.set_vexpand(True)
            content_box.append(title_handle)
            content_box.append(scrolled)
            window.set_content(content_box)

            def on_window_close(_window):
                self._profile_manager_window = None
                return False

            window.connect("close-request", on_window_close)
            self._profile_manager_window = window
            window.present()
            return True
        except Exception as exc:
            logger.error("Failed to open external profile manager window: %s", exc)
            return False
