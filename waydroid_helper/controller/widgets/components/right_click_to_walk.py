#!/usr/bin/env python3
import math
import time
from enum import Enum
from gettext import pgettext
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from cairo import Context, Surface
    from gi.repository import Gtk

from gi.repository import GLib, Gdk

from waydroid_helper.controller.android.input import (AMotionEventAction,
                                                      AMotionEventButtons)
from waydroid_helper.controller.core import (Event, EventType, KeyCombination,
                                             EventBus, KeyRegistry,
                                             PointerIdManager)
from waydroid_helper.controller.core.control_msg import InjectTouchEventMsg, ScreenInfo
from waydroid_helper.controller.core.handler.event_handlers import InputEvent
from waydroid_helper.controller.widgets.base.base_widget import BaseWidget
from waydroid_helper.controller.widgets.decorators import (Resizable,
                                                           ResizableDecorator)
from waydroid_helper.controller.widgets.config import create_action_config, create_text_config

class JoystickState(Enum):
    """摇杆状态枚举"""
    INACTIVE = "inactive"      # 未激活
    MOVING = "moving"          # 移动中（向边界移动）
    HOLDING = "holding"        # 在边界保持中


@Resizable(resize_strategy=ResizableDecorator.RESIZE_CENTER)
class RightClickToWalk(BaseWidget):
    """Right click widget for work or context menu actions"""

    MAPPING_MODE_WIDTH = 30
    MAPPING_MODE_HEIGHT = 30
    SETTINGS_PANEL_AUTO_HIDE = False
    WIDGET_NAME = pgettext("Controller Widgets", "Right Click to Walk")
    WIDGET_DESCRIPTION = pgettext(
        "Controller Widgets",
        "Add to the game's movement wheel: hold and drag to steer, single-click to auto-walk to cursor. Ideal for MOBAs.",
    )
    CENTER_X_CONFIG_KEY = "calibrated_center_x"
    CENTER_Y_CONFIG_KEY = "calibrated_center_y"
    CENTER_X_INPUT_CONFIG_KEY = "center_x_input"
    CENTER_Y_INPUT_CONFIG_KEY = "center_y_input"
    CALIBRATE_CENTER_CONFIG_KEY = "calibrate_center"
    RESET_CENTER_CONFIG_KEY = "reset_center"
    APPLY_CENTER_CONFIG_KEY = "apply_center"
    X_GAIN_CONFIG_KEY = "x_gain"
    Y_GAIN_CONFIG_KEY = "y_gain"
    X_GAIN_INPUT_CONFIG_KEY = "x_gain_input"
    Y_GAIN_INPUT_CONFIG_KEY = "y_gain_input"
    APPLY_GAIN_CONFIG_KEY = "apply_gains"
    TUNE_ANGLE_CONFIG_KEY = "tune_angle"
    UP_DIST_CONFIG_KEY = "up_dist_px"
    DOWN_DIST_CONFIG_KEY = "down_dist_px"
    LEFT_DIST_CONFIG_KEY = "left_dist_px"
    RIGHT_DIST_CONFIG_KEY = "right_dist_px"
    UP_DIST_INPUT_CONFIG_KEY = "up_dist_input"
    DOWN_DIST_INPUT_CONFIG_KEY = "down_dist_input"
    LEFT_DIST_INPUT_CONFIG_KEY = "left_dist_input"
    RIGHT_DIST_INPUT_CONFIG_KEY = "right_dist_input"
    APPLY_ANCHORS_CONFIG_KEY = "apply_anchors"
    RESET_ANCHORS_CONFIG_KEY = "reset_anchors"
    SET_UP_ANCHOR_CONFIG_KEY = "set_up_anchor"
    SET_DOWN_ANCHOR_CONFIG_KEY = "set_down_anchor"
    SET_LEFT_ANCHOR_CONFIG_KEY = "set_left_anchor"
    SET_RIGHT_ANCHOR_CONFIG_KEY = "set_right_anchor"
    DEADZONE_CONFIG_KEY = "deadzone"
    DEADZONE_INPUT_CONFIG_KEY = "deadzone_input"
    APPLY_DEADZONE_CONFIG_KEY = "apply_deadzone"
    GAIN_DEFAULT = 1.0
    GAIN_MIN = 0.5
    GAIN_MAX = 2.0
    DEADZONE_DEFAULT = 0.08
    DEADZONE_MIN = 0.0
    DEADZONE_MAX = 0.9

    def __init__(
        self,
        x: int = 0,
        y: int = 0,
        width: int = 150,
        height: int = 150,
        text: str = "",
        default_keys: set[KeyCombination] | None = None,
        event_bus: EventBus | None = None,
        pointer_id_manager: PointerIdManager | None = None,
        key_registry: KeyRegistry | None = None,
    ):
        super().__init__(
            x,
            y,
            min(width, height),
            min(width, height),
            pgettext("Controller Widgets", "Right Click to Walk"),
            text,
            min_width=25,
            min_height=25,
            event_bus=event_bus,
            pointer_id_manager=pointer_id_manager,
            key_registry=key_registry,
        )
        # Fix the default keys issue
        if default_keys is None:
            mouse_right_key = self.key_registry.get_by_name("Mouse_Right")
            if mouse_right_key is not None:
                default_keys = set([KeyCombination([mouse_right_key])])
            else:
                default_keys = set()
        
        self.set_default_keys(default_keys)
 
        self.event_bus.subscribe(EventType.MOUSE_MOTION, lambda event: (self.on_key_triggered(None, event.data), None)[1])

        # 摇杆状态管理
        self._joystick_state: JoystickState = JoystickState.INACTIVE
        self._current_position: tuple[float, float] = (x + width / 2, y + height / 2)
        self._target_position: tuple[float, float] = (x + width / 2, y + height / 2)
        self.is_reentrant: bool = True

        # 平滑移动系统
        self._timer_interval: int = 20  # ms
        self._move_steps_total: int = 6
        self._move_steps_count: int = 0
        self._move_timer: int | None = None

        # 点按/长按检测
        self._key_press_start_time: float = 0.0
        self._is_long_press: bool = False
        self._long_press_threshold: float = 0.3  # 300ms 区分点按和长按
        self._key_is_currently_pressed: bool = False  # 跟踪右键是否仍然按下

        # 边界保持系统
        self._hold_timer: int | None = None
        self._hold_duration: float = 0.0  # 保持时间（秒）
        self._max_hold_duration: float = 5.0  # 最大保持时间

        # 距离检测
        self._mouse_distance_from_center: float = 0.0

        self.screen_info = ScreenInfo()
        self._calibration_mode: bool = False
        self._tuning_mode: bool = False
        self._tuning_x_gain: float | None = None
        self._tuning_y_gain: float | None = None
        self._locked_target_position: tuple[float, float] | None = None
        self._anchor_calibration_axis: str | None = None

        self.setup_config()
        self.event_bus.subscribe(
            event_type=EventType.MASK_CLICKED,
            handler=self._on_mask_clicked,
            subscriber=self,
        )
        self._emit_overlay_event("register")

    def draw_widget_content(self, cr: "Context[Surface]", width: int, height: int):
        """绘制组件的具体内容 - 圆形背景，上下左右箭头，中心鼠标图标"""
        # 计算圆心和半径
        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) / 2 - 8  # 留出边距，与 dpad 一致

        # 绘制外圆背景
        cr.set_source_rgba(0.4, 0.4, 0.4, 0.7)
        cr.arc(center_x, center_y, radius, 0, 2 * math.pi)
        cr.fill()

        # 绘制外圆边框
        cr.set_source_rgba(0.2, 0.2, 0.2, 0.9)
        cr.set_line_width(2)
        cr.arc(center_x, center_y, radius, 0, 2 * math.pi)
        cr.stroke()

        # 绘制上下左右箭头
        self._draw_direction_arrows(cr, center_x, center_y, radius)

        # 绘制中心圆 - 与 dpad 相同的样式
        inner_radius = radius * 0.3
        cr.set_source_rgba(0.6, 0.6, 0.6, 0.8)
        cr.arc(center_x, center_y, inner_radius, 0, 2 * math.pi)
        cr.fill()

        # 在中心圆里绘制鼠标图标
        self._draw_mouse_in_center(cr, center_x, center_y, inner_radius)

    def _draw_direction_arrows(
        self, cr: "Context[Surface]", center_x: float, center_y: float, radius: float
    ):
        """绘制上下左右四个方向的好看箭头 - 实心三角形样式"""
        arrow_distance = radius * 0.65  # 箭头距离中心的距离
        arrow_size = radius * 0.12  # 箭头大小

        # 箭头位置
        positions = {
            "up": (center_x, center_y - arrow_distance),
            "down": (center_x, center_y + arrow_distance),
            "left": (center_x - arrow_distance, center_y),
            "right": (center_x + arrow_distance, center_y),
        }

        # 设置箭头颜色 - 白色带轻微透明度
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.9)

        # 上箭头 ↑ - 实心三角形
        x, y = positions["up"]
        cr.move_to(x, y - arrow_size)  # 顶点
        cr.line_to(x - arrow_size * 0.6, y + arrow_size * 0.5)  # 左下
        cr.line_to(x + arrow_size * 0.6, y + arrow_size * 0.5)  # 右下
        cr.close_path()
        cr.fill()

        # 下箭头 ↓ - 实心三角形
        x, y = positions["down"]
        cr.move_to(x, y + arrow_size)  # 底点
        cr.line_to(x - arrow_size * 0.6, y - arrow_size * 0.5)  # 左上
        cr.line_to(x + arrow_size * 0.6, y - arrow_size * 0.5)  # 右上
        cr.close_path()
        cr.fill()

        # 左箭头 ← - 实心三角形
        x, y = positions["left"]
        cr.move_to(x - arrow_size, y)  # 左点
        cr.line_to(x + arrow_size * 0.5, y - arrow_size * 0.6)  # 右上
        cr.line_to(x + arrow_size * 0.5, y + arrow_size * 0.6)  # 右下
        cr.close_path()
        cr.fill()

        # 右箭头 → - 实心三角形
        x, y = positions["right"]
        cr.move_to(x + arrow_size, y)  # 右点
        cr.line_to(x - arrow_size * 0.5, y - arrow_size * 0.6)  # 左上
        cr.line_to(x - arrow_size * 0.5, y + arrow_size * 0.6)  # 左下
        cr.close_path()
        cr.fill()

        # 可选：添加轻微的边框让箭头更突出
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.3)  # 半透明黑色边框
        cr.set_line_width(0.5)

        # 重新绘制上箭头的边框
        x, y = positions["up"]
        cr.move_to(x, y - arrow_size)
        cr.line_to(x - arrow_size * 0.6, y + arrow_size * 0.5)
        cr.line_to(x + arrow_size * 0.6, y + arrow_size * 0.5)
        cr.close_path()
        cr.stroke()

        # 重新绘制下箭头的边框
        x, y = positions["down"]
        cr.move_to(x, y + arrow_size)
        cr.line_to(x - arrow_size * 0.6, y - arrow_size * 0.5)
        cr.line_to(x + arrow_size * 0.6, y - arrow_size * 0.5)
        cr.close_path()
        cr.stroke()

        # 重新绘制左箭头的边框
        x, y = positions["left"]
        cr.move_to(x - arrow_size, y)
        cr.line_to(x + arrow_size * 0.5, y - arrow_size * 0.6)
        cr.line_to(x + arrow_size * 0.5, y + arrow_size * 0.6)
        cr.close_path()
        cr.stroke()

        # 重新绘制右箭头的边框
        x, y = positions["right"]
        cr.move_to(x + arrow_size, y)
        cr.line_to(x - arrow_size * 0.5, y - arrow_size * 0.6)
        cr.line_to(x - arrow_size * 0.5, y + arrow_size * 0.6)
        cr.close_path()
        cr.stroke()

    def _draw_mouse_in_center(
        self,
        cr: "Context[Surface]",
        center_x: float,
        center_y: float,
        circle_radius: float,
    ):
        """在中心圆内绘制鼠标图标 - 右键蓝色高亮"""
        # 鼠标尺寸适应中心圆
        mouse_w = circle_radius * 1.2  # 适当大小，不超出中心圆
        mouse_h = mouse_w * 1.25  # 稍微拉高，接近真实鼠标比例
        border_width = 1.0

        # 1. 先绘制整个鼠标为白色填充
        cr.save()
        cr.translate(center_x, center_y)
        cr.scale(mouse_w / 2, mouse_h / 2)
        cr.set_source_rgba(1, 1, 1, 1)  # 白色背景
        cr.arc(0, 0, 1, 0, 2 * math.pi)
        cr.fill()
        cr.restore()

        # 2. 右键（右上区域）用蓝色覆盖 - 修正为右键蓝色
        cr.save()
        cr.translate(center_x, center_y)
        cr.scale(mouse_w / 2, mouse_h / 2)
        cr.set_source_rgba(0.2, 0.6, 1.0, 1.0)  # 蓝色
        cr.move_to(0, 0)
        cr.arc(0, 0, 1, math.pi * 1.5, math.pi * 2)  # 右上区域 (0° 到 90°)
        cr.line_to(0, 0)
        cr.close_path()
        cr.fill()
        cr.restore()

        # 3. 鼠标外轮廓（黑色椭圆描边）
        cr.set_line_width(border_width)
        cr.set_source_rgba(0, 0, 0, 1)
        cr.save()
        cr.translate(center_x, center_y)
        cr.scale(mouse_w / 2, mouse_h / 2)
        cr.arc(0, 0, 1, 0, 2 * math.pi)
        cr.restore()
        cr.stroke()

        # 4. 绘制横线分割（上半/下半）
        mouse_x = center_x - mouse_w / 2
        mouse_y = center_y - mouse_h / 2
        cr.set_line_width(border_width)
        cr.set_source_rgba(0, 0, 0, 1)
        split_y = center_y
        cr.move_to(mouse_x, split_y)
        cr.line_to(mouse_x + mouse_w, split_y)
        cr.stroke()

        # 5. 绘制竖线分割（上半左右键）
        cr.set_line_width(border_width)
        cr.set_source_rgba(0, 0, 0, 1)
        split_x = center_x
        cr.move_to(split_x, mouse_y)
        cr.line_to(split_x, split_y)
        cr.stroke()

        # 清除路径，避免影响后续绘制
        cr.new_path()

    def draw_text_content(self, cr: "Context[Surface]", width: int, height: int):
        """重写文本绘制 - 鼠标图标已在 draw_widget_content 中绘制，这里为空"""

    def draw_selection_border(self, cr: "Context[Surface]", width: int, height: int):
        """Override selection border drawing - circular border for circular button"""
        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) / 2 - 5

        # Draw circular selection border
        cr.set_source_rgba(0.2, 0.6, 1.0, 0.8)
        cr.set_line_width(3)
        cr.arc(center_x, center_y, radius + 3, 0, 2 * math.pi)
        cr.stroke()

    def draw_mapping_mode_background(
        self, cr: "Context[Surface]", width: int, height: int
    ):
        """Mapping mode background drawing - circular background"""
        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) / 2 - 2  # Reduce margin

        # Draw single background color circle
        cr.set_source_rgba(0.6, 0.6, 0.6, 0.5)  # Unified semi-transparent gray
        cr.arc(center_x, center_y, radius, 0, 2 * math.pi)
        cr.fill()

    def draw_mapping_mode_content(
        self, cr: "Context[Surface]", width: int, height: int
    ):
        """映射模式下的内容绘制 - 只显示鼠标图标，与 fire 组件类似，右键蓝色高亮"""
        # 在映射模式下只绘制鼠标图标，尺寸与 fire 组件一致
        center_x = width / 2
        center_y = height / 2

        # 鼠标主体参数（与 fire.py 相同的尺寸）
        mouse_w = min(width, height) * 0.38
        mouse_h = mouse_w * 1.25  # 稍微拉高，接近真实鼠标比例
        mouse_x = center_x - mouse_w / 2
        mouse_y = center_y - mouse_h / 2
        border_width = 1.2

        # 1. 先绘制整个鼠标为白色填充
        cr.save()
        cr.translate(center_x, center_y)
        cr.scale(mouse_w / 2, mouse_h / 2)
        cr.set_source_rgba(1, 1, 1, 1)  # 白色背景
        cr.arc(0, 0, 1, 0, 2 * math.pi)
        cr.fill()
        cr.restore()

        # 2. 右键（右上区域）用蓝色覆盖 - 修正为右键蓝色
        cr.save()
        cr.translate(center_x, center_y)
        cr.scale(mouse_w / 2, mouse_h / 2)
        cr.set_source_rgba(0.2, 0.6, 1.0, 1.0)  # 蓝色
        cr.move_to(0, 0)
        cr.arc(0, 0, 1, math.pi * 1.5, math.pi * 2)  # 右上区域 (270° 到 360°)
        cr.line_to(0, 0)
        cr.close_path()
        cr.fill()
        cr.restore()

        # 3. 鼠标外轮廓（黑色椭圆描边）
        cr.set_line_width(border_width)
        cr.set_source_rgba(0, 0, 0, 1)
        cr.save()
        cr.translate(center_x, center_y)
        cr.scale(mouse_w / 2, mouse_h / 2)
        cr.arc(0, 0, 1, 0, 2 * math.pi)
        cr.restore()
        cr.stroke()

        # 4. 绘制横线分割（上半/下半）
        cr.set_line_width(border_width)
        cr.set_source_rgba(0, 0, 0, 1)
        split_y = center_y
        cr.move_to(mouse_x, split_y)
        cr.line_to(mouse_x + mouse_w, split_y)
        cr.stroke()

        # 5. 绘制竖线分割（上半左右键）
        cr.set_line_width(border_width)
        cr.set_source_rgba(0, 0, 0, 1)
        split_x = center_x
        cr.move_to(split_x, mouse_y)
        cr.line_to(split_x, split_y)
        cr.stroke()

        # 清除路径，避免影响后续绘制
        cr.new_path()

    def _calculate_hold_duration(self, mouse_distance: float, window_center: tuple[float, float], window_size: tuple[int, int]) -> float:
        """根据鼠标距离窗口中心的距离计算保持时间"""
        # 计算窗口对角线长度作为最大距离
        max_distance = math.sqrt(window_size[0]**2 + window_size[1]**2) / 2
        
        # 距离比例（0-1）
        distance_ratio = min(mouse_distance / max_distance, 1.0)
        
        # 保持时间与距离成正比，最多5秒
        hold_duration = distance_ratio * self._max_hold_duration
        
        return max(0.5, hold_duration)  # 最少0.5秒

    def _start_smooth_move_to_boundary(self):
        """开始平滑移动到边界"""
        if self._move_timer:
            GLib.source_remove(self._move_timer)
        
        self._joystick_state = JoystickState.MOVING
        self._move_steps_count = 0
        self._move_timer = GLib.timeout_add(
            self._timer_interval, self._update_smooth_move
        )

    def _update_smooth_move(self) -> bool:
        """平滑移动的定时器回调"""
        if self._move_steps_count < self._move_steps_total:
            dx = self._target_position[0] - self._current_position[0]
            dy = self._target_position[1] - self._current_position[1]
            remaining_steps = self._move_steps_total - self._move_steps_count

            self._current_position = (
                self._current_position[0] + dx / remaining_steps,
                self._current_position[1] + dy / remaining_steps,
            )
            self._move_steps_count += 1
            
            if self._joystick_state == JoystickState.MOVING:
                self._emit_touch_event(AMotionEventAction.MOVE)
            
            return True  # Continue timer

        # 移动完成，到达边界
        self._current_position = self._target_position
        self._move_timer = None
        
        if self._joystick_state == JoystickState.MOVING:
            self._on_reached_boundary()
        
        return False  # Stop timer

    def _on_reached_boundary(self):
        """到达边界时的处理"""
        self._joystick_state = JoystickState.HOLDING
        
        # 如果是点按模式且用户已经松开右键，立即开始保持计时
        if not self._is_long_press and not self._key_is_currently_pressed:
            self._start_hold_timer()
        else:
            pass

    def _start_hold_timer(self):
        """开始保持计时器"""
        # 清除之前的计时器（如果有）
        if self._hold_timer:
            GLib.source_remove(self._hold_timer)
            self._hold_timer = None
        
        # 计算保持时间
        self._hold_duration = self._calculate_hold_duration(
            self._mouse_distance_from_center, 
            self._get_window_center(),
            self._get_window_size()
        )
        
        # 启动计时器
        self._hold_timer = GLib.timeout_add(
            int(self._hold_duration * 1000), 
            self._on_hold_timeout
        )

    def _on_hold_timeout(self) -> bool:
        """保持时间到达后的回调"""
        self._hold_timer = None
        self._finish_joystick_action()
        return False  # Stop timer

    def _instant_move_to_boundary(self, new_trigger_time: float):
        """瞬间移动到边界（保持状态下的新触发）"""
        self._current_position = self._target_position
        self._emit_touch_event(AMotionEventAction.MOVE)
        
        # 更新触发时间和距离信息
        self._key_press_start_time = new_trigger_time
        self._is_long_press = False  # 重置长按状态，等待新的判断
        
        # 清除之前的保持计时器（如果有）
        if self._hold_timer:
            GLib.source_remove(self._hold_timer)
            self._hold_timer = None
        

    def _finish_joystick_action(self):
        """完成摇杆动作，发送UP事件并重置"""
        self._emit_touch_event(AMotionEventAction.UP)
        self._reset_joystick()

    def _reset_joystick(self):
        """重置摇杆状态"""
        self._joystick_state = JoystickState.INACTIVE
        self._current_position = (self.center_x, self.center_y)
        self._locked_target_position = None
        self._key_is_currently_pressed = False
        self._is_long_press = False
        
        # 清理定时器
        if self._move_timer:
            GLib.source_remove(self._move_timer)
            self._move_timer = None
        if self._hold_timer:
            GLib.source_remove(self._hold_timer)
            self._hold_timer = None
        
        # 释放指针ID
        self.pointer_id_manager.release(self)
        

    def _get_window_center(self) -> tuple[float, float]:
        """获取窗口中心坐标"""
        calibrated = self._get_calibrated_center()
        if calibrated is not None:
            return calibrated
        w, h = self.screen_info.get_host_resolution()
        return (w / 2, h / 2)

    def _get_window_size(self) -> tuple[int, int]:
        """获取窗口大小"""
        return self.screen_info.get_host_resolution()

    def _emit_touch_event(
        self, action: AMotionEventAction, position: tuple[float, float] | None = None
    ):
        pos = position if position is not None else self._current_position
        w, h = self.screen_info.get_host_resolution()
        pressure = 1.0 if action != AMotionEventAction.UP else 0.0
        buttons = AMotionEventButtons.PRIMARY if action != AMotionEventAction.UP else 0
        pointer_id = self.pointer_id_manager.get_allocated_id(self)
        if pointer_id is None:
            return

        msg = InjectTouchEventMsg(
            action=action,
            pointer_id=pointer_id,
            position=(int(pos[0]), int(pos[1]), w, h),
            pressure=pressure,
            action_button=AMotionEventButtons.PRIMARY,
            buttons=buttons,
        )
        self.event_bus.emit(Event(EventType.CONTROL_MSG, self, msg))

    def _get_target_position(
        self,
        cx: float,
        cy: float,
        r: float,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> tuple[float, float]:
        """计算目标位置（基于校准形状映射到理想圆）"""
        dx = x1 - x0
        dy = y1 - y0
        normalized = self._normalize_cursor_vector(dx, dy)
        if normalized is None:
            return self._get_fallback_target_position(cx, cy, r, dx, dy)
        nx, ny = normalized
        return (cx + nx * r, cy + ny * r)

    def _get_fallback_target_position(
        self, cx: float, cy: float, r: float, dx: float, dy: float
    ) -> tuple[float, float]:
        """Fallback to gain-based circle when anchors are missing."""
        x_gain, y_gain = self._get_gains()
        dx *= x_gain
        dy *= y_gain
        length = math.hypot(dx, dy)
        if length == 0:
            return (cx, cy)
        dx /= length
        dy /= length
        return (cx + dx * r, cy + dy * r)

    def _normalize_cursor_vector(self, dx: float, dy: float) -> tuple[float, float] | None:
        anchors = self._get_anchor_distances()
        if anchors is None:
            return None
        up_dist, down_dist, left_dist, right_dist = anchors
        rx = right_dist if dx >= 0 else left_dist
        ry = down_dist if dy >= 0 else up_dist
        if rx <= 0 or ry <= 0:
            return None
        nx = dx / rx
        ny = dy / ry
        length = math.hypot(nx, ny)
        if length > 1.0:
            nx /= length
            ny /= length
            length = 1.0
        deadzone = self._get_deadzone()
        if length < deadzone:
            return (0.0, 0.0)
        if length > 0 and deadzone > 0:
            scale = (length - deadzone) / (1.0 - deadzone)
            nx *= scale / length
            ny *= scale / length
        return (nx, ny)

    def on_key_triggered(
        self,
        key_combination: KeyCombination | None = None,
        event: "InputEvent | None" = None,
    ):
        if not event or event.position is None:
            return False

        current_time = time.time()

        # 获取鼠标位置和窗口信息
        mouse_x, mouse_y = event.position
        window_center_x, window_center_y = self._get_window_center()

        is_click_event = event.event_type == "mouse_press"
        is_motion_event = event.event_type == "mouse_motion"

        if is_click_event:
            # 计算鼠标距离窗口中心的距离
            self._mouse_distance_from_center = math.hypot(
                mouse_x - window_center_x,
                mouse_y - window_center_y,
            )
            # 计算目标位置（锁定方向）
            widget_radius = self.width / 2
            self._locked_target_position = self._get_target_position(
                self.center_x,
                self.center_y,
                widget_radius,
                window_center_x,
                window_center_y,
                mouse_x,
                mouse_y,
            )
            self._target_position = self._locked_target_position
        elif is_motion_event:
            if self._should_follow_cursor(current_time):
                widget_radius = self.width / 2
                self._target_position = self._get_target_position(
                    self.center_x,
                    self.center_y,
                    widget_radius,
                    window_center_x,
                    window_center_y,
                    mouse_x,
                    mouse_y,
                )
                self._locked_target_position = None
            elif self._locked_target_position is not None:
                self._target_position = self._locked_target_position

        if self._joystick_state == JoystickState.INACTIVE:
            # 首次激活 - 只有点击事件才能激活
            if is_click_event:
                self._key_press_start_time = current_time
                self._is_long_press = False
                self._key_is_currently_pressed = True
                self._joystick_state = JoystickState.MOVING
                
                # 分配指针ID并发送DOWN事件
                pointer_id = self.pointer_id_manager.allocate(self)
                if pointer_id is None:
                    return False
                
                self._current_position = (self.center_x, self.center_y)
                self._emit_touch_event(AMotionEventAction.DOWN, position=self._current_position)
                
                # 开始平滑移动到边界
                self._start_smooth_move_to_boundary()
                
            else:
                # 移动事件在未激活状态下不处理
                return False
            
        elif self._joystick_state == JoystickState.MOVING:
            if is_click_event:
                # 移动中收到新点击，重置触发时间和长按状态
                self._key_press_start_time = current_time
                self._is_long_press = False
                self._key_is_currently_pressed = True
            elif is_motion_event:
                # 移动事件只更新目标位置，不重置计时
                pass
            
        elif self._joystick_state == JoystickState.HOLDING:
            if is_click_event:
                # 保持状态下收到新点击，瞬移并重置状态
                self._instant_move_to_boundary(current_time)
                self._key_is_currently_pressed = True
            elif is_motion_event:
                # 保持状态下的移动事件，瞬移但不重置计时状态
                self._current_position = self._target_position
                self._emit_touch_event(AMotionEventAction.MOVE)

        return True

    def on_key_released(
        self,
        key_combination: KeyCombination | None = None,
        event: "InputEvent | None" = None,
    ):
        """当映射的键释放时"""
        if self._joystick_state == JoystickState.INACTIVE:
            return True

        current_time = time.time()
        press_duration = current_time - self._key_press_start_time
        self._key_is_currently_pressed = False
        
        # 判断是点按还是长按
        if press_duration >= self._long_press_threshold:
            self._is_long_press = True

        if self._is_long_press:
            # 长按模式：立即结束
            self._finish_joystick_action()
        else:
            # 点按模式：松开右键后开始保持计时
            if self._joystick_state == JoystickState.MOVING:
                # 还在移动中，设置标记，等移动完成后开始计时
                pass
            elif self._joystick_state == JoystickState.HOLDING:
                # 已经在边界，立即开始保持计时
                self._start_hold_timer()

        return True

    def _should_follow_cursor(self, current_time: float) -> bool:
        if not self._key_is_currently_pressed:
            return False
        if self._is_long_press:
            return True
        if current_time - self._key_press_start_time >= self._long_press_threshold:
            self._is_long_press = True
            return True
        return False

    def setup_config(self) -> None:
        """设置右键行走的配置项"""
        calibrate_center_config = create_action_config(
            key=self.CALIBRATE_CENTER_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Center Calibration"),
            button_label=pgettext("Controller Widgets", "Calibrate"),
            description=pgettext(
                "Controller Widgets",
                "Click to enter calibration mode, then click the character position on screen.",
            ),
        )
        reset_center_config = create_action_config(
            key=self.RESET_CENTER_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Reset Center"),
            button_label=pgettext("Controller Widgets", "Reset"),
            description=pgettext(
                "Controller Widgets",
                "Clear the calibrated center and return to the screen center.",
            ),
        )
        center_x_config = create_text_config(
            key=self.CENTER_X_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Center X"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored calibration center X coordinate."
            ),
            visible=False,
        )
        center_y_config = create_text_config(
            key=self.CENTER_Y_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Center Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored calibration center Y coordinate."
            ),
            visible=False,
        )
        center_x_input_config = create_text_config(
            key=self.CENTER_X_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Center X (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Manual center X coordinate in pixels."
            ),
        )
        center_y_input_config = create_text_config(
            key=self.CENTER_Y_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Center Y (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Manual center Y coordinate in pixels."
            ),
        )
        apply_center_config = create_action_config(
            key=self.APPLY_CENTER_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Apply Center"),
            button_label=pgettext("Controller Widgets", "Apply"),
            description=pgettext(
                "Controller Widgets", "Apply the manual center coordinates."
            ),
        )
        x_gain_config = create_text_config(
            key=self.X_GAIN_CONFIG_KEY,
            label=pgettext("Controller Widgets", "X Gain"),
            value=str(self.GAIN_DEFAULT),
            description=pgettext(
                "Controller Widgets", "Persisted X gain for ellipse correction."
            ),
            visible=False,
        )
        y_gain_config = create_text_config(
            key=self.Y_GAIN_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Y Gain"),
            value=str(self.GAIN_DEFAULT),
            description=pgettext(
                "Controller Widgets", "Persisted Y gain for ellipse correction."
            ),
            visible=False,
        )
        x_gain_input_config = create_text_config(
            key=self.X_GAIN_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "X Gain"),
            value=str(self.GAIN_DEFAULT),
            description=pgettext(
                "Controller Widgets", "Ellipse correction gain for X axis (0.5–2.0)."
            ),
        )
        y_gain_input_config = create_text_config(
            key=self.Y_GAIN_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Y Gain"),
            value=str(self.GAIN_DEFAULT),
            description=pgettext(
                "Controller Widgets", "Ellipse correction gain for Y axis (0.5–2.0)."
            ),
        )
        apply_gain_config = create_action_config(
            key=self.APPLY_GAIN_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Apply Gains"),
            button_label=pgettext("Controller Widgets", "Apply"),
            description=pgettext(
                "Controller Widgets", "Validate and apply ellipse correction gains."
            ),
        )
        tune_angle_config = create_action_config(
            key=self.TUNE_ANGLE_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Tune Angle"),
            button_label=pgettext("Controller Widgets", "Tune"),
            description=pgettext(
                "Controller Widgets", "Live tuning overlay for ellipse correction."
            ),
        )
        up_dist_config = create_text_config(
            key=self.UP_DIST_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Up Distance (stored)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored up anchor distance in pixels."
            ),
            visible=False,
        )
        down_dist_config = create_text_config(
            key=self.DOWN_DIST_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Down Distance (stored)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored down anchor distance in pixels."
            ),
            visible=False,
        )
        left_dist_config = create_text_config(
            key=self.LEFT_DIST_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Left Distance (stored)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored left anchor distance in pixels."
            ),
            visible=False,
        )
        right_dist_config = create_text_config(
            key=self.RIGHT_DIST_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Right Distance (stored)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored right anchor distance in pixels."
            ),
            visible=False,
        )
        up_dist_input_config = create_text_config(
            key=self.UP_DIST_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Up Distance (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Anchor distance from center to top in pixels."
            ),
        )
        down_dist_input_config = create_text_config(
            key=self.DOWN_DIST_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Down Distance (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Anchor distance from center to bottom in pixels."
            ),
        )
        left_dist_input_config = create_text_config(
            key=self.LEFT_DIST_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Left Distance (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Anchor distance from center to left in pixels."
            ),
        )
        right_dist_input_config = create_text_config(
            key=self.RIGHT_DIST_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Right Distance (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Anchor distance from center to right in pixels."
            ),
        )
        apply_anchors_config = create_action_config(
            key=self.APPLY_ANCHORS_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Apply Anchors"),
            button_label=pgettext("Controller Widgets", "Apply"),
            description=pgettext(
                "Controller Widgets", "Validate and apply anchor distances."
            ),
        )
        reset_anchors_config = create_action_config(
            key=self.RESET_ANCHORS_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Reset Anchors"),
            button_label=pgettext("Controller Widgets", "Reset"),
            description=pgettext(
                "Controller Widgets", "Clear all anchor distances."
            ),
        )
        set_up_anchor_config = create_action_config(
            key=self.SET_UP_ANCHOR_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Set Up Anchor"),
            button_label=pgettext("Controller Widgets", "Set Up"),
            description=pgettext(
                "Controller Widgets", "Click then choose the top anchor position."
            ),
        )
        set_down_anchor_config = create_action_config(
            key=self.SET_DOWN_ANCHOR_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Set Down Anchor"),
            button_label=pgettext("Controller Widgets", "Set Down"),
            description=pgettext(
                "Controller Widgets", "Click then choose the bottom anchor position."
            ),
        )
        set_left_anchor_config = create_action_config(
            key=self.SET_LEFT_ANCHOR_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Set Left Anchor"),
            button_label=pgettext("Controller Widgets", "Set Left"),
            description=pgettext(
                "Controller Widgets", "Click then choose the left anchor position."
            ),
        )
        set_right_anchor_config = create_action_config(
            key=self.SET_RIGHT_ANCHOR_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Set Right Anchor"),
            button_label=pgettext("Controller Widgets", "Set Right"),
            description=pgettext(
                "Controller Widgets", "Click then choose the right anchor position."
            ),
        )
        deadzone_config = create_text_config(
            key=self.DEADZONE_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Deadzone (stored)"),
            value=str(self.DEADZONE_DEFAULT),
            description=pgettext(
                "Controller Widgets", "Stored deadzone size for normalized input."
            ),
            visible=False,
        )
        deadzone_input_config = create_text_config(
            key=self.DEADZONE_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Deadzone"),
            value=str(self.DEADZONE_DEFAULT),
            description=pgettext(
                "Controller Widgets", "Deadzone size (0.0–0.9) in normalized units."
            ),
        )
        apply_deadzone_config = create_action_config(
            key=self.APPLY_DEADZONE_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Apply Deadzone"),
            button_label=pgettext("Controller Widgets", "Apply"),
            description=pgettext(
                "Controller Widgets", "Validate and apply deadzone size."
            ),
        )

        self.add_config_item(calibrate_center_config)
        self.add_config_item(reset_center_config)
        self.add_config_item(center_x_config)
        self.add_config_item(center_y_config)
        self.add_config_item(center_x_input_config)
        self.add_config_item(center_y_input_config)
        self.add_config_item(apply_center_config)
        self.add_config_item(x_gain_config)
        self.add_config_item(y_gain_config)
        self.add_config_item(x_gain_input_config)
        self.add_config_item(y_gain_input_config)
        self.add_config_item(apply_gain_config)
        self.add_config_item(tune_angle_config)
        self.add_config_item(up_dist_config)
        self.add_config_item(down_dist_config)
        self.add_config_item(left_dist_config)
        self.add_config_item(right_dist_config)
        self.add_config_item(up_dist_input_config)
        self.add_config_item(down_dist_input_config)
        self.add_config_item(left_dist_input_config)
        self.add_config_item(right_dist_input_config)
        self.add_config_item(apply_anchors_config)
        self.add_config_item(reset_anchors_config)
        self.add_config_item(set_up_anchor_config)
        self.add_config_item(set_down_anchor_config)
        self.add_config_item(set_left_anchor_config)
        self.add_config_item(set_right_anchor_config)
        self.add_config_item(deadzone_config)
        self.add_config_item(deadzone_input_config)
        self.add_config_item(apply_deadzone_config)

        self.add_config_change_callback(
            self.CALIBRATE_CENTER_CONFIG_KEY, self._on_calibrate_center_clicked
        )
        self.add_config_change_callback(
            self.RESET_CENTER_CONFIG_KEY, self._on_reset_center_clicked
        )
        self.add_config_change_callback(
            self.APPLY_CENTER_CONFIG_KEY, self._on_apply_center_clicked
        )
        self.add_config_change_callback(
            self.APPLY_GAIN_CONFIG_KEY, self._on_apply_gain_clicked
        )
        self.add_config_change_callback(
            self.TUNE_ANGLE_CONFIG_KEY, self._on_tune_angle_clicked
        )
        self.add_config_change_callback(
            self.APPLY_ANCHORS_CONFIG_KEY, self._on_apply_anchors_clicked
        )
        self.add_config_change_callback(
            self.RESET_ANCHORS_CONFIG_KEY, self._on_reset_anchors_clicked
        )
        self.add_config_change_callback(
            self.SET_UP_ANCHOR_CONFIG_KEY, self._on_set_anchor_clicked
        )
        self.add_config_change_callback(
            self.SET_DOWN_ANCHOR_CONFIG_KEY, self._on_set_anchor_clicked
        )
        self.add_config_change_callback(
            self.SET_LEFT_ANCHOR_CONFIG_KEY, self._on_set_anchor_clicked
        )
        self.add_config_change_callback(
            self.SET_RIGHT_ANCHOR_CONFIG_KEY, self._on_set_anchor_clicked
        )
        self.add_config_change_callback(
            self.APPLY_DEADZONE_CONFIG_KEY, self._on_apply_deadzone_clicked
        )
        self._sync_center_inputs()
        self._sync_gain_inputs()
        self._sync_anchor_inputs()
        self._sync_deadzone_inputs()
        self.get_config_manager().connect(
            "confirmed",
            lambda *_args: (
                self._sync_center_inputs(),
                self._sync_gain_inputs(),
                self._sync_anchor_inputs(),
                self._sync_deadzone_inputs(),
                self._emit_overlay_event("refresh"),
            ),
        )

    def _on_calibrate_center_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._anchor_calibration_axis = None
        self._set_calibration_mode(True)

    def _on_reset_center_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._set_calibration_mode(False)
        self.set_config_value(self.CENTER_X_CONFIG_KEY, "")
        self.set_config_value(self.CENTER_Y_CONFIG_KEY, "")
        self.set_config_value(self.X_GAIN_CONFIG_KEY, self.GAIN_DEFAULT)
        self.set_config_value(self.Y_GAIN_CONFIG_KEY, self.GAIN_DEFAULT)
        self._sync_center_inputs()
        self._sync_gain_inputs()
        self._emit_overlay_event("refresh")

    def _on_apply_center_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        raw_x = self.get_config_value(self.CENTER_X_INPUT_CONFIG_KEY)
        raw_y = self.get_config_value(self.CENTER_Y_INPUT_CONFIG_KEY)
        try:
            x = float(raw_x)
            y = float(raw_y)
        except (TypeError, ValueError):
            return
        w, h = self._get_window_size()
        if not (0 <= x < w and 0 <= y < h):
            return
        self.set_config_value(self.CENTER_X_CONFIG_KEY, float(x))
        self.set_config_value(self.CENTER_Y_CONFIG_KEY, float(y))
        self._sync_center_inputs()
        self._emit_overlay_event("refresh")

    def _on_apply_gain_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        raw_x_gain = self.get_config_value(self.X_GAIN_INPUT_CONFIG_KEY)
        raw_y_gain = self.get_config_value(self.Y_GAIN_INPUT_CONFIG_KEY)
        x_gain = self._sanitize_gain_value(raw_x_gain)
        y_gain = self._sanitize_gain_value(raw_y_gain)
        if x_gain is None or y_gain is None:
            return
        self.set_config_value(self.X_GAIN_CONFIG_KEY, x_gain)
        self.set_config_value(self.Y_GAIN_CONFIG_KEY, y_gain)
        self._sync_gain_inputs()
        self._emit_overlay_event("refresh")

    def _on_tune_angle_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring or self.mapping_mode:
            return
        if self._tuning_mode:
            return
        self._start_tuning()

    def _on_mask_clicked(self, event: Event[dict[str, int]]) -> None:
        if not self._calibration_mode:
            return
        data = event.data or {}
        x = data.get("x")
        y = data.get("y")
        if x is None or y is None:
            return
        w, h = self._get_window_size()
        if x < 0 or y < 0 or x >= w or y >= h:
            return
        center = self._get_window_center()
        if self._anchor_calibration_axis is not None:
            axis = self._anchor_calibration_axis
            distance = self._get_anchor_distance_from_click(axis, center, (x, y))
            if distance is None:
                return
            config_key = self._get_anchor_config_key(axis)
            self.set_config_value(config_key, distance)
            self._sync_anchor_inputs()
            self._set_calibration_mode(False)
            self._emit_overlay_event("refresh")
            return
        self.set_config_value(self.CENTER_X_CONFIG_KEY, float(x))
        self.set_config_value(self.CENTER_Y_CONFIG_KEY, float(y))
        self._sync_center_inputs()
        self._set_calibration_mode(False)
        self._emit_overlay_event("refresh")

    def _get_calibrated_center(self) -> tuple[float, float] | None:
        raw_x = self.get_config_value(self.CENTER_X_CONFIG_KEY)
        raw_y = self.get_config_value(self.CENTER_Y_CONFIG_KEY)
        if raw_x in (None, "") or raw_y in (None, ""):
            return None
        try:
            x = float(raw_x)
            y = float(raw_y)
        except (TypeError, ValueError):
            return None
        w, h = self._get_window_size()
        if not (0 <= x < w and 0 <= y < h):
            return None
        return (x, y)

    def _sync_center_inputs(self) -> None:
        calibrated = self._get_calibrated_center()
        if calibrated is None:
            self.set_config_value(self.CENTER_X_INPUT_CONFIG_KEY, "")
            self.set_config_value(self.CENTER_Y_INPUT_CONFIG_KEY, "")
            return
        self.set_config_value(self.CENTER_X_INPUT_CONFIG_KEY, str(int(calibrated[0])))
        self.set_config_value(self.CENTER_Y_INPUT_CONFIG_KEY, str(int(calibrated[1])))

    def _sync_gain_inputs(self) -> None:
        x_gain, y_gain = self._get_gains()
        self.set_config_value(self.X_GAIN_INPUT_CONFIG_KEY, f"{x_gain:.2f}")
        self.set_config_value(self.Y_GAIN_INPUT_CONFIG_KEY, f"{y_gain:.2f}")

    def _set_calibration_mode(self, active: bool) -> None:
        self._calibration_mode = active
        if not active:
            self._anchor_calibration_axis = None
        self._emit_overlay_event("start" if active else "stop")

    def _emit_overlay_event(self, action: str) -> None:
        self.event_bus.emit(
            Event(
                EventType.RIGHT_CLICK_TO_WALK_OVERLAY,
                self,
                {"action": action, "widget": self},
            )
        )

    def get_effective_center(self) -> tuple[float, float]:
        return self._get_window_center()

    def get_calibrated_center(self) -> tuple[float, float] | None:
        return self._get_calibrated_center()

    @property
    def is_calibrating(self) -> bool:
        return self._calibration_mode

    def cancel_calibration(self) -> None:
        if not self._calibration_mode:
            return
        self._set_calibration_mode(False)

    def _sanitize_gain_value(self, raw_value: object) -> float | None:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        return min(max(value, self.GAIN_MIN), self.GAIN_MAX)

    def _get_gains(self) -> tuple[float, float]:
        raw_x = self.get_config_value(self.X_GAIN_CONFIG_KEY)
        raw_y = self.get_config_value(self.Y_GAIN_CONFIG_KEY)
        x_gain = self._sanitize_gain_value(raw_x)
        y_gain = self._sanitize_gain_value(raw_y)
        return (
            x_gain if x_gain is not None else self.GAIN_DEFAULT,
            y_gain if y_gain is not None else self.GAIN_DEFAULT,
        )

    def _get_tuning_gains(self) -> tuple[float, float]:
        if self._tuning_mode and self._tuning_x_gain is not None and self._tuning_y_gain is not None:
            return self._tuning_x_gain, self._tuning_y_gain
        return self._get_gains()

    def _start_tuning(self) -> None:
        self._tuning_mode = True
        x_gain, y_gain = self._get_gains()
        self._tuning_x_gain = x_gain
        self._tuning_y_gain = y_gain
        self._emit_overlay_event("tune_start")

    def _stop_tuning(self) -> None:
        if not self._tuning_mode:
            return
        self._tuning_mode = False
        self._tuning_x_gain = None
        self._tuning_y_gain = None
        self._emit_overlay_event("tune_stop")

    def cancel_tuning(self) -> None:
        if not self._tuning_mode:
            return
        self._sync_gain_inputs()
        self._stop_tuning()

    def _apply_tuning(self) -> None:
        if not self._tuning_mode:
            return
        x_gain = self._sanitize_gain_value(self._tuning_x_gain)
        y_gain = self._sanitize_gain_value(self._tuning_y_gain)
        if x_gain is None or y_gain is None:
            self.cancel_tuning()
            return
        self.set_config_value(self.X_GAIN_CONFIG_KEY, x_gain)
        self.set_config_value(self.Y_GAIN_CONFIG_KEY, y_gain)
        self._sync_gain_inputs()
        self._stop_tuning()

    def handle_tuning_key(self, keyval: int, state: Gdk.ModifierType) -> bool:
        if not self._tuning_mode:
            return False
        if keyval in (Gdk.KEY_Escape,):
            self.cancel_tuning()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._apply_tuning()
            return True
        step = 0.05 if state & Gdk.ModifierType.SHIFT_MASK else 0.01
        if keyval in (Gdk.KEY_q, Gdk.KEY_Q):
            self._adjust_tuning_gain("x", -step)
            return True
        if keyval in (Gdk.KEY_a, Gdk.KEY_A):
            self._adjust_tuning_gain("x", step)
            return True
        if keyval in (Gdk.KEY_w, Gdk.KEY_W):
            self._adjust_tuning_gain("y", -step)
            return True
        if keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self._adjust_tuning_gain("y", step)
            return True
        return False

    def _adjust_tuning_gain(self, axis: str, delta: float) -> None:
        if axis == "x":
            current = self._tuning_x_gain if self._tuning_x_gain is not None else self.GAIN_DEFAULT
            self._tuning_x_gain = min(max(current + delta, self.GAIN_MIN), self.GAIN_MAX)
        else:
            current = self._tuning_y_gain if self._tuning_y_gain is not None else self.GAIN_DEFAULT
            self._tuning_y_gain = min(max(current + delta, self.GAIN_MIN), self.GAIN_MAX)
        self._emit_overlay_event("refresh")

    @staticmethod
    def _vector_to_angle(dx: float, dy: float) -> float:
        angle = math.degrees(math.atan2(dy, dx))
        if angle < 0:
            angle += 360
        return angle

    def get_tuning_overlay_data(
        self, cursor_position: tuple[int, int] | None
    ) -> dict[str, object]:
        x_gain, y_gain = self._get_tuning_gains()
        data: dict[str, object] = {
            "x_gain": x_gain,
            "y_gain": y_gain,
            "raw_angle": None,
            "corrected_angle": None,
            "raw_vector": None,
            "corrected_vector": None,
            "center": self._get_window_center(),
        }
        if cursor_position is None:
            return data
        center_x, center_y = data["center"]
        dx = cursor_position[0] - center_x
        dy = cursor_position[1] - center_y
        raw_angle = self._vector_to_angle(dx, dy)
        dx2 = dx * x_gain
        dy2 = dy * y_gain
        corrected_angle = self._vector_to_angle(dx2, dy2)
        data.update(
            {
                "raw_angle": raw_angle,
                "corrected_angle": corrected_angle,
                "raw_vector": (dx, dy),
                "corrected_vector": (dx2, dy2),
            }
        )
        return data

    def on_delete(self):
        self._emit_overlay_event("unregister")
        super().on_delete()

    @property
    def mapping_start_x(self):
        return self.x + self.width / 2 - self.MAPPING_MODE_WIDTH / 2

    @property
    def mapping_start_y(self):
        return self.y + self.height / 2 - self.MAPPING_MODE_HEIGHT / 2

    @property
    def center_x(self):
        return self.x + self.width / 2

    @property
    def center_y(self):
        return self.y + self.height / 2

    @property
    def is_tuning(self) -> bool:
        return self._tuning_mode

    def _sanitize_anchor_distance(self, raw_value: object) -> int | None:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return value

    def _get_anchor_distances(self) -> tuple[int, int, int, int] | None:
        raw_up = self.get_config_value(self.UP_DIST_CONFIG_KEY)
        raw_down = self.get_config_value(self.DOWN_DIST_CONFIG_KEY)
        raw_left = self.get_config_value(self.LEFT_DIST_CONFIG_KEY)
        raw_right = self.get_config_value(self.RIGHT_DIST_CONFIG_KEY)
        up = self._sanitize_anchor_distance(raw_up)
        down = self._sanitize_anchor_distance(raw_down)
        left = self._sanitize_anchor_distance(raw_left)
        right = self._sanitize_anchor_distance(raw_right)
        if None in (up, down, left, right):
            return None
        return (up, down, left, right)

    def _sync_anchor_inputs(self) -> None:
        raw_up = self._sanitize_anchor_distance(
            self.get_config_value(self.UP_DIST_CONFIG_KEY)
        )
        raw_down = self._sanitize_anchor_distance(
            self.get_config_value(self.DOWN_DIST_CONFIG_KEY)
        )
        raw_left = self._sanitize_anchor_distance(
            self.get_config_value(self.LEFT_DIST_CONFIG_KEY)
        )
        raw_right = self._sanitize_anchor_distance(
            self.get_config_value(self.RIGHT_DIST_CONFIG_KEY)
        )
        self.set_config_value(
            self.UP_DIST_INPUT_CONFIG_KEY, "" if raw_up is None else str(raw_up)
        )
        self.set_config_value(
            self.DOWN_DIST_INPUT_CONFIG_KEY, "" if raw_down is None else str(raw_down)
        )
        self.set_config_value(
            self.LEFT_DIST_INPUT_CONFIG_KEY, "" if raw_left is None else str(raw_left)
        )
        self.set_config_value(
            self.RIGHT_DIST_INPUT_CONFIG_KEY, "" if raw_right is None else str(raw_right)
        )

    def _on_apply_anchors_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        up = self._sanitize_anchor_distance(
            self.get_config_value(self.UP_DIST_INPUT_CONFIG_KEY)
        )
        down = self._sanitize_anchor_distance(
            self.get_config_value(self.DOWN_DIST_INPUT_CONFIG_KEY)
        )
        left = self._sanitize_anchor_distance(
            self.get_config_value(self.LEFT_DIST_INPUT_CONFIG_KEY)
        )
        right = self._sanitize_anchor_distance(
            self.get_config_value(self.RIGHT_DIST_INPUT_CONFIG_KEY)
        )
        if None in (up, down, left, right):
            return
        self.set_config_value(self.UP_DIST_CONFIG_KEY, up)
        self.set_config_value(self.DOWN_DIST_CONFIG_KEY, down)
        self.set_config_value(self.LEFT_DIST_CONFIG_KEY, left)
        self.set_config_value(self.RIGHT_DIST_CONFIG_KEY, right)
        self._sync_anchor_inputs()
        self._emit_overlay_event("refresh")

    def _on_reset_anchors_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self.set_config_value(self.UP_DIST_CONFIG_KEY, "")
        self.set_config_value(self.DOWN_DIST_CONFIG_KEY, "")
        self.set_config_value(self.LEFT_DIST_CONFIG_KEY, "")
        self.set_config_value(self.RIGHT_DIST_CONFIG_KEY, "")
        self._sync_anchor_inputs()
        self._emit_overlay_event("refresh")

    def _on_set_anchor_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring or self.mapping_mode:
            return
        axis_map = {
            self.SET_UP_ANCHOR_CONFIG_KEY: "up",
            self.SET_DOWN_ANCHOR_CONFIG_KEY: "down",
            self.SET_LEFT_ANCHOR_CONFIG_KEY: "left",
            self.SET_RIGHT_ANCHOR_CONFIG_KEY: "right",
        }
        axis = axis_map.get(key)
        if axis is None:
            return
        self._anchor_calibration_axis = axis
        self._set_calibration_mode(True)

    def _get_anchor_distance_from_click(
        self,
        axis: str,
        center: tuple[float, float],
        click: tuple[int, int],
    ) -> int | None:
        cx, cy = center
        x, y = click
        if axis == "up":
            distance = cy - y
        elif axis == "down":
            distance = y - cy
        elif axis == "left":
            distance = cx - x
        elif axis == "right":
            distance = x - cx
        else:
            return None
        if distance <= 0:
            return None
        return int(distance)

    def _get_anchor_config_key(self, axis: str) -> str:
        return {
            "up": self.UP_DIST_CONFIG_KEY,
            "down": self.DOWN_DIST_CONFIG_KEY,
            "left": self.LEFT_DIST_CONFIG_KEY,
            "right": self.RIGHT_DIST_CONFIG_KEY,
        }[axis]

    def get_anchor_overlay_data(self) -> dict[str, object] | None:
        anchors = self._get_anchor_distances()
        if anchors is None:
            return None
        center = self._get_window_center()
        up_dist, down_dist, left_dist, right_dist = anchors
        cx, cy = center
        anchor_points = {
            "up": (cx, cy - up_dist),
            "down": (cx, cy + down_dist),
            "left": (cx - left_dist, cy),
            "right": (cx + right_dist, cy),
        }
        boundary_points = self._get_anchor_boundary_points(center, anchors)
        return {
            "center": center,
            "anchors": anchor_points,
            "boundary": boundary_points,
        }

    def _get_anchor_boundary_points(
        self,
        center: tuple[float, float],
        anchors: tuple[int, int, int, int],
        segments: int = 120,
    ) -> list[tuple[float, float]]:
        cx, cy = center
        up_dist, down_dist, left_dist, right_dist = anchors
        points: list[tuple[float, float]] = []
        for i in range(segments + 1):
            angle = (i / segments) * 2 * math.pi
            degrees = math.degrees(angle) % 360
            if degrees <= 90:
                t = degrees / 90
                radius = right_dist + (down_dist - right_dist) * t
            elif degrees <= 180:
                t = (degrees - 90) / 90
                radius = down_dist + (left_dist - down_dist) * t
            elif degrees <= 270:
                t = (degrees - 180) / 90
                radius = left_dist + (up_dist - left_dist) * t
            else:
                t = (degrees - 270) / 90
                radius = up_dist + (right_dist - up_dist) * t
            points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
        return points

    def _sanitize_deadzone(self, raw_value: object) -> float | None:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        return min(max(value, self.DEADZONE_MIN), self.DEADZONE_MAX)

    def _get_deadzone(self) -> float:
        raw_value = self.get_config_value(self.DEADZONE_CONFIG_KEY)
        deadzone = self._sanitize_deadzone(raw_value)
        return deadzone if deadzone is not None else self.DEADZONE_DEFAULT

    def _sync_deadzone_inputs(self) -> None:
        deadzone = self._get_deadzone()
        self.set_config_value(self.DEADZONE_INPUT_CONFIG_KEY, f"{deadzone:.2f}")

    def _on_apply_deadzone_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        raw_deadzone = self.get_config_value(self.DEADZONE_INPUT_CONFIG_KEY)
        deadzone = self._sanitize_deadzone(raw_deadzone)
        if deadzone is None:
            return
        self.set_config_value(self.DEADZONE_CONFIG_KEY, deadzone)
        self._sync_deadzone_inputs()
