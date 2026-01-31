#!/usr/bin/env python3
"""
动态菜单管理
根据发现的组件自动生成菜单项
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from gettext import gettext as _
from pathlib import Path
from typing import TYPE_CHECKING, Any

import gi
from gi.repository import Gdk, Gtk, GLib

from waydroid_helper.controller.core.control_msg import ScreenInfo
from waydroid_helper.controller.core.key_system import Key, KeyCombination, KeyRegistry
from waydroid_helper.util.log import logger
from waydroid_helper.controller.widgets.base import BaseWidget
from waydroid_helper.config.file_manager import ConfigManager as FileConfigManager

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

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

    def _current_profile_state_path(self) -> Path:
        return Path(self._get_profiles_dir()) / f"{self.CURRENT_PROFILE_STATE_NAME}.json"

    def _write_current_profile_state(self, profile_name: str) -> None:
        state_path = self._current_profile_state_path()
        payload = {"current_profile": profile_name}
        temp_path = state_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, state_path)
        except Exception as e:
            logger.error(f"Failed to save profile state: {e}")

    def _load_current_profile(self) -> str:
        profile = self.DEFAULT_PROFILE_NAME
        self._write_current_profile_state(profile)
        return profile

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
        return sorted(profile_names)

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

    def _refresh_profile_dropdown(
        self, dropdown: Gtk.DropDown, profile_names: list[str], selected: str
    ) -> None:
        string_list = Gtk.StringList()
        for name in profile_names:
            string_list.append(name)
        dropdown.set_model(string_list)
        if selected in profile_names:
            dropdown.set_selected(profile_names.index(selected))

    def _get_selected_profile_name(self, dropdown: Gtk.DropDown) -> str:
        selected_item = dropdown.get_selected_item()
        if isinstance(selected_item, Gtk.StringObject):
            return selected_item.get_string()
        profile_names = self._list_profiles()
        selected_index = dropdown.get_selected()
        if 0 <= selected_index < len(profile_names):
            return profile_names[selected_index]
        return self.DEFAULT_PROFILE_NAME

    def _show_profile_manager(self, widget_factory: "WidgetFactory") -> None:
        dialog = Gtk.Dialog(title=_("Profile Manager"), transient_for=self.parent_window)
        dialog.set_modal(True)
        dialog.set_default_size(360, 260)
        dialog.add_button(_("Close"), Gtk.ResponseType.CLOSE)

        content = dialog.get_content_area()
        content.set_spacing(12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        current_label = Gtk.Label(label=_("Current profile"), xalign=0)
        content.append(current_label)

        profile_names = self._list_profiles()
        profile_dropdown = Gtk.DropDown()
        self._refresh_profile_dropdown(
            profile_dropdown, profile_names, self._current_profile
        )
        content.append(profile_dropdown)

        switch_button = Gtk.Button(label=_("Switch profile"))
        switch_button.connect(
            "clicked",
            lambda _btn: self._switch_profile(
                self._get_selected_profile_name(profile_dropdown), widget_factory
            ),
        )
        content.append(switch_button)

        update_button = Gtk.Button(label=_("Update selected profile"))
        update_button.connect(
            "clicked",
            lambda _btn: self._update_profile(
                self._get_selected_profile_name(profile_dropdown)
            ),
        )
        content.append(update_button)

        new_profile_label = Gtk.Label(label=_("Create new profile"), xalign=0)
        content.append(new_profile_label)

        new_profile_entry = Gtk.Entry()
        new_profile_entry.set_placeholder_text(_("New profile name"))
        content.append(new_profile_entry)

        create_button = Gtk.Button(label=_("Create profile from current"))
        create_button.connect(
            "clicked",
            lambda _btn: self._create_profile(
                new_profile_entry.get_text(), widget_factory
            ),
        )
        content.append(create_button)

        rename_label = Gtk.Label(label=_("Rename profile"), xalign=0)
        content.append(rename_label)

        rename_entry = Gtk.Entry()
        rename_entry.set_placeholder_text(_("New name for selected profile"))
        content.append(rename_entry)

        rename_button = Gtk.Button(label=_("Rename selected profile"))
        rename_button.connect(
            "clicked",
            lambda _btn: self._rename_profile(
                self._get_selected_profile_name(profile_dropdown),
                rename_entry.get_text(),
            ),
        )
        content.append(rename_button)

        def on_dialog_close(_dialog, _response_id):
            dialog.destroy()

        def refresh_profiles():
            updated_profiles = self._list_profiles()
            selected = self._current_profile
            self._refresh_profile_dropdown(
                profile_dropdown, updated_profiles, selected
            )
            return False

        update_button.connect("clicked", lambda _btn: GLib.idle_add(refresh_profiles))
        create_button.connect("clicked", lambda _btn: GLib.idle_add(refresh_profiles))
        rename_button.connect("clicked", lambda _btn: GLib.idle_add(refresh_profiles))
        switch_button.connect("clicked", lambda _btn: GLib.idle_add(refresh_profiles))

        dialog.connect("response", on_dialog_close)
        dialog.show()
