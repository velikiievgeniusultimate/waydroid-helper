#!/usr/bin/env python3
"""
技能释放按钮组件
一个圆形的半透明灰色按钮，支持技能释放操作
"""

import asyncio
import json
import math
import time
from dataclasses import dataclass
from enum import Enum
from gettext import pgettext
from typing import TYPE_CHECKING

from waydroid_helper.controller.widgets.components.cancel_casting import \
    CancelCasting
from waydroid_helper.util.log import logger

if TYPE_CHECKING:
    from cairo import Context, Surface
    from gi.repository import Gtk
    from waydroid_helper.controller.widgets.base.base_widget import EditableRegion

from cairo import FONT_SLANT_NORMAL, FONT_WEIGHT_BOLD

from gi.repository import Gdk, Gtk

from waydroid_helper.controller.android.input import (AMotionEventAction,
                                                      AMotionEventButtons)
from waydroid_helper.controller.core import (Event, EventType, KeyCombination,
                                             EventBus, PointerIdManager, KeyRegistry)
from waydroid_helper.controller.core.control_msg import InjectTouchEventMsg, ScreenInfo
from waydroid_helper.controller.core.handler.event_handlers import InputEvent
from waydroid_helper.controller.widgets.base.base_widget import BaseWidget
from waydroid_helper.controller.widgets.config import (
    create_action_config,
    create_dropdown_config,
    create_slider_config,
    create_switch_config,
    create_text_config,
)
from waydroid_helper.controller.widgets.decorators import (Editable, Resizable,
                                                           ResizableDecorator)

class SkillState(Enum):
    """技能释放状态枚举"""

    INACTIVE = "inactive"  # 未激活
    MOVING = "moving"  # 移动中（向目标位置移动）
    ACTIVE = "active"  # 激活状态（可以瞬移）
    LOCKED = "locked"  # 锁定状态（手动释放模式）
    CANCELING = "canceling"  # 取消施法移动状态


class CastTiming(Enum):
    """施法时机枚举"""

    ON_RELEASE = "on_release"  # 松开释放
    IMMEDIATE = "immediate"  # 立即释放
    MANUAL = "manual"  # 手动释放


@dataclass
class SkillEvent:
    """技能事件数据类"""

    type: str  # "key_press", "key_release", "mouse_motion", "cancel_casting"
    data: dict
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


@dataclass
class IdealCalibrationSample:
    target_angle: float
    target_radius: float
    cursor_angle: float
    cursor_radius: float


