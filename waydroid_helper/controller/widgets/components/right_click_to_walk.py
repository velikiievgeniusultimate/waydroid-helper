#!/usr/bin/env python3
import math
import time
from enum import Enum
from gettext import pgettext
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from cairo import Context, Surface
    from gi.repository import Gtk

from gi.repository import GLib, Gdk, Gtk

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
from waydroid_helper.controller.widgets.config import (
    create_action_config,
    create_switch_config,
    create_text_config,
)

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
    SETTINGS_PANEL_MIN_WIDTH = 380
    SETTINGS_PANEL_MIN_HEIGHT = 420
    SETTINGS_PANEL_MAX_HEIGHT = 650
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
    GAIN_ENABLED_CONFIG_KEY = "gain_enabled"
    X_GAIN_CONFIG_KEY = "x_gain"
    Y_GAIN_CONFIG_KEY = "y_gain"
    X_GAIN_INPUT_CONFIG_KEY = "x_gain_input"
    Y_GAIN_INPUT_CONFIG_KEY = "y_gain_input"
    APPLY_GAIN_CONFIG_KEY = "apply_gains"
    TUNE_ANGLE_CONFIG_KEY = "tune_angle"
    ANCHOR_UP_CONFIG_KEY = "anchor_up_dist_px"
    ANCHOR_DOWN_CONFIG_KEY = "anchor_down_dist_px"
    ANCHOR_LEFT_CONFIG_KEY = "anchor_left_dist_px"
    ANCHOR_RIGHT_CONFIG_KEY = "anchor_right_dist_px"
    ANCHOR_UP_INPUT_CONFIG_KEY = "anchor_up_input"
    ANCHOR_DOWN_INPUT_CONFIG_KEY = "anchor_down_input"
    ANCHOR_LEFT_INPUT_CONFIG_KEY = "anchor_left_input"
    ANCHOR_RIGHT_INPUT_CONFIG_KEY = "anchor_right_input"
    APPLY_ANCHORS_CONFIG_KEY = "apply_anchors"
    RESET_ANCHORS_CONFIG_KEY = "reset_anchors"
    SET_ANCHOR_UP_CONFIG_KEY = "set_anchor_up"
    SET_ANCHOR_DOWN_CONFIG_KEY = "set_anchor_down"
    SET_ANCHOR_LEFT_CONFIG_KEY = "set_anchor_left"
    SET_ANCHOR_RIGHT_CONFIG_KEY = "set_anchor_right"
    CANCEL_ANCHOR_SET_CONFIG_KEY = "cancel_anchor_set"
    ANCHOR_DEADZONE_CONFIG_KEY = "anchor_deadzone"
    GAIN_DEFAULT = 1.0
    GAIN_MIN = 0.5
    GAIN_MAX = 2.0
    ANCHOR_MAX_MULTIPLIER = 4
    DEADZONE_DEFAULT = 0.1
    DEADZONE_MAX = 0.95

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
        self._anchor_set_mode: str | None = None

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
        """计算目标位置（圆边界上的交点）"""
        anchor_vector = self._get_anchor_normalized_vector(x0, y0, x1, y1)
        if anchor_vector is not None:
            nx, ny = anchor_vector
            return (cx + nx * r, cy + ny * r)
        dx = x1 - x0
        dy = y1 - y0
        x_gain, y_gain = self._get_gains()
        dx *= x_gain
        dy *= y_gain
        length = math.hypot(dx, dy)
        if length == 0:
            return (cx, cy)  # 如果没有方向，返回中心点

        # 单位方向向量
        dx /= length
        dy /= length

        # 从圆心出发沿着方向 (dx, dy)，走 r 的距离
        px = cx + dx * r
        py = cy + dy * r

        return (px, py)

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
        gain_enabled_config = create_switch_config(
            key=self.GAIN_ENABLED_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Enable Ellipse Correction"),
            value=True,
            description=pgettext(
                "Controller Widgets",
                "Enable gain-based correction for non-circular movement inputs.",
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
        anchor_up_config = create_text_config(
            key=self.ANCHOR_UP_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Up Anchor Distance"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored upward anchor distance in pixels."
            ),
            visible=False,
        )
        anchor_down_config = create_text_config(
            key=self.ANCHOR_DOWN_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Down Anchor Distance"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored downward anchor distance in pixels."
            ),
            visible=False,
        )
        anchor_left_config = create_text_config(
            key=self.ANCHOR_LEFT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Left Anchor Distance"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored leftward anchor distance in pixels."
            ),
            visible=False,
        )
        anchor_right_config = create_text_config(
            key=self.ANCHOR_RIGHT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Right Anchor Distance"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored rightward anchor distance in pixels."
            ),
            visible=False,
        )
        anchor_up_input_config = create_text_config(
            key=self.ANCHOR_UP_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Up Distance (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Distance from center to the upper anchor."
            ),
        )
        anchor_down_input_config = create_text_config(
            key=self.ANCHOR_DOWN_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Down Distance (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Distance from center to the lower anchor."
            ),
        )
        anchor_left_input_config = create_text_config(
            key=self.ANCHOR_LEFT_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Left Distance (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Distance from center to the left anchor."
            ),
        )
        anchor_right_input_config = create_text_config(
            key=self.ANCHOR_RIGHT_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Right Distance (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Distance from center to the right anchor."
            ),
        )
        apply_anchors_config = create_action_config(
            key=self.APPLY_ANCHORS_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Apply Anchors"),
            button_label=pgettext("Controller Widgets", "Apply"),
            description=pgettext(
                "Controller Widgets",
                "Validate and apply the four anchor distances.",
            ),
        )
        reset_anchors_config = create_action_config(
            key=self.RESET_ANCHORS_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Reset Anchors"),
            button_label=pgettext("Controller Widgets", "Reset"),
            description=pgettext(
                "Controller Widgets",
                "Clear all calibrated anchor distances.",
            ),
        )
        set_anchor_up_config = create_action_config(
            key=self.SET_ANCHOR_UP_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Set Up"),
            button_label=pgettext("Controller Widgets", "Set Up"),
            description=pgettext(
                "Controller Widgets", "Click the upper boundary on the screen."
            ),
        )
        set_anchor_down_config = create_action_config(
            key=self.SET_ANCHOR_DOWN_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Set Down"),
            button_label=pgettext("Controller Widgets", "Set Down"),
            description=pgettext(
                "Controller Widgets", "Click the lower boundary on the screen."
            ),
        )
        set_anchor_left_config = create_action_config(
            key=self.SET_ANCHOR_LEFT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Set Left"),
            button_label=pgettext("Controller Widgets", "Set Left"),
            description=pgettext(
                "Controller Widgets", "Click the left boundary on the screen."
            ),
        )
        set_anchor_right_config = create_action_config(
            key=self.SET_ANCHOR_RIGHT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Set Right"),
            button_label=pgettext("Controller Widgets", "Set Right"),
            description=pgettext(
                "Controller Widgets", "Click the right boundary on the screen."
            ),
        )
        cancel_anchor_set_config = create_action_config(
            key=self.CANCEL_ANCHOR_SET_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Cancel Anchor Set"),
            button_label=pgettext("Controller Widgets", "Cancel"),
            description=pgettext(
                "Controller Widgets", "Exit anchor capture mode without saving."
            ),
        )
        anchor_deadzone_config = create_text_config(
            key=self.ANCHOR_DEADZONE_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Deadzone (0-1)"),
            value=f"{self.DEADZONE_DEFAULT:.2f}",
            description=pgettext(
                "Controller Widgets",
                "Normalized deadzone before movement begins (0.0–1.0).",
            ),
        )

        self.add_config_item(calibrate_center_config)
        self.add_config_item(reset_center_config)
        self.add_config_item(center_x_config)
        self.add_config_item(center_y_config)
        self.add_config_item(center_x_input_config)
        self.add_config_item(center_y_input_config)
        self.add_config_item(apply_center_config)
        self.add_config_item(gain_enabled_config)
        self.add_config_item(x_gain_config)
        self.add_config_item(y_gain_config)
        self.add_config_item(x_gain_input_config)
        self.add_config_item(y_gain_input_config)
        self.add_config_item(apply_gain_config)
        self.add_config_item(tune_angle_config)
        self.add_config_item(anchor_up_config)
        self.add_config_item(anchor_down_config)
        self.add_config_item(anchor_left_config)
        self.add_config_item(anchor_right_config)
        self.add_config_item(anchor_up_input_config)
        self.add_config_item(anchor_down_input_config)
        self.add_config_item(anchor_left_input_config)
        self.add_config_item(anchor_right_input_config)
        self.add_config_item(apply_anchors_config)
        self.add_config_item(reset_anchors_config)
        self.add_config_item(set_anchor_up_config)
        self.add_config_item(set_anchor_down_config)
        self.add_config_item(set_anchor_left_config)
        self.add_config_item(set_anchor_right_config)
        self.add_config_item(cancel_anchor_set_config)
        self.add_config_item(anchor_deadzone_config)

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
            self.GAIN_ENABLED_CONFIG_KEY, self._on_gain_enabled_changed
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
            self.SET_ANCHOR_UP_CONFIG_KEY, self._on_set_anchor_up_clicked
        )
        self.add_config_change_callback(
            self.SET_ANCHOR_DOWN_CONFIG_KEY, self._on_set_anchor_down_clicked
        )
        self.add_config_change_callback(
            self.SET_ANCHOR_LEFT_CONFIG_KEY, self._on_set_anchor_left_clicked
        )
        self.add_config_change_callback(
            self.SET_ANCHOR_RIGHT_CONFIG_KEY, self._on_set_anchor_right_clicked
        )
        self.add_config_change_callback(
            self.CANCEL_ANCHOR_SET_CONFIG_KEY, self._on_cancel_anchor_set_clicked
        )
        self._sync_center_inputs()
        self._sync_gain_inputs()
        self._sync_anchor_inputs()
        self._set_gain_controls_visible(self._is_gain_enabled())
        self._set_anchor_controls_visible(not self.mapping_mode)
        self.get_config_manager().connect(
            "confirmed",
            lambda *_args: (
                self._sync_center_inputs(),
                self._sync_gain_inputs(),
                self._sync_anchor_inputs(),
                self._emit_overlay_event("refresh"),
            ),
        )

    def create_settings_panel(self) -> Gtk.Widget:
        config_manager = self.get_config_manager()
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        panel.set_margin_top(6)
        panel.set_margin_bottom(6)
        panel.set_margin_start(6)
        panel.set_margin_end(6)

        intro = Gtk.Label(
            label=pgettext(
                "Controller Widgets",
                "Configure center calibration and optional ellipse correction.",
            ),
            xalign=0,
        )
        intro.set_wrap(True)
        panel.append(intro)

        def add_missing_label(section: Gtk.Box, key: str) -> None:
            label = Gtk.Label(
                label=pgettext(
                    "Controller Widgets", "Unable to load setting: {key}"
                ).format(key=key),
                xalign=0,
            )
            label.set_wrap(True)
            section.append(label)

        def build_section(
            title: str,
            keys: list[str],
            description: str | None = None,
            expanded: bool = True,
            extra_widgets: list[Gtk.Widget] | None = None,
        ) -> Gtk.Expander:
            expander = Gtk.Expander(label=title)
            expander.set_expanded(expanded)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            if description:
                desc_label = Gtk.Label(label=description, xalign=0)
                desc_label.set_wrap(True)
                box.append(desc_label)
            for key in keys:
                widget = config_manager.create_ui_widget_for_key(key)
                if widget is None:
                    add_missing_label(box, key)
                else:
                    box.append(widget)
            if extra_widgets:
                for widget in extra_widgets:
                    box.append(widget)
            expander.set_child(box)
            return expander

        panel.append(
            build_section(
                pgettext("Controller Widgets", "Center Calibration"),
                [
                    self.CALIBRATE_CENTER_CONFIG_KEY,
                    self.RESET_CENTER_CONFIG_KEY,
                    self.CENTER_X_INPUT_CONFIG_KEY,
                    self.CENTER_Y_INPUT_CONFIG_KEY,
                    self.APPLY_CENTER_CONFIG_KEY,
                ],
                description=pgettext(
                    "Controller Widgets",
                    "Calibrate by clicking the character position on screen, or enter pixel coordinates manually.",
                ),
                expanded=True,
            )
        )

        tune_hint = Gtk.Label(
            label=pgettext(
                "Controller Widgets",
                "Tuning overlay is available while in Mapping mode.",
            ),
            xalign=0,
        )
        tune_hint.set_wrap(True)

        panel.append(
            build_section(
                pgettext("Controller Widgets", "Direction Mapping"),
                [
                    self.GAIN_ENABLED_CONFIG_KEY,
                    self.X_GAIN_INPUT_CONFIG_KEY,
                    self.Y_GAIN_INPUT_CONFIG_KEY,
                    self.APPLY_GAIN_CONFIG_KEY,
                    self.TUNE_ANGLE_CONFIG_KEY,
                ],
                description=pgettext(
                    "Controller Widgets",
                    "Use ellipse correction gains to compensate for uneven movement wheels.",
                ),
                expanded=True,
                extra_widgets=[tune_hint],
            )
        )

        panel.append(
            build_section(
                pgettext("Controller Widgets", "Anchor Calibration"),
                [
                    self.ANCHOR_UP_INPUT_CONFIG_KEY,
                    self.ANCHOR_DOWN_INPUT_CONFIG_KEY,
                    self.ANCHOR_LEFT_INPUT_CONFIG_KEY,
                    self.ANCHOR_RIGHT_INPUT_CONFIG_KEY,
                    self.ANCHOR_DEADZONE_CONFIG_KEY,
                    self.APPLY_ANCHORS_CONFIG_KEY,
                    self.RESET_ANCHORS_CONFIG_KEY,
                    self.SET_ANCHOR_UP_CONFIG_KEY,
                    self.SET_ANCHOR_DOWN_CONFIG_KEY,
                    self.SET_ANCHOR_LEFT_CONFIG_KEY,
                    self.SET_ANCHOR_RIGHT_CONFIG_KEY,
                    self.CANCEL_ANCHOR_SET_CONFIG_KEY,
                ],
                description=pgettext(
                    "Controller Widgets",
                    "Define four anchor distances from the calibrated center (in pixels).",
                ),
                expanded=False,
            )
        )

        tune_widget = config_manager.ui_widgets.get(self.TUNE_ANGLE_CONFIG_KEY)
        if tune_widget is not None:
            tune_widget.set_sensitive(self.mapping_mode)

        return panel

    def _on_calibrate_center_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
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

    def _on_gain_enabled_changed(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        enabled = self._is_gain_enabled()
        self._set_gain_controls_visible(enabled)
        if not enabled:
            self.cancel_tuning()
        self._emit_overlay_event("refresh")

    def _on_apply_gain_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        if not self._is_gain_enabled():
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
        if restoring or not self.mapping_mode or not self._is_gain_enabled():
            return
        if self._tuning_mode:
            return
        self._start_tuning()

    def _on_apply_anchors_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        raw_up = self.get_config_value(self.ANCHOR_UP_INPUT_CONFIG_KEY)
        raw_down = self.get_config_value(self.ANCHOR_DOWN_INPUT_CONFIG_KEY)
        raw_left = self.get_config_value(self.ANCHOR_LEFT_INPUT_CONFIG_KEY)
        raw_right = self.get_config_value(self.ANCHOR_RIGHT_INPUT_CONFIG_KEY)
        up = self._sanitize_anchor_distance(raw_up)
        down = self._sanitize_anchor_distance(raw_down)
        left = self._sanitize_anchor_distance(raw_left)
        right = self._sanitize_anchor_distance(raw_right)
        if None in (up, down, left, right):
            return
        self._store_anchor_distances(up, down, left, right)
        self._sync_anchor_inputs()
        self._emit_overlay_event("refresh")

    def _on_reset_anchors_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._reset_anchor_distances()
        self._sync_anchor_inputs()
        self.cancel_anchor_set()
        self._emit_overlay_event("refresh")

    def _on_set_anchor_up_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._start_anchor_set_mode("up")

    def _on_set_anchor_down_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._start_anchor_set_mode("down")

    def _on_set_anchor_left_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._start_anchor_set_mode("left")

    def _on_set_anchor_right_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._start_anchor_set_mode("right")

    def _on_cancel_anchor_set_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self.cancel_anchor_set()

    def _on_mask_clicked(self, event: Event[dict[str, int]]) -> None:
        data = event.data or {}
        x = data.get("x")
        y = data.get("y")
        if x is None or y is None:
            return
        w, h = self._get_window_size()
        if x < 0 or y < 0 or x >= w or y >= h:
            return
        if self._anchor_set_mode is not None:
            self._handle_anchor_click(x, y)
            return
        if not self._calibration_mode:
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
        x_gain, y_gain = self._get_saved_gains()
        self.set_config_value(self.X_GAIN_INPUT_CONFIG_KEY, f"{x_gain:.2f}")
        self.set_config_value(self.Y_GAIN_INPUT_CONFIG_KEY, f"{y_gain:.2f}")

    def _sync_anchor_inputs(self) -> None:
        up = self._sanitize_anchor_distance(
            self.get_config_value(self.ANCHOR_UP_CONFIG_KEY)
        )
        down = self._sanitize_anchor_distance(
            self.get_config_value(self.ANCHOR_DOWN_CONFIG_KEY)
        )
        left = self._sanitize_anchor_distance(
            self.get_config_value(self.ANCHOR_LEFT_CONFIG_KEY)
        )
        right = self._sanitize_anchor_distance(
            self.get_config_value(self.ANCHOR_RIGHT_CONFIG_KEY)
        )
        self.set_config_value(self.ANCHOR_UP_INPUT_CONFIG_KEY, str(up) if up else "")
        self.set_config_value(self.ANCHOR_DOWN_INPUT_CONFIG_KEY, str(down) if down else "")
        self.set_config_value(self.ANCHOR_LEFT_INPUT_CONFIG_KEY, str(left) if left else "")
        self.set_config_value(self.ANCHOR_RIGHT_INPUT_CONFIG_KEY, str(right) if right else "")

    def _set_gain_controls_visible(self, enabled: bool) -> None:
        manager = self.get_config_manager()
        for key in (
            self.X_GAIN_INPUT_CONFIG_KEY,
            self.Y_GAIN_INPUT_CONFIG_KEY,
            self.APPLY_GAIN_CONFIG_KEY,
            self.TUNE_ANGLE_CONFIG_KEY,
        ):
            manager.set_visible(key, enabled)

    def _set_anchor_controls_visible(self, visible: bool) -> None:
        manager = self.get_config_manager()
        for key in (
            self.ANCHOR_UP_INPUT_CONFIG_KEY,
            self.ANCHOR_DOWN_INPUT_CONFIG_KEY,
            self.ANCHOR_LEFT_INPUT_CONFIG_KEY,
            self.ANCHOR_RIGHT_INPUT_CONFIG_KEY,
            self.ANCHOR_DEADZONE_CONFIG_KEY,
            self.APPLY_ANCHORS_CONFIG_KEY,
            self.RESET_ANCHORS_CONFIG_KEY,
            self.SET_ANCHOR_UP_CONFIG_KEY,
            self.SET_ANCHOR_DOWN_CONFIG_KEY,
            self.SET_ANCHOR_LEFT_CONFIG_KEY,
            self.SET_ANCHOR_RIGHT_CONFIG_KEY,
            self.CANCEL_ANCHOR_SET_CONFIG_KEY,
        ):
            manager.set_visible(key, visible)

    def _set_calibration_mode(self, active: bool) -> None:
        if active:
            self.cancel_anchor_set()
        self._calibration_mode = active
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
        self.cancel_anchor_set()

    def cancel_anchor_set(self) -> None:
        if self._anchor_set_mode is None:
            return
        self._anchor_set_mode = None
        self._emit_overlay_event("stop")

    def _sanitize_gain_value(self, raw_value: object) -> float | None:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        return min(max(value, self.GAIN_MIN), self.GAIN_MAX)

    def _sanitize_anchor_distance(self, raw_value: object) -> int | None:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or not value.is_integer():
            return None
        value_int = int(value)
        if value_int <= 0:
            return None
        limit = self._get_anchor_distance_limit()
        if value_int > limit:
            return None
        return value_int

    def _get_anchor_distance_limit(self) -> int:
        w, h = self._get_window_size()
        return self.ANCHOR_MAX_MULTIPLIER * max(w, h)

    def _get_anchor_distances(self) -> tuple[int, int, int, int] | None:
        raw_up = self.get_config_value(self.ANCHOR_UP_CONFIG_KEY)
        raw_down = self.get_config_value(self.ANCHOR_DOWN_CONFIG_KEY)
        raw_left = self.get_config_value(self.ANCHOR_LEFT_CONFIG_KEY)
        raw_right = self.get_config_value(self.ANCHOR_RIGHT_CONFIG_KEY)
        up = self._sanitize_anchor_distance(raw_up)
        down = self._sanitize_anchor_distance(raw_down)
        left = self._sanitize_anchor_distance(raw_left)
        right = self._sanitize_anchor_distance(raw_right)
        if None in (up, down, left, right):
            return None
        return (up, down, left, right)

    def _store_anchor_distances(
        self, up: int, down: int, left: int, right: int
    ) -> None:
        self.set_config_value(self.ANCHOR_UP_CONFIG_KEY, up)
        self.set_config_value(self.ANCHOR_DOWN_CONFIG_KEY, down)
        self.set_config_value(self.ANCHOR_LEFT_CONFIG_KEY, left)
        self.set_config_value(self.ANCHOR_RIGHT_CONFIG_KEY, right)

    def _reset_anchor_distances(self) -> None:
        self.set_config_value(self.ANCHOR_UP_CONFIG_KEY, "")
        self.set_config_value(self.ANCHOR_DOWN_CONFIG_KEY, "")
        self.set_config_value(self.ANCHOR_LEFT_CONFIG_KEY, "")
        self.set_config_value(self.ANCHOR_RIGHT_CONFIG_KEY, "")

    def _get_deadzone(self) -> float:
        raw_deadzone = self.get_config_value(self.ANCHOR_DEADZONE_CONFIG_KEY)
        try:
            value = float(raw_deadzone)
        except (TypeError, ValueError):
            return self.DEADZONE_DEFAULT
        if not math.isfinite(value):
            return self.DEADZONE_DEFAULT
        return min(max(value, 0.0), self.DEADZONE_MAX)

    def _is_gain_enabled(self) -> bool:
        raw = self.get_config_value(self.GAIN_ENABLED_CONFIG_KEY)
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return True
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw)

    def _get_saved_gains(self) -> tuple[float, float]:
        raw_x = self.get_config_value(self.X_GAIN_CONFIG_KEY)
        raw_y = self.get_config_value(self.Y_GAIN_CONFIG_KEY)
        x_gain = self._sanitize_gain_value(raw_x)
        y_gain = self._sanitize_gain_value(raw_y)
        return (
            x_gain if x_gain is not None else self.GAIN_DEFAULT,
            y_gain if y_gain is not None else self.GAIN_DEFAULT,
        )

    def _get_gains(self) -> tuple[float, float]:
        x_gain, y_gain = self._get_saved_gains()
        if not self._is_gain_enabled():
            return (self.GAIN_DEFAULT, self.GAIN_DEFAULT)
        return (x_gain, y_gain)

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

    def _start_anchor_set_mode(self, axis: str) -> None:
        if axis not in ("up", "down", "left", "right"):
            return
        self._set_calibration_mode(False)
        self._anchor_set_mode = axis
        self._emit_overlay_event("start")

    def _handle_anchor_click(self, x: int, y: int) -> None:
        if self._anchor_set_mode is None:
            return
        center_x, center_y = self._get_window_center()
        distance = None
        if self._anchor_set_mode == "up":
            distance = center_y - y
        elif self._anchor_set_mode == "down":
            distance = y - center_y
        elif self._anchor_set_mode == "left":
            distance = center_x - x
        elif self._anchor_set_mode == "right":
            distance = x - center_x
        if distance is None:
            return
        distance_value = self._sanitize_anchor_distance(int(round(distance)))
        if distance_value is None:
            return
        stored = self._get_anchor_distances()
        if stored is None:
            up = self._sanitize_anchor_distance(
                self.get_config_value(self.ANCHOR_UP_INPUT_CONFIG_KEY)
            )
            down = self._sanitize_anchor_distance(
                self.get_config_value(self.ANCHOR_DOWN_INPUT_CONFIG_KEY)
            )
            left = self._sanitize_anchor_distance(
                self.get_config_value(self.ANCHOR_LEFT_INPUT_CONFIG_KEY)
            )
            right = self._sanitize_anchor_distance(
                self.get_config_value(self.ANCHOR_RIGHT_INPUT_CONFIG_KEY)
            )
        else:
            up, down, left, right = stored
        if self._anchor_set_mode == "up":
            up = distance_value
        elif self._anchor_set_mode == "down":
            down = distance_value
        elif self._anchor_set_mode == "left":
            left = distance_value
        elif self._anchor_set_mode == "right":
            right = distance_value
        if None not in (up, down, left, right):
            self._store_anchor_distances(up, down, left, right)
        else:
            if up is not None:
                self.set_config_value(self.ANCHOR_UP_CONFIG_KEY, up)
            if down is not None:
                self.set_config_value(self.ANCHOR_DOWN_CONFIG_KEY, down)
            if left is not None:
                self.set_config_value(self.ANCHOR_LEFT_CONFIG_KEY, left)
            if right is not None:
                self.set_config_value(self.ANCHOR_RIGHT_CONFIG_KEY, right)
        self._sync_anchor_inputs()
        self._anchor_set_mode = None
        self._emit_overlay_event("stop")
        self._emit_overlay_event("refresh")

    def _get_anchor_normalized_vector(
        self, center_x: float, center_y: float, cursor_x: float, cursor_y: float
    ) -> tuple[float, float] | None:
        distances = self._get_anchor_distances()
        if distances is None:
            return None
        up, down, left, right = distances
        dx = cursor_x - center_x
        dy = cursor_y - center_y
        rx = right if dx >= 0 else left
        ry = down if dy >= 0 else up
        if rx <= 0 or ry <= 0:
            return None
        nx = dx / rx
        ny = dy / ry
        length = math.hypot(nx, ny)
        if length == 0:
            return (0.0, 0.0)
        if length > 1.0:
            nx /= length
            ny /= length
            length = 1.0
        deadzone = self._get_deadzone()
        if length < deadzone:
            return (0.0, 0.0)
        if deadzone > 0:
            scaled_length = (length - deadzone) / (1.0 - deadzone)
            scaled_length = max(0.0, min(scaled_length, 1.0))
        else:
            scaled_length = length
        nx = (nx / length) * scaled_length
        ny = (ny / length) * scaled_length
        return (nx, ny)

    def get_anchor_overlay_data(self) -> dict[str, object] | None:
        distances = self._get_anchor_distances()
        if distances is None:
            return None
        center = self._get_window_center()
        up, down, left, right = distances
        center_x, center_y = center
        anchors = {
            "up": (center_x, center_y - up),
            "down": (center_x, center_y + down),
            "left": (center_x - left, center_y),
            "right": (center_x + right, center_y),
        }
        points: list[tuple[float, float]] = []
        segments = 256
        # Smooth asymmetric superellipse boundary.
        # p controls roundness (2.0 is ellipse, higher = squarer). k controls
        # the softness of left/right and up/down blending.
        p = min(4.0, max(2.0, 2.2))
        k = min(10.0, max(1.0, 4.0))

        def lerp(a: float, b: float, t: float) -> float:
            return a + (b - a) * t

        for i in range(segments + 1):
            rad = 2 * math.pi * i / segments
            dx = math.cos(rad)
            dy = math.sin(rad)
            sx = 0.5 * (1.0 + math.tanh(k * dx))
            sy = 0.5 * (1.0 + math.tanh(k * dy))
            rx = lerp(left, right, sx)
            ry = lerp(up, down, sy)
            denom = (abs(dx) / rx) ** p + (abs(dy) / ry) ** p
            r = 1.0 / (denom ** (1.0 / p))
            x = center_x + r * dx
            y = center_y + r * dy
            points.append((x, y))
        return {
            "center": center,
            "anchors": anchors,
            "contour": points,
        }

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

    def set_mapping_mode(self, mapping_mode: bool) -> None:
        super().set_mapping_mode(mapping_mode)
        self._set_anchor_controls_visible(not mapping_mode)
        if mapping_mode:
            self.cancel_anchor_set()