@Editable
@Resizable(resize_strategy=ResizableDecorator.RESIZE_CENTER)
class SkillCasting(BaseWidget):
    """技能释放按钮组件 - 圆形半透明按钮"""

    # 组件元数据
    SETTINGS_PANEL_AUTO_HIDE = False
    SETTINGS_PANEL_MIN_WIDTH = 420
    SETTINGS_PANEL_MIN_HEIGHT = 480
    SETTINGS_PANEL_MAX_HEIGHT = 700
    WIDGET_NAME = pgettext("Controller Widgets", "Skill Casting")
    WIDGET_DESCRIPTION = pgettext(
        "Controller Widgets",
        "Commonly used when using the characters' skills, click and cooperate with the mouse to release skills.",
    )
    CENTER_X_CONFIG_KEY = "skill_calibrated_center_x"
    CENTER_Y_CONFIG_KEY = "skill_calibrated_center_y"
    CENTER_X_INPUT_CONFIG_KEY = "skill_center_x_input"
    CENTER_Y_INPUT_CONFIG_KEY = "skill_center_y_input"
    CALIBRATE_CENTER_CONFIG_KEY = "skill_calibrate_center"
    RESET_CENTER_CONFIG_KEY = "skill_reset_center"
    APPLY_CENTER_CONFIG_KEY = "skill_apply_center"
    GAIN_ENABLED_CONFIG_KEY = "skill_gain_enabled"
    X_GAIN_CONFIG_KEY = "skill_x_gain"
    Y_GAIN_CONFIG_KEY = "skill_y_gain"
    X_GAIN_INPUT_CONFIG_KEY = "skill_x_gain_input"
    Y_GAIN_INPUT_CONFIG_KEY = "skill_y_gain_input"
    APPLY_GAIN_CONFIG_KEY = "skill_apply_gains"
    TUNE_ANGLE_CONFIG_KEY = "skill_tune_angle"
    ANCHOR_UP_CONFIG_KEY = "skill_anchor_up_dist_px"
    ANCHOR_DOWN_CONFIG_KEY = "skill_anchor_down_dist_px"
    ANCHOR_LEFT_CONFIG_KEY = "skill_anchor_left_dist_px"
    ANCHOR_RIGHT_CONFIG_KEY = "skill_anchor_right_dist_px"
    ANCHOR_UP_INPUT_CONFIG_KEY = "skill_anchor_up_input"
    ANCHOR_DOWN_INPUT_CONFIG_KEY = "skill_anchor_down_input"
    ANCHOR_LEFT_INPUT_CONFIG_KEY = "skill_anchor_left_input"
    ANCHOR_RIGHT_INPUT_CONFIG_KEY = "skill_anchor_right_input"
    APPLY_ANCHORS_CONFIG_KEY = "skill_apply_anchors"
    RESET_ANCHORS_CONFIG_KEY = "skill_reset_anchors"
    SET_ANCHOR_UP_CONFIG_KEY = "skill_set_anchor_up"
    SET_ANCHOR_DOWN_CONFIG_KEY = "skill_set_anchor_down"
    SET_ANCHOR_LEFT_CONFIG_KEY = "skill_set_anchor_left"
    SET_ANCHOR_RIGHT_CONFIG_KEY = "skill_set_anchor_right"
    CANCEL_ANCHOR_SET_CONFIG_KEY = "skill_cancel_anchor_set"
    ANCHOR_DEADZONE_CONFIG_KEY = "skill_anchor_deadzone"
    DIAG_UR_DX_CONFIG_KEY = "skill_diag_ur_dx"
    DIAG_UR_DY_CONFIG_KEY = "skill_diag_ur_dy"
    DIAG_DR_DX_CONFIG_KEY = "skill_diag_dr_dx"
    DIAG_DR_DY_CONFIG_KEY = "skill_diag_dr_dy"
    DIAG_DL_DX_CONFIG_KEY = "skill_diag_dl_dx"
    DIAG_DL_DY_CONFIG_KEY = "skill_diag_dl_dy"
    DIAG_UL_DX_CONFIG_KEY = "skill_diag_ul_dx"
    DIAG_UL_DY_CONFIG_KEY = "skill_diag_ul_dy"
    DIAG_UR_DX_INPUT_CONFIG_KEY = "skill_diag_ur_dx_input"
    DIAG_UR_DY_INPUT_CONFIG_KEY = "skill_diag_ur_dy_input"
    DIAG_DR_DX_INPUT_CONFIG_KEY = "skill_diag_dr_dx_input"
    DIAG_DR_DY_INPUT_CONFIG_KEY = "skill_diag_dr_dy_input"
    DIAG_DL_DX_INPUT_CONFIG_KEY = "skill_diag_dl_dx_input"
    DIAG_DL_DY_INPUT_CONFIG_KEY = "skill_diag_dl_dy_input"
    DIAG_UL_DX_INPUT_CONFIG_KEY = "skill_diag_ul_dx_input"
    DIAG_UL_DY_INPUT_CONFIG_KEY = "skill_diag_ul_dy_input"
    APPLY_DIAGONALS_CONFIG_KEY = "skill_apply_diagonals"
    RESET_DIAGONALS_CONFIG_KEY = "skill_reset_diagonals"
    SHOW_DEBUG_BOUNDARY_CONFIG_KEY = "skill_show_debug_boundary"
    IDEAL_CALIBRATION_SKILL_CONFIG_KEY = "skill_ideal_calibration_skill"
    IDEAL_CALIBRATION_SAMPLES_CONFIG_KEY = "skill_ideal_calibration_samples"
    IDEAL_CALIBRATION_START_CONFIG_KEY = "skill_ideal_calibration_start"
    IDEAL_CALIBRATION_STOP_CONFIG_KEY = "skill_ideal_calibration_stop"
    IDEAL_CALIBRATION_RESET_CONFIG_KEY = "skill_ideal_calibration_reset"
    IDEAL_CALIBRATION_CONFIRM_YES_CONFIG_KEY = "skill_ideal_calibration_confirm_yes"
    IDEAL_CALIBRATION_CONFIRM_NO_CONFIG_KEY = "skill_ideal_calibration_confirm_no"
    IDEAL_CALIBRATION_CONFIRM_REDO_CONFIG_KEY = "skill_ideal_calibration_confirm_redo"
    IDEAL_CALIBRATION_SAVE_PARTIAL_CONFIG_KEY = "skill_ideal_calibration_save_partial"
    IDEAL_CALIBRATION_DATA_CONFIG_KEY = "skill_ideal_calibration_data"
    GAIN_DEFAULT = 1.0
    GAIN_MIN = 0.5
    GAIN_MAX = 2.0
    DEFAULT_CAST_RADIUS = 200.0
    IDEAL_CALIBRATION_SCALE_MIN = 0.5
    IDEAL_CALIBRATION_SCALE_MAX = 2.0
    IDEAL_CALIBRATION_TARGET_RATIO = 0.95
    ANCHOR_MAX_MULTIPLIER = 4
    DEADZONE_DEFAULT = 0.1
    DEADZONE_MAX = 0.95
    DIAGONAL_DEFAULT_SCALE = 0.7
    DIAGONAL_HANDLE_RADIUS = 12
    DIAGONAL_QUADRANTS = {
        "ur": (1, -1),
        "dr": (1, 1),
        "dl": (-1, 1),
        "ul": (-1, -1),
    }

    # 映射模式固定尺寸
    MAPPING_MODE_HEIGHT = 30

    cancel_button_widget = {"widget": None}
    cancel_button_config = create_switch_config(
        key="enable_cancel_button",
        label=pgettext("Controller Widgets", "Enable Cancel Button"),
        value=False,
        description=pgettext(
            "Controller Widgets",
            "Enable a cancel casting button that can interrupt ongoing skill casting",
        ),
    )

    @property
    def MAPPING_MODE_WIDTH(self):
        """根据文字长度计算映射模式宽度，与draw_mapping_mode_background的逻辑保持一致"""
        if self.text:
            # 估算文字宽度：对于12px的Arial字体
            # 英文数字字符平均约7-8px，为保险起见用8px
            # 中文字符约12px，这里简化统一按8px估算（略保守）
            estimated_text_width = len(self.text) * 8

            # 加上左右内边距 (padding_x = 8 * 2 = 16)
            padding_x = 8
            rect_width = estimated_text_width + 2 * padding_x

            # 确保最小宽度 24，与draw_mapping_mode_background一致
            rect_width = max(rect_width, 24)

            # 为了保险起见，再加4px缓冲，确保不会被截断
            return rect_width + 4
        else:
            # 无文字时的默认宽度，与draw_mapping_mode_background的default保持一致
            return 24 + 4  # 24是最小宽度，+4是缓冲

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
        # 初始化基类，传入默认按键
        super().__init__(
            x,
            y,
            min(width, height),
            min(width, height),
            pgettext("Controller Widgets", "Skill Casting"),
            text,
            default_keys,
            min_width=25,
            min_height=25,
            event_bus=event_bus,
            pointer_id_manager=pointer_id_manager,
            key_registry=key_registry,
        )

        # 异步状态管理
        self._skill_state: SkillState = SkillState.INACTIVE
        self._current_position: tuple[float, float] = (x + width / 2, y + height / 2)
        self._target_position: tuple[float, float] = (x + width / 2, y + height / 2)
        self.is_reentrant: bool = True

        # 异步任务管理
        self._current_task: asyncio.Task | None = None
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._event_processor_task: asyncio.Task | None = None

        # 技能释放控制标志
        self._target_locked: bool = False  # 是否锁定目标位置（所有模式共用）
        self._key_released_during_moving: bool = (
            False  # 移动过程中按键是否已释放（ON_RELEASE模式专用）
        )

        # 取消施法相关变量
        self._cancel_target_position: tuple[float, float] | None = (
            None  # 取消施法的目标位置
        )

        # 平滑移动系统参数
        self._move_interval: float = 0.02  # 20ms，转换为秒
        self._move_steps_total: int = 6

        # 圆形映射参数（像素值）
        # self.circle_radius: int = 200  # 圆半径，单位像素
        self._mouse_x: float = 0
        self._mouse_y: float = 0

        self._calibration_mode: bool = False
        self._tuning_mode: bool = False
        self._tuning_x_gain: float | None = None
        self._tuning_y_gain: float | None = None
        self._anchor_set_mode: str | None = None
        self._diag_warning_label: Gtk.Label | None = None
        self._ideal_calibration_active: bool = False
        self._ideal_calibration_skill: str = "Q"
        self._ideal_calibration_samples_total: int = 16
        self._ideal_calibration_targets: list[float] = []
        self._ideal_calibration_index: int = 0
        self._ideal_calibration_samples: list[IdealCalibrationSample] = []
        self._ideal_calibration_pending_sample: IdealCalibrationSample | None = None
        self._ideal_calibration_awaiting_confirmation: bool = False
        self._ideal_calibration_status_label: Gtk.Label | None = None
        self._ideal_calibration_progress_label: Gtk.Label | None = None
        self._ideal_calibration_last_error: str = ""

        # 施法时机配置
        # self.cast_timing: str = CastTiming.ON_RELEASE.value  # 默认为松开释放

        # 设置配置项
        self.setup_config()

        # 启动异步事件处理器
        self._start_event_processor()

        # 订阅事件总线
        self.event_bus.subscribe(EventType.MOUSE_MOTION, self._on_mouse_motion, subscriber=self)
        self.event_bus.subscribe(EventType.CANCEL_CASTING, self._on_cancel_casting, subscriber=self)
        self.event_bus.subscribe(
            event_type=EventType.MASK_CLICKED,
            handler=self._on_mask_clicked,
            subscriber=self,
        )

        # # 测试：监听取消按钮销毁事件
        # event_bus.subscribe(
        #     EventType.CANCEL_BUTTON_DESTROYED,
        #     self._on_custom_event,
        #     filter=lambda e: e.data.get("widget_class") == "CancelCasting"
        #     and self._cancel_button_widget["widget"] is not None,
        #     subscriber=self,
        # )
        self.screen_info = ScreenInfo()
        self._emit_overlay_event("register")

    def _start_event_processor(self):
        """启动异步事件处理器"""
        if self._event_processor_task is None or self._event_processor_task.done():
            self._event_processor_task = asyncio.create_task(self._process_events())

    async def _process_events(self):
        """异步事件处理器主循环"""
        try:
            while True:
                # 等待事件
                event = await self._event_queue.get()
                await self._handle_event(event)
                self._event_queue.task_done()
        except:
            pass

    async def _handle_event(self, event: SkillEvent):
        """处理单个事件"""
        try:
            if event.type == "key_press":
                await self._handle_key_press(event)
            elif event.type == "key_release":
                await self._handle_key_release(event)
            elif event.type == "mouse_motion":
                await self._handle_mouse_motion_async(event)
            elif event.type == "cancel_casting":
                await self._handle_cancel_casting_async(event)
        except:
            pass

    def _on_mouse_motion(self, event):
        """鼠标移动事件回调 - 将事件放入队列"""
        # 窗口发送的 MOUSE_MOTION 事件包含 InputEvent 对象
        if hasattr(event, "data") and hasattr(event.data, "position"):
            # 这是 InputEvent 对象
            position = event.data.position
        elif (
            hasattr(event, "data")
            and isinstance(event.data, dict)
            and event.data.get("position")
        ):
            # 这是字典格式的事件数据
            position = event.data["position"]
        else:
            return

        skill_event = SkillEvent(
            type="mouse_motion", data={"position": position, "timestamp": time.time()}
        )

        # 非阻塞方式放入队列
        try:
            self._event_queue.put_nowait(skill_event)
        except:
            pass

    def _on_cancel_casting(self, event):
        """取消施法事件回调 - 将事件放入队列"""
        skill_event = SkillEvent(
            type="cancel_casting", data=event.data if hasattr(event, "data") else event
        )

        # 非阻塞方式放入队列
        try:
            self._event_queue.put_nowait(skill_event)
        except:
            pass

    async def _handle_key_press(self, event: SkillEvent):
        """异步处理按键按下事件"""
        if self._skill_state == SkillState.INACTIVE:
            # 首次激活
            await self._activate_skill()
        elif self._skill_state == SkillState.LOCKED:
            # 手动释放模式的第二次按键
            await self._release_skill()

    async def _handle_key_release(self, event: SkillEvent):
        """异步处理按键释放事件"""
        if self._skill_state == SkillState.INACTIVE:
            return

        # 取消施法状态下不响应按键弹起
        if self._skill_state == SkillState.CANCELING:
            return

        # 根据施法时机决定处理方式
        if self.get_config_value("cast_timing") == CastTiming.ON_RELEASE.value:
            if self._skill_state == SkillState.MOVING:
                # 正在移动中，设置标志表示按键已释放
                self._key_released_during_moving = True
            elif self._skill_state == SkillState.ACTIVE:
                # 已到达目标，立即发送UP事件并重置
                await self._release_skill()

    async def _handle_mouse_motion_async(self, event: SkillEvent):
        """异步处理鼠标移动事件"""
        if not event.data.get("position"):
            return

        self._mouse_x, self._mouse_y = event.data["position"]
        mapped_target = self._map_circle_to_circle(self._mouse_x, self._mouse_y)

        if self._skill_state == SkillState.INACTIVE:
            # 未激活状态下不处理鼠标移动
            return
        elif self._skill_state == SkillState.MOVING:
            # 移动中忽略鼠标移动（目标已锁定）
            return
        elif self._skill_state == SkillState.ACTIVE:
            # 激活状态：更新目标位置并瞬移
            await self._instant_move_to_target(mapped_target)
        elif self._skill_state == SkillState.LOCKED:
            # 锁定状态：鼠标移动，瞬移到新目标位置
            await self._instant_move_to_target(mapped_target)

    async def _handle_cancel_casting_async(self, event: SkillEvent):
        """异步处理取消施法事件"""
        if self._skill_state == SkillState.INACTIVE:
            return

        # 从事件中获取取消施法的目标位置
        event_data = event.data
        if (
            not isinstance(event_data, dict)
            or "x" not in event_data
            or "y" not in event_data
        ):
            return

        cancel_x = event_data["x"]
        cancel_y = event_data["y"]
        self._cancel_target_position = (cancel_x, cancel_y)

        if self._skill_state == SkillState.MOVING:
            # 当前正在移动中，等待移动完成后再执行取消流程
            pass
            # 不取消当前任务，让它自然完成，然后在 _skill_casting_flow 中处理取消
        else:
            # 当前不在移动状态，立即开始取消施法移动
            # 取消当前任务
            if self._current_task and not self._current_task.done():
                self._current_task.cancel()

            # 开始取消施法移动
            self._current_task = asyncio.create_task(self._cancel_casting_move())

    async def _activate_skill(self):
        """激活技能"""
        # 将鼠标位置映射到虚拟摇杆位置
        mapped_target = self._map_circle_to_circle(self._mouse_x, self._mouse_y)

        # 设置目标位置并锁定
        self._target_position = mapped_target
        self._target_locked = True

        # 分配指针ID并发送DOWN事件
        pointer_id = self.pointer_id_manager.allocate(self)
        if pointer_id is None:
            return

        self._current_position = (self.center_x, self.center_y)
        self._emit_touch_event(AMotionEventAction.DOWN, position=self._current_position)

        # 开始技能流程
        self._current_task = asyncio.create_task(self._skill_casting_flow())

    async def _skill_casting_flow(self):
        """技能释放主流程"""
        try:
            # 开始移动
            self._skill_state = SkillState.MOVING
            await self._smooth_move_to_target(self._target_position)

            # 移动完成后，检查是否有取消请求
            if self._cancel_target_position is not None:
                # 有待处理的取消事件，开始取消施法移动
                await self._cancel_casting_move()
                return

            # 根据施法时机处理
            if self.get_config_value("cast_timing") == CastTiming.IMMEDIATE.value:
                # 立即释放模式：移动完成后立即发送UP事件并重置
                await self._release_skill()
            elif self.get_config_value("cast_timing") == CastTiming.MANUAL.value:
                # 手动释放模式：进入锁定状态，等待第二次按键
                self._skill_state = SkillState.LOCKED
                self._target_locked = False  # 解锁目标位置，允许瞬移
            else:  # ON_RELEASE
                # ON_RELEASE模式：检查是否在移动过程中按键已释放
                if self._key_released_during_moving:
                    # 移动过程中按键已释放，立即发送UP事件并重置
                    await self._release_skill()
                else:
                    # 按键未释放，进入激活状态，等待按键松开
                    self._skill_state = SkillState.ACTIVE
                    self._target_locked = False  # 解锁目标位置，允许瞬移

        except asyncio.CancelledError:
            # 被取消时的处理
            await self._release_skill()
        except Exception as e:
            await self._release_skill()

    async def _cancel_casting_move(self):
        """取消施法的平滑移动"""
        if self._cancel_target_position is None:
            return

        try:
            # 设置目标位置并开始移动
            self._target_position = self._cancel_target_position
            self._skill_state = SkillState.CANCELING
            self._target_locked = True  # 锁定目标，不允许中断

            # 开始平滑移动
            await self._smooth_move_to_target(self._cancel_target_position)

            # 移动完成，发送UP事件并重置
            await self._release_skill()

        except asyncio.CancelledError:
            await self._release_skill()
        except Exception:
            await self._release_skill()

    async def _smooth_move_to_target(self, target: tuple[float, float]):
        """异步平滑移动到目标位置"""
        start_pos = self._current_position
        steps = self._move_steps_total

        for step in range(1, steps + 1):
            # 计算当前位置
            progress = step / steps
            current_x = start_pos[0] + (target[0] - start_pos[0]) * progress
            current_y = start_pos[1] + (target[1] - start_pos[1]) * progress

            self._current_position = (current_x, current_y)
            self._emit_touch_event(AMotionEventAction.MOVE)

            # 等待间隔
            await asyncio.sleep(self._move_interval)

            # 检查是否被取消
            if self._skill_state == SkillState.INACTIVE:
                return

        # 移动完成
        self._current_position = target

    async def _instant_move_to_target(self, target: tuple[float, float]):
        """瞬间移动到目标位置"""
        self._current_position = target
        self._target_position = target
        self._emit_touch_event(AMotionEventAction.MOVE)

    async def _release_skill(self):
        """释放技能"""
        self._emit_touch_event(AMotionEventAction.UP)
        self._capture_ideal_calibration_sample()
        await self._reset_skill()

    async def _reset_skill(self):
        """异步重置技能状态"""
        self._skill_state = SkillState.INACTIVE
        self._current_position = (self.center_x, self.center_y)
        self._target_locked = False
        self._key_released_during_moving = False

        # 清理取消施法相关状态
        self._cancel_target_position = None

        # 取消当前任务
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            self._current_task = None

        # 释放指针ID
        self.pointer_id_manager.release(self)

    def setup_config(self) -> None:
        """设置配置项"""
        cast_timing_config = create_dropdown_config(
            key="cast_timing",
            label=pgettext("Controller Widgets", "Cast Timing"),
            options=[
                CastTiming.ON_RELEASE.value,
                CastTiming.IMMEDIATE.value,
                CastTiming.MANUAL.value,
            ],
            option_labels={
                CastTiming.ON_RELEASE.value: pgettext(
                    "Controller Widgets", "On Release"
                ),
                CastTiming.IMMEDIATE.value: pgettext("Controller Widgets", "Immediate"),
                CastTiming.MANUAL.value: pgettext("Controller Widgets", "Manual"),
            },
            value=CastTiming.ON_RELEASE.value,
            description=pgettext(
                "Controller Widgets",
                "Determines when the skill casting ends: On Release (default), Immediate (auto-release after moving), or Manual (sticky mode)",
            ),
        )
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
        diag_ur_dx_config = create_text_config(
            key=self.DIAG_UR_DX_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Diagonal UR X"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored diagonal up-right X offset."
            ),
            visible=False,
        )
        diag_ur_dy_config = create_text_config(
            key=self.DIAG_UR_DY_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Diagonal UR Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored diagonal up-right Y offset."
            ),
            visible=False,
        )
        diag_dr_dx_config = create_text_config(
            key=self.DIAG_DR_DX_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Diagonal DR X"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored diagonal down-right X offset."
            ),
            visible=False,
        )
        diag_dr_dy_config = create_text_config(
            key=self.DIAG_DR_DY_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Diagonal DR Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored diagonal down-right Y offset."
            ),
            visible=False,
        )
        diag_dl_dx_config = create_text_config(
            key=self.DIAG_DL_DX_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Diagonal DL X"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored diagonal down-left X offset."
            ),
            visible=False,
        )
        diag_dl_dy_config = create_text_config(
            key=self.DIAG_DL_DY_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Diagonal DL Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored diagonal down-left Y offset."
            ),
            visible=False,
        )
        diag_ul_dx_config = create_text_config(
            key=self.DIAG_UL_DX_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Diagonal UL X"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored diagonal up-left X offset."
            ),
            visible=False,
        )
        diag_ul_dy_config = create_text_config(
            key=self.DIAG_UL_DY_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Diagonal UL Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored diagonal up-left Y offset."
            ),
            visible=False,
        )
        diag_ur_dx_input_config = create_text_config(
            key=self.DIAG_UR_DX_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "UR dx (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Up-right diagonal X offset from center."
            ),
        )
        diag_ur_dy_input_config = create_text_config(
            key=self.DIAG_UR_DY_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "UR dy (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Up-right diagonal Y offset from center."
            ),
        )
        diag_dr_dx_input_config = create_text_config(
            key=self.DIAG_DR_DX_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "DR dx (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Down-right diagonal X offset from center."
            ),
        )
        diag_dr_dy_input_config = create_text_config(
            key=self.DIAG_DR_DY_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "DR dy (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Down-right diagonal Y offset from center."
            ),
        )
        diag_dl_dx_input_config = create_text_config(
            key=self.DIAG_DL_DX_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "DL dx (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Down-left diagonal X offset from center."
            ),
        )
        diag_dl_dy_input_config = create_text_config(
            key=self.DIAG_DL_DY_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "DL dy (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Down-left diagonal Y offset from center."
            ),
        )
        diag_ul_dx_input_config = create_text_config(
            key=self.DIAG_UL_DX_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "UL dx (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Up-left diagonal X offset from center."
            ),
        )
        diag_ul_dy_input_config = create_text_config(
            key=self.DIAG_UL_DY_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "UL dy (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Up-left diagonal Y offset from center."
            ),
        )
        apply_diagonals_config = create_action_config(
            key=self.APPLY_DIAGONALS_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Apply Diagonals"),
            button_label=pgettext("Controller Widgets", "Apply"),
            description=pgettext(
                "Controller Widgets",
                "Validate and apply diagonal offsets for the boundary.",
            ),
        )
        reset_diagonals_config = create_action_config(
            key=self.RESET_DIAGONALS_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Reset Diagonals"),
            button_label=pgettext("Controller Widgets", "Reset"),
            description=pgettext(
                "Controller Widgets",
                "Clear diagonal offsets and regenerate defaults.",
            ),
        )
        show_debug_boundary_config = create_switch_config(
            key=self.SHOW_DEBUG_BOUNDARY_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Show Debug Boundary (Edit Mode)"),
            value=True,
            description=pgettext(
                "Controller Widgets",
                "Show the boundary/center debug overlay while editing this widget.",
            ),
        )
        ideal_calibration_skill_config = create_dropdown_config(
            key=self.IDEAL_CALIBRATION_SKILL_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Skill"),
            options=["Q"],
            option_labels={"Q": pgettext("Controller Widgets", "Q")},
            value="Q",
            description=pgettext(
                "Controller Widgets",
                "Select which skill key to calibrate (more options may be added later).",
            ),
        )
        ideal_calibration_samples_config = create_dropdown_config(
            key=self.IDEAL_CALIBRATION_SAMPLES_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Samples"),
            options=["16", "32"],
            option_labels={
                "16": pgettext("Controller Widgets", "16 samples"),
                "32": pgettext("Controller Widgets", "32 samples"),
            },
            value="16",
            description=pgettext(
                "Controller Widgets",
                "Number of target points to capture during calibration.",
            ),
        )
        ideal_calibration_start_config = create_action_config(
            key=self.IDEAL_CALIBRATION_START_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Ideal Calibration"),
            button_label=pgettext("Controller Widgets", "Start"),
            description=pgettext(
                "Controller Widgets",
                "Start the ideal calibration wizard for the selected skill.",
            ),
        )
        ideal_calibration_stop_config = create_action_config(
            key=self.IDEAL_CALIBRATION_STOP_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Stop Calibration"),
            button_label=pgettext("Controller Widgets", "Stop"),
            description=pgettext(
                "Controller Widgets",
                "Stop the current calibration session without saving.",
            ),
        )
        ideal_calibration_save_partial_config = create_action_config(
            key=self.IDEAL_CALIBRATION_SAVE_PARTIAL_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Save Partial"),
            button_label=pgettext("Controller Widgets", "Save Partial"),
            description=pgettext(
                "Controller Widgets",
                "Save the samples collected so far and exit the wizard.",
            ),
        )
        ideal_calibration_reset_config = create_action_config(
            key=self.IDEAL_CALIBRATION_RESET_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Reset Calibration"),
            button_label=pgettext("Controller Widgets", "Reset"),
            description=pgettext(
                "Controller Widgets",
                "Clear the stored ideal calibration data for this skill.",
            ),
        )
        ideal_calibration_confirm_yes_config = create_action_config(
            key=self.IDEAL_CALIBRATION_CONFIRM_YES_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Did it hit?"),
            button_label=pgettext("Controller Widgets", "Yes"),
            description=pgettext(
                "Controller Widgets",
                "Confirm that the cast landed on the target.",
            ),
        )
        ideal_calibration_confirm_no_config = create_action_config(
            key=self.IDEAL_CALIBRATION_CONFIRM_NO_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Did it hit?"),
            button_label=pgettext("Controller Widgets", "No"),
            description=pgettext(
                "Controller Widgets",
                "Discard the sample and repeat the same target.",
            ),
        )
        ideal_calibration_confirm_redo_config = create_action_config(
            key=self.IDEAL_CALIBRATION_CONFIRM_REDO_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Did it hit?"),
            button_label=pgettext("Controller Widgets", "Redo"),
            description=pgettext(
                "Controller Widgets",
                "Redo the current target without saving the sample.",
            ),
        )
        ideal_calibration_data_config = create_text_config(
            key=self.IDEAL_CALIBRATION_DATA_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Ideal Calibration Data"),
            value="",
            description=pgettext(
                "Controller Widgets",
                "Serialized ideal calibration data (stored per skill).",
            ),
            visible=False,
        )

        self.add_config_item(cast_timing_config)
        self.add_config_item(self.cancel_button_config)
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
        self.add_config_item(diag_ur_dx_config)
        self.add_config_item(diag_ur_dy_config)
        self.add_config_item(diag_dr_dx_config)
        self.add_config_item(diag_dr_dy_config)
        self.add_config_item(diag_dl_dx_config)
        self.add_config_item(diag_dl_dy_config)
        self.add_config_item(diag_ul_dx_config)
        self.add_config_item(diag_ul_dy_config)
        self.add_config_item(diag_ur_dx_input_config)
        self.add_config_item(diag_ur_dy_input_config)
        self.add_config_item(diag_dr_dx_input_config)
        self.add_config_item(diag_dr_dy_input_config)
        self.add_config_item(diag_dl_dx_input_config)
        self.add_config_item(diag_dl_dy_input_config)
        self.add_config_item(diag_ul_dx_input_config)
        self.add_config_item(diag_ul_dy_input_config)
        self.add_config_item(apply_diagonals_config)
        self.add_config_item(reset_diagonals_config)
        self.add_config_item(show_debug_boundary_config)
        self.add_config_item(ideal_calibration_skill_config)
        self.add_config_item(ideal_calibration_samples_config)
        self.add_config_item(ideal_calibration_start_config)
        self.add_config_item(ideal_calibration_stop_config)
        self.add_config_item(ideal_calibration_save_partial_config)
        self.add_config_item(ideal_calibration_reset_config)
        self.add_config_item(ideal_calibration_confirm_yes_config)
        self.add_config_item(ideal_calibration_confirm_no_config)
        self.add_config_item(ideal_calibration_confirm_redo_config)
        self.add_config_item(ideal_calibration_data_config)

        self.add_config_change_callback("cast_timing", self._on_cast_timing_changed)
        self.add_config_change_callback(
            "enable_cancel_button", self._on_cancel_button_config_changed
        )
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
        self.add_config_change_callback(
            self.APPLY_DIAGONALS_CONFIG_KEY, self._on_apply_diagonals_clicked
        )
        self.add_config_change_callback(
            self.RESET_DIAGONALS_CONFIG_KEY, self._on_reset_diagonals_clicked
        )
        self.add_config_change_callback(
            self.SHOW_DEBUG_BOUNDARY_CONFIG_KEY, self._on_debug_boundary_changed
        )
        self.add_config_change_callback(
            self.IDEAL_CALIBRATION_SKILL_CONFIG_KEY,
            self._on_ideal_calibration_skill_changed,
        )
        self.add_config_change_callback(
            self.IDEAL_CALIBRATION_SAMPLES_CONFIG_KEY,
            self._on_ideal_calibration_samples_changed,
        )
        self.add_config_change_callback(
            self.IDEAL_CALIBRATION_START_CONFIG_KEY,
            self._on_ideal_calibration_start_clicked,
        )
        self.add_config_change_callback(
            self.IDEAL_CALIBRATION_STOP_CONFIG_KEY,
            self._on_ideal_calibration_stop_clicked,
        )
        self.add_config_change_callback(
            self.IDEAL_CALIBRATION_SAVE_PARTIAL_CONFIG_KEY,
            self._on_ideal_calibration_save_partial_clicked,
        )
        self.add_config_change_callback(
            self.IDEAL_CALIBRATION_RESET_CONFIG_KEY,
            self._on_ideal_calibration_reset_clicked,
        )
        self.add_config_change_callback(
            self.IDEAL_CALIBRATION_CONFIRM_YES_CONFIG_KEY,
            self._on_ideal_calibration_confirm_yes_clicked,
        )
        self.add_config_change_callback(
            self.IDEAL_CALIBRATION_CONFIRM_NO_CONFIG_KEY,
            self._on_ideal_calibration_confirm_no_clicked,
        )
        self.add_config_change_callback(
            self.IDEAL_CALIBRATION_CONFIRM_REDO_CONFIG_KEY,
            self._on_ideal_calibration_confirm_redo_clicked,
        )

        self._sync_center_inputs()
        self._sync_gain_inputs()
        self._sync_anchor_inputs()
        self._ensure_diagonal_defaults()
        self._sync_diagonal_inputs()
        self._sync_ideal_calibration_settings()
        self._set_gain_controls_visible(self._is_gain_enabled())
        self._set_anchor_controls_visible(not self.mapping_mode)
        self._set_diagonal_controls_visible(
            self._are_anchor_distances_valid() and not self.mapping_mode
        )
        self.get_config_manager().connect(
            "confirmed",
            lambda *_args: (
                self._sync_center_inputs(),
                self._sync_gain_inputs(),
                self._sync_anchor_inputs(),
                self._sync_diagonal_inputs(),
                self._sync_ideal_calibration_settings(),
                self._emit_overlay_event("refresh"),
            ),
        )

    def _on_cast_timing_changed(self, key: str, value: str, restoring:bool) -> None:
        """处理施法时机配置变更"""
        try:
            # self.cast_timing = str(value)
            pass
        except (ValueError, TypeError):
            pass

    def _on_cancel_button_config_changed(self, key: str, value: bool, restoring:bool) -> None:
        """处理取消施法按钮配置变更"""
        if restoring:
            return
        try:
            if value:
                self._enable_cancel_button()
            else:
                self._disable_cancel_button()
        except (ValueError, TypeError) as e:
            logger.error(f"SkillCasting {id(self)} _on_cancel_button_config_changed error: {e}")

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
                "Configure casting behavior, calibration, and boundary mapping.",
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
                pgettext("Controller Widgets", "Casting Behavior"),
                ["cast_timing", "enable_cancel_button"],
                description=pgettext(
                    "Controller Widgets",
                    "Adjust how the skill is cast and whether a cancel button is shown.",
                ),
                expanded=True,
            )
        )

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

        self._diag_warning_label = Gtk.Label(xalign=0)
        self._diag_warning_label.set_wrap(True)
        self._diag_warning_label.add_css_class("warning")
        self._diag_warning_label.set_visible(False)

        panel.append(
            build_section(
                pgettext("Controller Widgets", "Diagonal Boundary"),
                [
                    self.DIAG_UR_DX_INPUT_CONFIG_KEY,
                    self.DIAG_UR_DY_INPUT_CONFIG_KEY,
                    self.DIAG_DR_DX_INPUT_CONFIG_KEY,
                    self.DIAG_DR_DY_INPUT_CONFIG_KEY,
                    self.DIAG_DL_DX_INPUT_CONFIG_KEY,
                    self.DIAG_DL_DY_INPUT_CONFIG_KEY,
                    self.DIAG_UL_DX_INPUT_CONFIG_KEY,
                    self.DIAG_UL_DY_INPUT_CONFIG_KEY,
                    self.APPLY_DIAGONALS_CONFIG_KEY,
                    self.RESET_DIAGONALS_CONFIG_KEY,
                ],
                description=pgettext(
                    "Controller Widgets",
                    "Fine-tune the diagonal boundary points after the axis anchors are set.",
                ),
                expanded=False,
                extra_widgets=[self._diag_warning_label],
            )
        )

        panel.append(
            build_section(
                pgettext("Controller Widgets", "Debug Overlay"),
                [self.SHOW_DEBUG_BOUNDARY_CONFIG_KEY],
                description=pgettext(
                    "Controller Widgets",
                    "Toggle the edit-mode boundary and center markers for this widget.",
                ),
                expanded=False,
            )
        )

        self._ideal_calibration_status_label = Gtk.Label(xalign=0)
        self._ideal_calibration_status_label.set_wrap(True)
        self._ideal_calibration_progress_label = Gtk.Label(xalign=0)
        self._ideal_calibration_progress_label.set_wrap(True)

        panel.append(
            build_section(
                pgettext("Controller Widgets", "Ideal Calibration Wizard"),
                [
                    self.IDEAL_CALIBRATION_SKILL_CONFIG_KEY,
                    self.IDEAL_CALIBRATION_SAMPLES_CONFIG_KEY,
                    self.IDEAL_CALIBRATION_START_CONFIG_KEY,
                    self.IDEAL_CALIBRATION_STOP_CONFIG_KEY,
                    self.IDEAL_CALIBRATION_SAVE_PARTIAL_CONFIG_KEY,
                    self.IDEAL_CALIBRATION_RESET_CONFIG_KEY,
                    self.IDEAL_CALIBRATION_CONFIRM_YES_CONFIG_KEY,
                    self.IDEAL_CALIBRATION_CONFIRM_NO_CONFIG_KEY,
                    self.IDEAL_CALIBRATION_CONFIRM_REDO_CONFIG_KEY,
                ],
                description=pgettext(
                    "Controller Widgets",
                    "Collect cast samples by confirming each target to build a correction map.",
                ),
                expanded=False,
                extra_widgets=[
                    self._ideal_calibration_status_label,
                    self._ideal_calibration_progress_label,
                ],
            )
        )

        tune_widget = config_manager.ui_widgets.get(self.TUNE_ANGLE_CONFIG_KEY)
        if tune_widget is not None:
            tune_widget.set_sensitive(self.mapping_mode)
        self._update_ideal_calibration_labels()
        self._update_ideal_calibration_controls()

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
        self._ensure_diagonal_defaults()
        self._sync_diagonal_inputs()
        self._set_diagonal_controls_visible(True)
        self._emit_overlay_event("refresh")

    def _on_reset_anchors_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._reset_anchor_distances()
        self._sync_anchor_inputs()
        self._sync_diagonal_inputs()
        self._set_diagonal_controls_visible(False)
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

    def _on_apply_diagonals_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring or not self._are_anchor_distances_valid():
            return
        raw_values = {
            "ur": (
                self.get_config_value(self.DIAG_UR_DX_INPUT_CONFIG_KEY),
                self.get_config_value(self.DIAG_UR_DY_INPUT_CONFIG_KEY),
            ),
            "dr": (
                self.get_config_value(self.DIAG_DR_DX_INPUT_CONFIG_KEY),
                self.get_config_value(self.DIAG_DR_DY_INPUT_CONFIG_KEY),
            ),
            "dl": (
                self.get_config_value(self.DIAG_DL_DX_INPUT_CONFIG_KEY),
                self.get_config_value(self.DIAG_DL_DY_INPUT_CONFIG_KEY),
            ),
            "ul": (
                self.get_config_value(self.DIAG_UL_DX_INPUT_CONFIG_KEY),
                self.get_config_value(self.DIAG_UL_DY_INPUT_CONFIG_KEY),
            ),
        }
        sanitized: dict[str, tuple[int, int]] = {}
        for key_name, (raw_dx, raw_dy) in raw_values.items():
            result = self._sanitize_diagonal_pair(key_name, raw_dx, raw_dy)
            if result is None:
                self._set_diagonal_warning(
                    pgettext(
                        "Controller Widgets",
                        "Diagonal values must be integers in the expected quadrant.",
                    )
                )
                return
            sanitized[key_name] = result
        self._store_diagonal_offsets(sanitized)
        self._sync_diagonal_inputs()
        self._set_diagonal_warning("")
        self._emit_overlay_event("refresh")

    def _on_reset_diagonals_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._reset_diagonal_offsets()
        self._sync_diagonal_inputs()
        self._set_diagonal_warning("")
        self._emit_overlay_event("refresh")

    def _on_debug_boundary_changed(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._emit_overlay_event("refresh")

    def _on_ideal_calibration_skill_changed(
        self, key: str, value: str, restoring: bool
    ) -> None:
        if restoring:
            return
        if isinstance(value, str) and value:
            self._ideal_calibration_skill = value
        self._update_ideal_calibration_labels()

    def _on_ideal_calibration_samples_changed(
        self, key: str, value: str, restoring: bool
    ) -> None:
        if restoring:
            return
        try:
            count = int(value)
        except (TypeError, ValueError):
            return
        if count not in (16, 32):
            return
        self._ideal_calibration_samples_total = count
        self._update_ideal_calibration_labels()

    def _on_ideal_calibration_start_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._start_ideal_calibration()

    def _on_ideal_calibration_stop_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._stop_ideal_calibration(save_partial=False)

    def _on_ideal_calibration_save_partial_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._stop_ideal_calibration(save_partial=True)

    def _on_ideal_calibration_reset_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._clear_skill_calibration_map(self._ideal_calibration_skill)
        self._ideal_calibration_last_error = ""
        self._update_ideal_calibration_labels()
        self._emit_overlay_event("refresh")

    def _on_ideal_calibration_confirm_yes_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._confirm_ideal_calibration_sample(record=True)

    def _on_ideal_calibration_confirm_no_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._confirm_ideal_calibration_sample(record=False)

    def _on_ideal_calibration_confirm_redo_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._confirm_ideal_calibration_sample(record=False)

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
        self._set_diagonal_controls_visible(
            self._are_anchor_distances_valid() and not self.mapping_mode
        )

    def _sync_diagonal_inputs(self) -> None:
        diagonals = self._get_diagonal_offsets(allow_default_init=False)
        values = diagonals or {}
        self.set_config_value(
            self.DIAG_UR_DX_INPUT_CONFIG_KEY,
            str(values.get("ur", ("", ""))[0]) if "ur" in values else "",
        )
        self.set_config_value(
            self.DIAG_UR_DY_INPUT_CONFIG_KEY,
            str(values.get("ur", ("", ""))[1]) if "ur" in values else "",
        )
        self.set_config_value(
            self.DIAG_DR_DX_INPUT_CONFIG_KEY,
            str(values.get("dr", ("", ""))[0]) if "dr" in values else "",
        )
        self.set_config_value(
            self.DIAG_DR_DY_INPUT_CONFIG_KEY,
            str(values.get("dr", ("", ""))[1]) if "dr" in values else "",
        )
        self.set_config_value(
            self.DIAG_DL_DX_INPUT_CONFIG_KEY,
            str(values.get("dl", ("", ""))[0]) if "dl" in values else "",
        )
        self.set_config_value(
            self.DIAG_DL_DY_INPUT_CONFIG_KEY,
            str(values.get("dl", ("", ""))[1]) if "dl" in values else "",
        )
        self.set_config_value(
            self.DIAG_UL_DX_INPUT_CONFIG_KEY,
            str(values.get("ul", ("", ""))[0]) if "ul" in values else "",
        )
        self.set_config_value(
            self.DIAG_UL_DY_INPUT_CONFIG_KEY,
            str(values.get("ul", ("", ""))[1]) if "ul" in values else "",
        )

    def _sync_ideal_calibration_settings(self) -> None:
        skill = self.get_config_value(self.IDEAL_CALIBRATION_SKILL_CONFIG_KEY)
        if isinstance(skill, str) and skill:
            self._ideal_calibration_skill = skill
        samples_value = self.get_config_value(self.IDEAL_CALIBRATION_SAMPLES_CONFIG_KEY)
        try:
            samples = int(samples_value)
        except (TypeError, ValueError):
            samples = self._ideal_calibration_samples_total
        if samples in (16, 32):
            self._ideal_calibration_samples_total = samples

    def _are_anchor_distances_valid(self) -> bool:
        return self._get_anchor_distances() is not None

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

    def _set_diagonal_controls_visible(self, visible: bool) -> None:
        manager = self.get_config_manager()
        for key in (
            self.DIAG_UR_DX_INPUT_CONFIG_KEY,
            self.DIAG_UR_DY_INPUT_CONFIG_KEY,
            self.DIAG_DR_DX_INPUT_CONFIG_KEY,
            self.DIAG_DR_DY_INPUT_CONFIG_KEY,
            self.DIAG_DL_DX_INPUT_CONFIG_KEY,
            self.DIAG_DL_DY_INPUT_CONFIG_KEY,
            self.DIAG_UL_DX_INPUT_CONFIG_KEY,
            self.DIAG_UL_DY_INPUT_CONFIG_KEY,
            self.APPLY_DIAGONALS_CONFIG_KEY,
            self.RESET_DIAGONALS_CONFIG_KEY,
        ):
            manager.set_visible(key, visible)
        if self._diag_warning_label is not None:
            self._diag_warning_label.set_visible(visible and bool(self._diag_warning_label.get_label()))

    def _set_calibration_mode(self, active: bool) -> None:
        if active:
            self.cancel_anchor_set()
        self._calibration_mode = active
        self._emit_overlay_event("start" if active else "stop")

    def _set_diagonal_warning(self, message: str) -> None:
        if self._diag_warning_label is None:
            return
        self._diag_warning_label.set_label(message)
        self._diag_warning_label.set_visible(bool(message))

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

    def cancel_ideal_calibration(self) -> None:
        if not self._ideal_calibration_active:
            return
        self._stop_ideal_calibration(save_partial=False)

    def _start_ideal_calibration(self) -> None:
        if self._ideal_calibration_active:
            return
        self._ideal_calibration_skill = str(
            self.get_config_value(self.IDEAL_CALIBRATION_SKILL_CONFIG_KEY) or "Q"
        )
        samples_value = self.get_config_value(self.IDEAL_CALIBRATION_SAMPLES_CONFIG_KEY)
        try:
            samples = int(samples_value)
        except (TypeError, ValueError):
            samples = self._ideal_calibration_samples_total
        if samples not in (16, 32):
            samples = 16
        self._ideal_calibration_samples_total = samples
        self._ideal_calibration_targets = self._build_ideal_calibration_targets(samples)
        self._ideal_calibration_index = 0
        self._ideal_calibration_samples = []
        self._ideal_calibration_pending_sample = None
        self._ideal_calibration_awaiting_confirmation = False
        self._ideal_calibration_last_error = ""
        self._ideal_calibration_active = True
        self._set_calibration_mode(False)
        self.cancel_anchor_set()
        self.cancel_tuning()
        self._update_ideal_calibration_labels()
        self._update_ideal_calibration_controls()
        self._emit_overlay_event("refresh")

    def _stop_ideal_calibration(self, save_partial: bool) -> None:
        if not self._ideal_calibration_active:
            return
        if save_partial and self._ideal_calibration_samples:
            self._finalize_ideal_calibration(self._ideal_calibration_samples)
        self._ideal_calibration_active = False
        self._ideal_calibration_targets = []
        self._ideal_calibration_samples = []
        self._ideal_calibration_index = 0
        self._ideal_calibration_pending_sample = None
        self._ideal_calibration_awaiting_confirmation = False
        self._update_ideal_calibration_labels()
        self._update_ideal_calibration_controls()
        self._emit_overlay_event("refresh")

    def _confirm_ideal_calibration_sample(self, record: bool) -> None:
        if not self._ideal_calibration_active:
            return
        if not self._ideal_calibration_awaiting_confirmation:
            return
        if self._ideal_calibration_pending_sample is None:
            return
        if record:
            self._ideal_calibration_samples.append(self._ideal_calibration_pending_sample)
            self._ideal_calibration_index += 1
            if self._ideal_calibration_index >= self._ideal_calibration_samples_total:
                self._finalize_ideal_calibration(self._ideal_calibration_samples)
                self._ideal_calibration_active = False
                self._ideal_calibration_targets = []
                self._ideal_calibration_samples = []
                self._ideal_calibration_index = 0
        self._ideal_calibration_pending_sample = None
        self._ideal_calibration_awaiting_confirmation = False
        self._update_ideal_calibration_labels()
        self._update_ideal_calibration_controls()
        self._emit_overlay_event("refresh")

    def _finalize_ideal_calibration(self, samples: list[IdealCalibrationSample]) -> None:
        if not samples:
            return
        map_data = self._build_ideal_calibration_map(samples)
        if map_data:
            self._set_skill_calibration_map(self._ideal_calibration_skill, map_data)
            self._ideal_calibration_last_error = pgettext(
                "Controller Widgets", "Ideal calibration saved."
            )
        else:
            self._ideal_calibration_last_error = pgettext(
                "Controller Widgets", "Unable to build calibration map."
            )

    def _build_ideal_calibration_targets(self, samples: int) -> list[float]:
        if samples <= 0:
            return []
        step = 360.0 / samples
        return [self._normalize_angle(i * step) for i in range(samples)]

    def _get_boundary_radius_at_angle(self, angle: float) -> float:
        distances = self._get_anchor_distances()
        angle = self._normalize_angle(angle)
        radians = math.radians(angle)
        dx = math.cos(radians)
        dy = math.sin(radians)
        if distances is None:
            return self.DEFAULT_CAST_RADIUS
        up, down, left, right = distances
        diagonals = self._get_diagonal_offsets(allow_default_init=True)
        center_x, center_y = self._get_window_center()
        if diagonals is not None:
            contour = self._build_diagonal_contour(center_x, center_y, distances, diagonals)
            distance = self._ray_intersection_distance((center_x, center_y), (dx, dy), contour)
            if distance is not None and distance > 0:
                return distance
        rx = right if dx >= 0 else left
        ry = down if dy >= 0 else up
        if rx > 0 and ry > 0:
            denom = (abs(dx) / rx) ** 2 + (abs(dy) / ry) ** 2
            if denom > 0:
                return 1.0 / math.sqrt(denom)
        return self.DEFAULT_CAST_RADIUS

    def _get_current_calibration_target(self) -> tuple[float, float, tuple[float, float]] | None:
        if not self._ideal_calibration_targets or self._ideal_calibration_index >= len(self._ideal_calibration_targets):
            return None
        angle = self._ideal_calibration_targets[self._ideal_calibration_index]
        radius = self._get_boundary_radius_at_angle(angle) * self.IDEAL_CALIBRATION_TARGET_RATIO
        center_x, center_y = self._get_window_center()
        radians = math.radians(angle)
        target = (center_x + math.cos(radians) * radius, center_y + math.sin(radians) * radius)
        return angle, radius, target

    def _capture_ideal_calibration_sample(self) -> None:
        if not self._ideal_calibration_active:
            return
        if self._ideal_calibration_awaiting_confirmation:
            return
        if self._skill_state == SkillState.CANCELING:
            return
        target = self._get_current_calibration_target()
        if target is None:
            return
        target_angle, target_radius, _target_point = target
        window_center_x, window_center_y = self._get_window_center()
        rel_x = self._mouse_x - window_center_x
        rel_y = self._mouse_y - window_center_y
        x_gain, y_gain = self._get_gains()
        rel_x *= x_gain
        rel_y *= y_gain
        cursor_radius = math.hypot(rel_x, rel_y)
        if cursor_radius == 0:
            return
        cursor_angle = self._normalize_angle(self._vector_to_angle(rel_x, rel_y))
        self._ideal_calibration_pending_sample = IdealCalibrationSample(
            target_angle=target_angle,
            target_radius=target_radius,
            cursor_angle=cursor_angle,
            cursor_radius=cursor_radius,
        )
        self._ideal_calibration_awaiting_confirmation = True
        self._update_ideal_calibration_labels()
        self._update_ideal_calibration_controls()
        self._emit_overlay_event("refresh")

    def _build_ideal_calibration_map(
        self, samples: list[IdealCalibrationSample]
    ) -> dict[str, object] | None:
        if not samples:
            return None
        buckets: dict[float, list[IdealCalibrationSample]] = {}
        for sample in samples:
            angle = self._normalize_angle(sample.target_angle)
            buckets.setdefault(angle, []).append(sample)
        angles: list[float] = []
        offsets: list[float] = []
        scales: list[float] = []
        for angle in sorted(buckets.keys()):
            entries = buckets[angle]
            if not entries:
                continue
            offset_values = []
            scale_values = []
            for entry in entries:
                delta = self._normalize_angle_delta(entry.cursor_angle - entry.target_angle)
                offset_values.append(delta)
                if entry.target_radius > 0:
                    scale = entry.cursor_radius / entry.target_radius
                else:
                    scale = 1.0
                scale = max(self.IDEAL_CALIBRATION_SCALE_MIN, min(scale, self.IDEAL_CALIBRATION_SCALE_MAX))
                scale_values.append(scale)
            angles.append(angle)
            offsets.append(sum(offset_values) / len(offset_values))
            scales.append(sum(scale_values) / len(scale_values))
        if not angles:
            return None
        return {
            "bins": len(angles),
            "angles": angles,
            "angle_offsets": offsets,
            "radius_scales": scales,
        }

    def _update_ideal_calibration_labels(self) -> None:
        status_label = self._ideal_calibration_status_label
        progress_label = self._ideal_calibration_progress_label
        if status_label is None or progress_label is None:
            return
        if self._ideal_calibration_active:
            status_label.set_label(
                pgettext(
                    "Controller Widgets",
                    "Wizard active for skill {skill}. Cast to capture each target.",
                ).format(skill=self._ideal_calibration_skill)
            )
            progress = pgettext(
                "Controller Widgets", "Step {current}/{total}"
            ).format(
                current=min(self._ideal_calibration_index + 1, self._ideal_calibration_samples_total),
                total=self._ideal_calibration_samples_total,
            )
            target = self._get_current_calibration_target()
            if target is not None:
                angle = target[0]
                progress = f"{progress} · {angle:.0f}°"
            if self._ideal_calibration_awaiting_confirmation:
                progress = f"{progress} · {pgettext('Controller Widgets', 'Awaiting confirmation')}"
            progress_label.set_label(progress)
        else:
            data = self._get_skill_calibration_map(self._ideal_calibration_skill)
            if data:
                status_label.set_label(
                    pgettext(
                        "Controller Widgets",
                        "Calibration loaded for {skill} ({bins} bins).",
                    ).format(skill=self._ideal_calibration_skill, bins=data.get("bins", 0))
                )
            else:
                status_label.set_label(
                    pgettext(
                        "Controller Widgets",
                        "No calibration data stored for {skill}.",
                    ).format(skill=self._ideal_calibration_skill)
                )
            progress_label.set_label(self._ideal_calibration_last_error)

    def _set_action_button_sensitive(self, key: str, sensitive: bool) -> None:
        widget = self.get_config_manager().ui_widgets.get(key)
        if widget is None:
            return
        button = widget.get_last_child()
        if isinstance(button, Gtk.Button):
            button.set_sensitive(sensitive)

    def _update_ideal_calibration_controls(self) -> None:
        manager = self.get_config_manager()
        active = self._ideal_calibration_active
        awaiting = self._ideal_calibration_awaiting_confirmation
        manager.set_visible(self.IDEAL_CALIBRATION_START_CONFIG_KEY, not active)
        manager.set_visible(self.IDEAL_CALIBRATION_STOP_CONFIG_KEY, active)
        manager.set_visible(self.IDEAL_CALIBRATION_SAVE_PARTIAL_CONFIG_KEY, active)
        manager.set_visible(self.IDEAL_CALIBRATION_CONFIRM_YES_CONFIG_KEY, active)
        manager.set_visible(self.IDEAL_CALIBRATION_CONFIRM_NO_CONFIG_KEY, active)
        manager.set_visible(self.IDEAL_CALIBRATION_CONFIRM_REDO_CONFIG_KEY, active)
        self._set_action_button_sensitive(
            self.IDEAL_CALIBRATION_SAVE_PARTIAL_CONFIG_KEY,
            active and bool(self._ideal_calibration_samples),
        )
        for key in (
            self.IDEAL_CALIBRATION_CONFIRM_YES_CONFIG_KEY,
            self.IDEAL_CALIBRATION_CONFIRM_NO_CONFIG_KEY,
            self.IDEAL_CALIBRATION_CONFIRM_REDO_CONFIG_KEY,
        ):
            self._set_action_button_sensitive(key, awaiting)

    def is_debug_boundary_enabled(self) -> bool:
        raw = self.get_config_value(self.SHOW_DEBUG_BOUNDARY_CONFIG_KEY)
        if isinstance(raw, bool):
            return raw
        if raw is None:
            return True
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return bool(raw)

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

    def _sanitize_diagonal_value(self, raw_value: object) -> int | None:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or not value.is_integer():
            return None
        value_int = int(value)
        if value_int == 0:
            return None
        limit = self._get_anchor_distance_limit()
        if abs(value_int) > limit:
            return None
        return value_int

    def _sanitize_diagonal_pair(
        self, key: str, raw_dx: object, raw_dy: object
    ) -> tuple[int, int] | None:
        dx = self._sanitize_diagonal_value(raw_dx)
        dy = self._sanitize_diagonal_value(raw_dy)
        if dx is None or dy is None:
            return None
        if not self._validate_diagonal_quadrant(key, dx, dy):
            return None
        return (dx, dy)

    def _validate_diagonal_quadrant(self, key: str, dx: int, dy: int) -> bool:
        signs = self.DIAGONAL_QUADRANTS.get(key)
        if signs is None:
            return False
        sign_x, sign_y = signs
        return (dx * sign_x) > 0 and (dy * sign_y) > 0

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
        self._ensure_diagonal_defaults()

    def _reset_anchor_distances(self) -> None:
        self.set_config_value(self.ANCHOR_UP_CONFIG_KEY, "")
        self.set_config_value(self.ANCHOR_DOWN_CONFIG_KEY, "")
        self.set_config_value(self.ANCHOR_LEFT_CONFIG_KEY, "")
        self.set_config_value(self.ANCHOR_RIGHT_CONFIG_KEY, "")

    def _get_diagonal_offsets(
        self, allow_default_init: bool = True
    ) -> dict[str, tuple[int, int]] | None:
        if not self._are_anchor_distances_valid():
            return None
        values = {
            "ur": (
                self.get_config_value(self.DIAG_UR_DX_CONFIG_KEY),
                self.get_config_value(self.DIAG_UR_DY_CONFIG_KEY),
            ),
            "dr": (
                self.get_config_value(self.DIAG_DR_DX_CONFIG_KEY),
                self.get_config_value(self.DIAG_DR_DY_CONFIG_KEY),
            ),
            "dl": (
                self.get_config_value(self.DIAG_DL_DX_CONFIG_KEY),
                self.get_config_value(self.DIAG_DL_DY_CONFIG_KEY),
            ),
            "ul": (
                self.get_config_value(self.DIAG_UL_DX_CONFIG_KEY),
                self.get_config_value(self.DIAG_UL_DY_CONFIG_KEY),
            ),
        }
        results: dict[str, tuple[int, int]] = {}
        missing_keys: list[str] = []
        for key_name, (raw_dx, raw_dy) in values.items():
            if raw_dx in (None, "") or raw_dy in (None, ""):
                missing_keys.append(key_name)
                continue
            sanitized = self._sanitize_diagonal_pair(key_name, raw_dx, raw_dy)
            if sanitized is None:
                return None
            results[key_name] = sanitized
        if missing_keys and allow_default_init:
            defaults = self._default_diagonal_offsets()
            for key_name in missing_keys:
                if key_name in defaults:
                    results[key_name] = defaults[key_name]
            self._store_diagonal_offsets(results)
        if len(results) != 4:
            return None
        return results

    def _default_diagonal_offsets(self) -> dict[str, tuple[int, int]]:
        distances = self._get_anchor_distances()
        if distances is None:
            return {}
        up, down, left, right = distances
        scale = self.DIAGONAL_DEFAULT_SCALE
        return {
            "ur": (max(1, int(round(right * scale))), -max(1, int(round(up * scale)))),
            "dr": (max(1, int(round(right * scale))), max(1, int(round(down * scale)))),
            "dl": (-max(1, int(round(left * scale))), max(1, int(round(down * scale)))),
            "ul": (-max(1, int(round(left * scale))), -max(1, int(round(up * scale)))),
        }

    def _ensure_diagonal_defaults(self) -> None:
        if not self._are_anchor_distances_valid():
            return
        current = self._get_diagonal_offsets(allow_default_init=False)
        if current is not None:
            return
        defaults = self._default_diagonal_offsets()
        if defaults:
            self._store_diagonal_offsets(defaults)

    def _store_diagonal_offsets(self, offsets: dict[str, tuple[int, int]]) -> None:
        mapping = {
            "ur": (self.DIAG_UR_DX_CONFIG_KEY, self.DIAG_UR_DY_CONFIG_KEY),
            "dr": (self.DIAG_DR_DX_CONFIG_KEY, self.DIAG_DR_DY_CONFIG_KEY),
            "dl": (self.DIAG_DL_DX_CONFIG_KEY, self.DIAG_DL_DY_CONFIG_KEY),
            "ul": (self.DIAG_UL_DX_CONFIG_KEY, self.DIAG_UL_DY_CONFIG_KEY),
        }
        for key_name, (dx, dy) in offsets.items():
            keys = mapping.get(key_name)
            if keys is None:
                continue
            self.set_config_value(keys[0], int(dx))
            self.set_config_value(keys[1], int(dy))

    def _reset_diagonal_offsets(self) -> None:
        self.set_config_value(self.DIAG_UR_DX_CONFIG_KEY, "")
        self.set_config_value(self.DIAG_UR_DY_CONFIG_KEY, "")
        self.set_config_value(self.DIAG_DR_DX_CONFIG_KEY, "")
        self.set_config_value(self.DIAG_DR_DY_CONFIG_KEY, "")
        self.set_config_value(self.DIAG_DL_DX_CONFIG_KEY, "")
        self.set_config_value(self.DIAG_DL_DY_CONFIG_KEY, "")
        self.set_config_value(self.DIAG_UL_DX_CONFIG_KEY, "")
        self.set_config_value(self.DIAG_UL_DY_CONFIG_KEY, "")

    def _clamp_diagonal_offset(
        self, key: str, dx: float, dy: float
    ) -> tuple[int, int] | None:
        signs = self.DIAGONAL_QUADRANTS.get(key)
        if signs is None:
            return None
        sign_x, sign_y = signs
        limit = self._get_anchor_distance_limit()
        dx_value = int(round(dx))
        dy_value = int(round(dy))
        dx_value = max(-limit, min(limit, dx_value))
        dy_value = max(-limit, min(limit, dy_value))
        if sign_x > 0:
            dx_value = max(dx_value, 1)
        else:
            dx_value = min(dx_value, -1)
        if sign_y > 0:
            dy_value = max(dy_value, 1)
        else:
            dy_value = min(dy_value, -1)
        return (dx_value, dy_value)

    def get_diagonal_handle_positions(self) -> dict[str, tuple[float, float]] | None:
        offsets = self._get_diagonal_offsets(allow_default_init=True)
        if offsets is None:
            return None
        center_x, center_y = self._get_window_center()
        return {
            key: (center_x + dx, center_y + dy)
            for key, (dx, dy) in offsets.items()
        }

    def get_diagonal_handle_radius(self) -> int:
        return self.DIAGONAL_HANDLE_RADIUS

    def get_diagonal_offset(self, key: str) -> tuple[int, int] | None:
        offsets = self._get_diagonal_offsets(allow_default_init=True)
        if offsets is None:
            return None
        return offsets.get(key)

    def update_diagonal_offset(self, key: str, dx: float, dy: float) -> bool:
        clamped = self._clamp_diagonal_offset(key, dx, dy)
        if clamped is None:
            return False
        self._store_diagonal_offsets({key: clamped})
        self._sync_diagonal_inputs()
        return True

    def _get_deadzone(self) -> float:
        raw_deadzone = self.get_config_value(self.ANCHOR_DEADZONE_CONFIG_KEY)
        try:
            value = float(raw_deadzone)
        except (TypeError, ValueError):
            return self.DEADZONE_DEFAULT
        if not math.isfinite(value):
            return self.DEADZONE_DEFAULT
        return min(max(value, 0.0), self.DEADZONE_MAX)

    def _apply_deadzone(self, length: float) -> float:
        deadzone = self._get_deadzone()
        if length < deadzone:
            return 0.0
        if deadzone > 0:
            scaled_length = (length - deadzone) / (1.0 - deadzone)
            return max(0.0, min(scaled_length, 1.0))
        return min(max(length, 0.0), 1.0)

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

    def _normalize_angle(self, angle: float) -> float:
        angle = angle % 360.0
        if angle < 0:
            angle += 360.0
        return angle

    def _normalize_angle_delta(self, delta: float) -> float:
        while delta > 180.0:
            delta -= 360.0
        while delta < -180.0:
            delta += 360.0
        return delta

    def _get_calibration_store(self) -> dict[str, object]:
        raw = self.get_config_value(self.IDEAL_CALIBRATION_DATA_CONFIG_KEY)
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _set_calibration_store(self, data: dict[str, object]) -> None:
        try:
            payload = json.dumps(data, ensure_ascii=False)
        except (TypeError, ValueError):
            payload = ""
        self.set_config_value(self.IDEAL_CALIBRATION_DATA_CONFIG_KEY, payload)

    def _get_skill_calibration_map(self, skill: str) -> dict[str, object] | None:
        data = self._get_calibration_store()
        entry = data.get(skill)
        return entry if isinstance(entry, dict) else None

    def _set_skill_calibration_map(self, skill: str, map_data: dict[str, object]) -> None:
        data = self._get_calibration_store()
        data[skill] = map_data
        self._set_calibration_store(data)

    def _clear_skill_calibration_map(self, skill: str) -> None:
        data = self._get_calibration_store()
        if skill in data:
            data.pop(skill, None)
            self._set_calibration_store(data)

    def _get_calibration_adjustment(self, angle: float) -> tuple[float, float]:
        if self._ideal_calibration_active:
            return (0.0, 1.0)
        data = self._get_skill_calibration_map(self._ideal_calibration_skill)
        if not data:
            return (0.0, 1.0)
        angles = data.get("angles")
        offsets = data.get("angle_offsets")
        scales = data.get("radius_scales")
        if not (
            isinstance(angles, list)
            and isinstance(offsets, list)
            and isinstance(scales, list)
            and len(angles) == len(offsets) == len(scales)
            and angles
        ):
            return (0.0, 1.0)
        angle = self._normalize_angle(angle)
        pairs = sorted(zip(angles, offsets, scales), key=lambda item: item[0])
        angles_sorted = [p[0] for p in pairs]
        offsets_sorted = [p[1] for p in pairs]
        scales_sorted = [p[2] for p in pairs]
        if angle <= angles_sorted[0]:
            prev_angle = angles_sorted[-1] - 360.0
            prev_offset = offsets_sorted[-1]
            prev_scale = scales_sorted[-1]
            next_angle = angles_sorted[0]
            next_offset = offsets_sorted[0]
            next_scale = scales_sorted[0]
        elif angle >= angles_sorted[-1]:
            prev_angle = angles_sorted[-1]
            prev_offset = offsets_sorted[-1]
            prev_scale = scales_sorted[-1]
            next_angle = angles_sorted[0] + 360.0
            next_offset = offsets_sorted[0]
            next_scale = scales_sorted[0]
        else:
            prev_angle = angles_sorted[0]
            prev_offset = offsets_sorted[0]
            prev_scale = scales_sorted[0]
            next_angle = angles_sorted[-1]
            next_offset = offsets_sorted[-1]
            next_scale = scales_sorted[-1]
            for idx in range(len(angles_sorted) - 1):
                if angles_sorted[idx] <= angle <= angles_sorted[idx + 1]:
                    prev_angle = angles_sorted[idx]
                    prev_offset = offsets_sorted[idx]
                    prev_scale = scales_sorted[idx]
                    next_angle = angles_sorted[idx + 1]
                    next_offset = offsets_sorted[idx + 1]
                    next_scale = scales_sorted[idx + 1]
                    break
        span = max(next_angle - prev_angle, 1e-6)
        t = (angle - prev_angle) / span
        offset = prev_offset + (next_offset - prev_offset) * t
        scale = prev_scale + (next_scale - prev_scale) * t
        return (offset, scale)

    def _apply_ideal_calibration_to_vector(self, rel_x: float, rel_y: float) -> tuple[float, float]:
        if rel_x == 0 and rel_y == 0:
            return (0.0, 0.0)
        angle = self._vector_to_angle(rel_x, rel_y)
        radius = math.hypot(rel_x, rel_y)
        offset, scale = self._get_calibration_adjustment(angle)
        corrected_angle = math.radians(self._normalize_angle(angle + offset))
        corrected_radius = radius * max(self.IDEAL_CALIBRATION_SCALE_MIN, min(scale, self.IDEAL_CALIBRATION_SCALE_MAX))
        return (
            math.cos(corrected_angle) * corrected_radius,
            math.sin(corrected_angle) * corrected_radius,
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
        if self._are_anchor_distances_valid():
            self._ensure_diagonal_defaults()
            self._sync_diagonal_inputs()
            self._set_diagonal_controls_visible(True)
        self._anchor_set_mode = None
        self._emit_overlay_event("stop")
        self._emit_overlay_event("refresh")

    def _get_anchor_normalized_vector(
        self, center_x: float, center_y: float, cursor_x: float, cursor_y: float
    ) -> tuple[float, float] | None:
        distances = self._get_anchor_distances()
        if distances is None:
            return None
        dx = cursor_x - center_x
        dy = cursor_y - center_y
        length = math.hypot(dx, dy)
        if length == 0:
            return (0.0, 0.0)
        unit_x = dx / length
        unit_y = dy / length

        diagonal_offsets = self._get_diagonal_offsets(allow_default_init=True)
        contour = None
        if diagonal_offsets is not None:
            contour = self._build_diagonal_contour(center_x, center_y, distances, diagonal_offsets)
        if contour:
            boundary = self._ray_intersection_distance(
                (center_x, center_y), (unit_x, unit_y), contour
            )
            if boundary is not None and boundary > 0:
                normalized = min(length / boundary, 1.0)
                normalized = self._apply_deadzone(normalized)
                return (unit_x * normalized, unit_y * normalized)

        up, down, left, right = distances
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
        scaled_length = self._apply_deadzone(length)
        if scaled_length == 0:
            return (0.0, 0.0)
        nx = (nx / length) * scaled_length
        ny = (ny / length) * scaled_length
        return (nx, ny)

    def _build_diagonal_contour(
        self,
        center_x: float,
        center_y: float,
        distances: tuple[int, int, int, int],
        diagonals: dict[str, tuple[int, int]],
        samples: int = 256,
    ) -> list[tuple[float, float]]:
        up, down, left, right = distances
        points = [
            (center_x, center_y - up),
            (center_x + diagonals["ur"][0], center_y + diagonals["ur"][1]),
            (center_x + right, center_y),
            (center_x + diagonals["dr"][0], center_y + diagonals["dr"][1]),
            (center_x, center_y + down),
            (center_x + diagonals["dl"][0], center_y + diagonals["dl"][1]),
            (center_x - left, center_y),
            (center_x + diagonals["ul"][0], center_y + diagonals["ul"][1]),
        ]
        return self._catmull_rom_closed(points, samples)

    @staticmethod
    def _catmull_rom_closed(
        points: list[tuple[float, float]], samples: int
    ) -> list[tuple[float, float]]:
        if len(points) < 4:
            return points
        total_samples = max(samples, len(points) * 4)
        per_segment = max(1, total_samples // len(points))
        spline: list[tuple[float, float]] = []
        count = len(points)
        for i in range(count):
            p0 = points[(i - 1) % count]
            p1 = points[i]
            p2 = points[(i + 1) % count]
            p3 = points[(i + 2) % count]
            for step in range(per_segment):
                t = step / per_segment
                t2 = t * t
                t3 = t2 * t
                x = 0.5 * (
                    2 * p1[0]
                    + (-p0[0] + p2[0]) * t
                    + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                    + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
                )
                y = 0.5 * (
                    2 * p1[1]
                    + (-p0[1] + p2[1]) * t
                    + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                    + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
                )
                spline.append((x, y))
        if spline and spline[0] != spline[-1]:
            spline.append(spline[0])
        return spline

    @staticmethod
    def _ray_intersection_distance(
        origin: tuple[float, float],
        direction: tuple[float, float],
        contour: list[tuple[float, float]],
    ) -> float | None:
        if not contour or len(contour) < 2:
            return None
        ox, oy = origin
        dx, dy = direction
        min_t: float | None = None

        def cross(ax: float, ay: float, bx: float, by: float) -> float:
            return ax * by - ay * bx

        for i in range(len(contour) - 1):
            ax, ay = contour[i]
            bx, by = contour[i + 1]
            sx = bx - ax
            sy = by - ay
            rxs = cross(dx, dy, sx, sy)
            if abs(rxs) < 1e-6:
                continue
            qpx = ax - ox
            qpy = ay - oy
            t = cross(qpx, qpy, sx, sy) / rxs
            u = cross(qpx, qpy, dx, dy) / rxs
            if t >= 0 and 0 <= u <= 1:
                if min_t is None or t < min_t:
                    min_t = t
        return min_t

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
        diagonals = self._get_diagonal_offsets(allow_default_init=True)
        points: list[tuple[float, float]] = []
        if diagonals is not None:
            points = self._build_diagonal_contour(center_x, center_y, distances, diagonals)
        if not points:
            segments = 256
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
        diagonal_points = None
        if diagonals is not None:
            diagonal_points = {
                key: (center_x + dx, center_y + dy)
                for key, (dx, dy) in diagonals.items()
            }
        return {
            "center": center,
            "anchors": anchors,
            "contour": points,
            "diagonals": diagonal_points,
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

    def get_ideal_calibration_overlay_data(self) -> dict[str, object] | None:
        if not self._ideal_calibration_active:
            return None
        target = self._get_current_calibration_target()
        if target is None:
            return None
        angle, _radius, point = target
        title = pgettext(
            "Controller Widgets", "Ideal Calibration ({skill})"
        ).format(skill=self._ideal_calibration_skill)
        progress = pgettext(
            "Controller Widgets", "Step {current}/{total} · Target {angle}°"
        ).format(
            current=min(self._ideal_calibration_index + 1, self._ideal_calibration_samples_total),
            total=self._ideal_calibration_samples_total,
            angle=int(round(angle)),
        )
        instruction = pgettext(
            "Controller Widgets",
            "Move the cursor so the skill lands on the target, then cast/release.",
        )
        confirmation = pgettext(
            "Controller Widgets",
            "Did it hit the target? Confirm in settings (Yes / No / Redo).",
        )
        return {
            "active": True,
            "center": self._get_window_center(),
            "target": point,
            "title": title,
            "progress": progress,
            "instruction": instruction,
            "awaiting_confirmation": self._ideal_calibration_awaiting_confirmation,
            "confirmation": confirmation,
        }

    # def _on_custom_event(self, event):
    #     """处理自定义事件"""
    #     logger.debug(f"SkillCasting {id(self)} received custom event: {event.data}")

    #     if self._cancel_button_widget["widget"] is not None and id(
    #         self._cancel_button_widget["widget"]
    #     ) == event.data.get("widget_id"):

    #         logger.info(f"Detected cancel button destruction, resetting state")
    #         self._cancel_button_widget["widget"] = None
    #         self.cancel_button_config.value = False

    def _enable_cancel_button(self):
        """启用取消施法按钮"""
        if self.cancel_button_widget["widget"] is not None:
            return

        w, h = self.screen_info.get_host_resolution()
        # 发送事件通知window创建取消按钮
        create_data = {
            "widget": CancelCasting(event_bus=self.event_bus, pointer_id_manager=self.pointer_id_manager, key_registry=self.key_registry),
            "x": 0.8 * w,
            "y": h / 2,
        }

        self.event_bus.emit(Event(EventType.CREATE_WIDGET, self, create_data))
        self.cancel_button_widget["widget"] = create_data["widget"]

    def _disable_cancel_button(self):
        """禁用取消施法按钮"""
        if self.cancel_button_widget["widget"] is None:
            return

        # 发送事件通知window删除取消按钮
        self.event_bus.emit(
            Event(EventType.DELETE_WIDGET, self, self.cancel_button_widget["widget"])
        )
        self.cancel_button_widget["widget"] = None

    def __del__(self):
        """析构时清理取消按钮和异步任务"""
        # if self._cancel_button_widget is not None:
        #     self._disable_cancel_button()

        # 取消异步任务
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
        if self._event_processor_task and not self._event_processor_task.done():
            self._event_processor_task.cancel()

    def on_delete(self):
        self._emit_overlay_event("unregister")
        super().on_delete()

    def draw_widget_content(self, cr: "Context[Surface]", width: int, height: int):
        """绘制圆形按钮的具体内容"""
        # 计算圆心和半径
        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) / 2 - 5  # 留出边距

        # 绘制圆形背景
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.6)
        cr.arc(center_x, center_y, radius, 0, 2 * math.pi)
        cr.fill()

        # 绘制雷达扫描效果
        # 绘制同心圆（类似雷达的圆圈）- 从内向外颜色加深
        # 内圆 - 最浅灰色 (133/400 = 0.33)
        inner_radius = radius * 0.33
        cr.set_source_rgba(0.8, 0.8, 0.8, 0.8)  # 最浅灰色
        cr.arc(center_x, center_y, inner_radius, 0, 2 * math.pi)
        cr.fill()

        # 中圆 - 中等灰色 (266/400 = 0.66)
        middle_radius = radius * 0.66
        cr.set_source_rgba(0.6, 0.6, 0.6, 0.8)  # 中等灰色
        cr.arc(center_x, center_y, middle_radius, 0, 2 * math.pi)
        cr.fill()

        # 外圆已经是原本的圆形背景(0.5, 0.5, 0.5, 0.6)，是最深的，保持不变

        # 绘制135度扇形朝上 - 透明度高
        cr.set_source_rgba(64 / 255, 224 / 255, 208 / 255, 0.25)  # 青绿色，透明度0.25
        cr.move_to(center_x, center_y)
        # 135度扇形，以向上(-π/2)为中心，向两边扩展67.5度
        start_angle_135 = -math.pi / 2 - 135 * math.pi / 360  # 向上中心-67.5度
        end_angle_135 = -math.pi / 2 + 135 * math.pi / 360  # 向上中心+67.5度
        cr.arc(center_x, center_y, radius, start_angle_135, end_angle_135)
        cr.close_path()
        cr.fill()

        # 绘制45度扇形朝上 - 透明度低
        cr.set_source_rgba(64 / 255, 224 / 255, 208 / 255, 0.15)  # 青绿色，透明度0.15
        cr.move_to(center_x, center_y)
        # 45度扇形，以向上(-π/2)为中心，向两边扩展22.5度
        start_angle_45 = -math.pi / 2 - 45 * math.pi / 360  # 向上中心-22.5度
        end_angle_45 = -math.pi / 2 + 45 * math.pi / 360  # 向上中心+22.5度
        cr.arc(center_x, center_y, radius, start_angle_45, end_angle_45)
        cr.close_path()
        cr.fill()

        # 绘制圆形边框
        cr.set_source_rgba(0.3, 0.3, 0.3, 0.9)
        cr.set_line_width(2)
        cr.arc(center_x, center_y, radius, 0, 2 * math.pi)
        cr.stroke()

    def draw_text_content(self, cr: "Context[Surface]", width: int, height: int):
        """重写文本绘制 - 使用白色文字适配圆形按钮"""
        if self.text:
            center_x = width / 2
            center_y = height / 2

            cr.set_source_rgba(1, 1, 1, 1)  # 白色文字
            cr.select_font_face(
                "Arial", FONT_SLANT_NORMAL, FONT_WEIGHT_BOLD
            )
            cr.set_font_size(12)
            text_extents = cr.text_extents(self.text)
            x = center_x - text_extents.width / 2
            y = center_y + text_extents.height / 2
            cr.move_to(x, y)
            cr.show_text(self.text)

            # 清除路径，避免影响后续绘制
            cr.new_path()

    def draw_selection_border(self, cr: "Context[Surface]", width: int, height: int):
        """重写选择边框绘制 - 绘制圆形边框适配圆形按钮"""
        center_x = width / 2
        center_y = height / 2
        radius = min(width, height) / 2 - 5

        # 绘制圆形选择边框
        cr.set_source_rgba(0.2, 0.6, 1.0, 0.8)
        cr.set_line_width(3)
        cr.arc(center_x, center_y, radius + 3, 0, 2 * math.pi)
        cr.stroke()

    def draw_mapping_mode_background(
        self, cr: "Context[Surface]", width: int, height: int
    ):
        """映射模式下的背景绘制 - 根据文字长度的圆角矩形"""
        center_x = width / 2
        center_y = height / 2

        # 计算文字尺寸
        if self.text:
            cr.set_font_size(12)
            text_extents = cr.text_extents(self.text)
            text_width = text_extents.width
            text_height = text_extents.height
        else:
            text_width = 20  # 默认宽度
            text_height = 12  # 默认高度

        # 圆角矩形参数
        padding_x = 8  # 左右内边距
        padding_y = 4  # 上下内边距
        corner_radius = 6  # 圆角半径

        rect_width = text_width + 2 * padding_x
        rect_height = text_height + 2 * padding_y

        # 确保矩形不会太小
        rect_width = max(rect_width, 24)
        rect_height = max(rect_height, 16)

        # 计算矩形位置（居中）
        rect_x = center_x - rect_width / 2
        rect_y = center_y - rect_height / 2

        # 绘制圆角矩形背景
        cr.set_source_rgba(0.6, 0.6, 0.6, 0.7)  # 稍微加深一点透明度

        # 使用路径绘制圆角矩形
        # 左上角
        cr.move_to(rect_x + corner_radius, rect_y)
        # 上边
        cr.line_to(rect_x + rect_width - corner_radius, rect_y)
        # 右上角
        cr.arc(
            rect_x + rect_width - corner_radius,
            rect_y + corner_radius,
            corner_radius,
            -math.pi / 2,
            0,
        )
        # 右边
        cr.line_to(rect_x + rect_width, rect_y + rect_height - corner_radius)
        # 右下角
        cr.arc(
            rect_x + rect_width - corner_radius,
            rect_y + rect_height - corner_radius,
            corner_radius,
            0,
            math.pi / 2,
        )
        # 下边
        cr.line_to(rect_x + corner_radius, rect_y + rect_height)
        # 左下角
        cr.arc(
            rect_x + corner_radius,
            rect_y + rect_height - corner_radius,
            corner_radius,
            math.pi / 2,
            math.pi,
        )
        # 左边
        cr.line_to(rect_x, rect_y + corner_radius)
        # 左上角
        cr.arc(
            rect_x + corner_radius,
            rect_y + corner_radius,
            corner_radius,
            math.pi,
            3 * math.pi / 2,
        )
        cr.close_path()
        cr.fill()

        # 绘制圆角矩形边框
        cr.set_source_rgba(0.4, 0.4, 0.4, 0.9)
        cr.set_line_width(1)
        # 重复上面的路径
        cr.move_to(rect_x + corner_radius, rect_y)
        cr.line_to(rect_x + rect_width - corner_radius, rect_y)
        cr.arc(
            rect_x + rect_width - corner_radius,
            rect_y + corner_radius,
            corner_radius,
            -math.pi / 2,
            0,
        )
        cr.line_to(rect_x + rect_width, rect_y + rect_height - corner_radius)
        cr.arc(
            rect_x + rect_width - corner_radius,
            rect_y + rect_height - corner_radius,
            corner_radius,
            0,
            math.pi / 2,
        )
        cr.line_to(rect_x + corner_radius, rect_y + rect_height)
        cr.arc(
            rect_x + corner_radius,
            rect_y + rect_height - corner_radius,
            corner_radius,
            math.pi / 2,
            math.pi,
        )
        cr.line_to(rect_x, rect_y + corner_radius)
        cr.arc(
            rect_x + corner_radius,
            rect_y + corner_radius,
            corner_radius,
            math.pi,
            3 * math.pi / 2,
        )
        cr.close_path()
        cr.stroke()

    def draw_mapping_mode_content(
        self, cr: "Context[Surface]", width: int, height: int
    ):
        if self.text:
            center_x = width / 2
            center_y = height / 2

            # 使用白色文字以在灰色背景上清晰显示
            cr.set_source_rgba(1, 1, 1, 1)  # 白色文字
            cr.select_font_face(
                "Arial", FONT_SLANT_NORMAL, FONT_WEIGHT_BOLD
            )
            cr.set_font_size(12)
            text_extents = cr.text_extents(self.text)
            x = center_x - text_extents.width / 2
            y = center_y + text_extents.height / 2
            cr.move_to(x, y)
            cr.show_text(self.text)

            # 清除路径，避免影响后续绘制
            cr.new_path()

    def _get_window_center(self) -> tuple[float, float]:
        """获取窗口中心坐标"""
        calibrated = self._get_calibrated_center()
        if calibrated is not None:
            return calibrated
        w, h = self.screen_info.get_host_resolution()
        return (w / 2, h / 2)

    def _get_window_size(self) -> tuple[int, int]:
        """获取窗口大小"""
        w, h = self.screen_info.get_host_resolution()
        return w, h

    def _map_circle_to_circle(
        self, mouse_x: float, mouse_y: float
    ) -> tuple[float, float]:
        """
        将鼠标在圆形范围内的坐标映射到虚拟摇杆圆形范围内的坐标

        外圆：窗口中心为圆心，半径按百分比缩放
        内圆：widget中心为圆心，宽度/2为半径
        """
        window_center_x, window_center_y = self._get_window_center()

        widget_center_x = self.center_x
        widget_center_y = self.center_y
        widget_radius = self.width / 2

        rel_x = mouse_x - window_center_x
        rel_y = mouse_y - window_center_y

        x_gain, y_gain = self._get_gains()
        rel_x *= x_gain
        rel_y *= y_gain

        rel_x, rel_y = self._apply_ideal_calibration_to_vector(rel_x, rel_y)
        corrected_mouse_x = window_center_x + rel_x
        corrected_mouse_y = window_center_y + rel_y

        anchor_vector = self._get_anchor_normalized_vector(
            window_center_x, window_center_y, corrected_mouse_x, corrected_mouse_y
        )
        if anchor_vector is not None:
            nx, ny = anchor_vector
            return (
                widget_center_x + nx * widget_radius,
                widget_center_y + ny * widget_radius,
            )

        outer_radius = self.DEFAULT_CAST_RADIUS

        distance = math.sqrt(rel_x * rel_x + rel_y * rel_y)

        if distance == 0:
            return (widget_center_x, widget_center_y)

        ratio = min(distance / outer_radius, 1.0)
        target_x = widget_center_x + (rel_x / distance) * ratio * widget_radius
        target_y = widget_center_y + (rel_y / distance) * ratio * widget_radius

        return (target_x, target_y)

    def _emit_touch_event(
        self, action: AMotionEventAction, position: tuple[float, float] | None = None
    ):
        """发送触摸事件"""
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

    def on_key_triggered(
        self,
        key_combination: KeyCombination | None = None,
        event: "InputEvent | None" = None,
    ):
        """按键触发事件处理 - 将事件放入异步队列"""
        if not event or not event.event_type:
            return False

        # 取消施法状态下不响应任何用户输入
        if self._skill_state == SkillState.CANCELING:
            return True

        # 判断事件类型
        is_key_press = event.event_type == "key_press"
        is_mouse_motion = event.event_type == "mouse_motion"

        if not (is_key_press or is_mouse_motion):
            return False

        if is_mouse_motion:
            if not event.position:
                return False
            self._mouse_x, self._mouse_y = event.position

        # 将事件放入异步队列
        skill_event = SkillEvent(
            type=event.event_type,
            data={
                "key_combination": key_combination,
                "position": event.position,
                "timestamp": time.time(),
            },
        )

        # 非阻塞方式放入队列
        try:
            self._event_queue.put_nowait(skill_event)
        except asyncio.QueueFull:
            pass

        return True

    def on_key_released(
        self,
        key_combination: KeyCombination | None = None,
        event: "InputEvent | None" = None,
    ):
        """按键释放事件处理 - 将事件放入异步队列"""
        # 将事件放入异步队列
        skill_event = SkillEvent(
            type="key_release",
            data={"key_combination": key_combination, "timestamp": time.time()},
        )

        # 非阻塞方式放入队列
        try:
            self._event_queue.put_nowait(skill_event)
        except asyncio.QueueFull:
            pass

        return True

    def get_editable_regions(self) -> list["EditableRegion"]:
        return [
            {
                "id": "default",
                "name": "按键映射",
                "bounds": (0, 0, self.width, self.height),
                "get_keys": lambda: self.final_keys.copy(),
                "set_keys": lambda keys: setattr(
                    self, "final_keys", set(keys) if keys else set()
                ),
            }
        ]

    @property
    def mapping_start_x(self):
        return int(self.x + self.width / 2)

    @property
    def mapping_start_y(self):
        return int(self.y + self.height / 2)

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
        self._set_diagonal_controls_visible(
            self._are_anchor_distances_valid() and not mapping_mode
        )
        if mapping_mode:
            self.cancel_anchor_set()
            self.cancel_tuning()
        self._emit_overlay_event("refresh")
