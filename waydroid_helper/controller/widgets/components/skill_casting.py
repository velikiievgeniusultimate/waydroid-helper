#!/usr/bin/env python3
"""
技能释放按钮组件
一个圆形的半透明灰色按钮，支持技能释放操作
"""

import asyncio
import math
import time
from dataclasses import dataclass
from enum import Enum
from gettext import pgettext
from typing import TYPE_CHECKING, cast

from waydroid_helper.controller.widgets.components.cancel_casting import \
    CancelCasting
from waydroid_helper.controller.widgets.components.skill_casting_v2 import (
    SkillCastingCalibration,
    map_pointer_to_widget_target,
)
from waydroid_helper.controller.widgets.components.skill_casting_perspective import (
    PerspectiveEllipseModel,
)
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


@Editable
@Resizable(resize_strategy=ResizableDecorator.RESIZE_CENTER)
class SkillCasting(BaseWidget):
    """技能释放按钮组件 - 圆形半透明按钮"""

    # 组件元数据
    WIDGET_NAME = pgettext("Controller Widgets", "Skill Casting")
    WIDGET_DESCRIPTION = pgettext(
        "Controller Widgets",
        "Commonly used when using the characters' skills, click and cooperate with the mouse to release skills.",
    )
    CENTER_X_CONFIG_KEY = "skill_calibrated_center_x"
    CENTER_Y_CONFIG_KEY = "skill_calibrated_center_y"
    CENTER_X_INPUT_CONFIG_KEY = "skill_center_x_input"
    CENTER_Y_INPUT_CONFIG_KEY = "skill_center_y_input"
    Y_OFFSET_CONFIG_KEY = "skill_ellipse_y_offset"
    CALIBRATE_CENTER_CONFIG_KEY = "skill_calibrate_center"
    RESET_CENTER_CONFIG_KEY = "skill_reset_center"
    APPLY_CENTER_CONFIG_KEY = "skill_apply_center"
    ENABLE_PERSPECTIVE_CONFIG_KEY = "skill_enable_perspective_correction"
    RADIUS_X_CONFIG_KEY = "skill_perspective_radius_x"
    RADIUS_Y_CONFIG_KEY = "skill_perspective_radius_y"
    DX_BIAS_CONFIG_KEY = "skill_perspective_dx_bias"
    DY_BIAS_CONFIG_KEY = "skill_perspective_dy_bias"
    DEADZONE_CONFIG_KEY = "skill_perspective_deadzone"
    MAX_RADIUS_CLAMP_CONFIG_KEY = "skill_perspective_max_radius_clamp"
    DISTANCE_CURVE_MODE_CONFIG_KEY = "skill_perspective_distance_curve_mode"
    GAMMA_CONFIG_KEY = "skill_perspective_gamma"
    ANGLE_BIAS_CONFIG_KEY = "skill_perspective_angle_bias"
    RADIUS_SCALE_CONFIG_KEY = "skill_perspective_radius_scale"
    PERSPECTIVE_APPLY_CARDINALS_KEY = "skill_perspective_apply_cardinals"
    PERSPECTIVE_MISMATCH_THRESHOLD_KEY = "skill_perspective_mismatch_threshold"
    PERSPECTIVE_CARDINAL_N_X = "skill_perspective_n_x"
    PERSPECTIVE_CARDINAL_N_Y = "skill_perspective_n_y"
    PERSPECTIVE_CARDINAL_S_X = "skill_perspective_s_x"
    PERSPECTIVE_CARDINAL_S_Y = "skill_perspective_s_y"
    PERSPECTIVE_CARDINAL_W_X = "skill_perspective_w_x"
    PERSPECTIVE_CARDINAL_W_Y = "skill_perspective_w_y"
    PERSPECTIVE_CARDINAL_E_X = "skill_perspective_e_x"
    PERSPECTIVE_CARDINAL_E_Y = "skill_perspective_e_y"
    PERSPECTIVE_DIAG_NE_X = "skill_perspective_ne_x"
    PERSPECTIVE_DIAG_NE_Y = "skill_perspective_ne_y"
    PERSPECTIVE_DIAG_NW_X = "skill_perspective_nw_x"
    PERSPECTIVE_DIAG_NW_Y = "skill_perspective_nw_y"
    PERSPECTIVE_DIAG_SW_X = "skill_perspective_sw_x"
    PERSPECTIVE_DIAG_SW_Y = "skill_perspective_sw_y"
    PERSPECTIVE_DIAG_SE_X = "skill_perspective_se_x"
    PERSPECTIVE_DIAG_SE_Y = "skill_perspective_se_y"
    VERTICAL_SCALE_RATIO = 0.745
    PERSPECTIVE_DEFAULT_RADIUS_X = 460.0
    PERSPECTIVE_DEFAULT_RADIUS_Y = 345.0
    PERSPECTIVE_DEFAULT_MAX_CLAMP = 1.0
    PERSPECTIVE_DEFAULT_DEADZONE = 0.0
    PERSPECTIVE_DEFAULT_GAMMA = 1.0
    PERSPECTIVE_DEFAULT_RADIUS_SCALE = 1.0
    PERSPECTIVE_DEFAULT_ANGLE_BIAS = 0.0
    PERSPECTIVE_RADIUS_MIN = 1.0
    PERSPECTIVE_RADIUS_MAX = 5000.0
    PERSPECTIVE_BIAS_MIN = -500.0
    PERSPECTIVE_BIAS_MAX = 500.0
    PERSPECTIVE_DEADZONE_MAX = 0.3
    PERSPECTIVE_MAX_CLAMP_MIN = 1.0
    PERSPECTIVE_MAX_CLAMP_MAX = 1.2
    PERSPECTIVE_GAMMA_MIN = 0.5
    PERSPECTIVE_GAMMA_MAX = 2.5
    PERSPECTIVE_RADIUS_SCALE_MIN = 0.5
    PERSPECTIVE_RADIUS_SCALE_MAX = 1.5
    PERSPECTIVE_ANGLE_BIAS_MIN = -10.0
    PERSPECTIVE_ANGLE_BIAS_MAX = 10.0
    PERSPECTIVE_MISMATCH_THRESHOLD_DEFAULT = 5.0

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

        self._center_calibration_active: bool = False
        self._calibration_status_label: Gtk.Label | None = None
        self._radius_adjustment: Gtk.Adjustment | None = None
        self._radius_adjustment_updating: bool = False
        self._perspective_diagnostics_label: Gtk.Label | None = None

        # 施法时机配置
        # self.cast_timing: str = CastTiming.ON_RELEASE.value  # 默认为松开释放

        # 设置配置项
        self.setup_config()

        # 监听选中状态变化，用于圆形绘制通知
        self.connect("notify::is-selected", self._on_selection_changed)

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
        circle_radius_config = create_slider_config(
            key="circle_radius",
            label=pgettext("Controller Widgets", "Casting Radius"),
            value=200,
            min_value=1,
            max_value=10000,
            step=1,
            description=pgettext(
                "Controller Widgets",
                "Fine-tune according to the casting range of different skills",
            ),
        )
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
            label=pgettext("Controller Widgets", "Calibrate Anchor Center"),
            button_label=pgettext("Controller Widgets", "Calibrate"),
            description=pgettext(
                "Controller Widgets",
                "Click to enter calibration mode, then click the anchor center on screen.",
            ),
        )
        reset_center_config = create_action_config(
            key=self.RESET_CENTER_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Reset Anchor Center"),
            button_label=pgettext("Controller Widgets", "Reset"),
            description=pgettext(
                "Controller Widgets",
                "Clear the calibrated anchor center and return to the screen center.",
            ),
        )
        center_x_config = create_text_config(
            key=self.CENTER_X_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Anchor Center X"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored anchor center X coordinate."
            ),
            visible=False,
        )
        center_y_config = create_text_config(
            key=self.CENTER_Y_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Anchor Center Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "Stored anchor center Y coordinate."
            ),
            visible=False,
        )
        center_x_input_config = create_text_config(
            key=self.CENTER_X_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Anchor Center X (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Manual anchor center X coordinate in pixels."
            ),
        )
        center_y_input_config = create_text_config(
            key=self.CENTER_Y_INPUT_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Anchor Center Y (px)"),
            value="",
            description=pgettext(
                "Controller Widgets", "Manual anchor center Y coordinate in pixels."
            ),
        )
        y_offset_config = create_text_config(
            key=self.Y_OFFSET_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Ellipse Y Offset (px)"),
            value="0",
            description=pgettext(
                "Controller Widgets",
                "Offset applied to the ellipse center relative to the anchor center.",
            ),
        )
        apply_center_config = create_action_config(
            key=self.APPLY_CENTER_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Apply Anchor Center"),
            button_label=pgettext("Controller Widgets", "Apply"),
            description=pgettext(
                "Controller Widgets", "Apply the manual anchor center coordinates."
            ),
        )
        enable_perspective_config = create_switch_config(
            key=self.ENABLE_PERSPECTIVE_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Enable Perspective Correction"),
            value=False,
            description=pgettext(
                "Controller Widgets",
                "Correct ellipse perspective when mapping aim direction and distance.",
            ),
        )
        perspective_radius_x_config = create_slider_config(
            key=self.RADIUS_X_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Perspective Radius X (px)"),
            value=self.PERSPECTIVE_DEFAULT_RADIUS_X,
            min_value=self.PERSPECTIVE_RADIUS_MIN,
            max_value=self.PERSPECTIVE_RADIUS_MAX,
            step=1,
            description=pgettext(
                "Controller Widgets",
                "Horizontal radius of the perceived skill range ellipse.",
            ),
        )
        perspective_radius_y_config = create_slider_config(
            key=self.RADIUS_Y_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Perspective Radius Y (px)"),
            value=self.PERSPECTIVE_DEFAULT_RADIUS_Y,
            min_value=self.PERSPECTIVE_RADIUS_MIN,
            max_value=self.PERSPECTIVE_RADIUS_MAX,
            step=1,
            description=pgettext(
                "Controller Widgets",
                "Vertical radius of the perceived skill range ellipse.",
            ),
        )
        perspective_dx_bias_config = create_slider_config(
            key=self.DX_BIAS_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Perspective Center X Bias (px)"),
            value=0.0,
            min_value=self.PERSPECTIVE_BIAS_MIN,
            max_value=self.PERSPECTIVE_BIAS_MAX,
            step=1,
            description=pgettext(
                "Controller Widgets",
                "Horizontal bias between anchor center and ellipse center.",
            ),
        )
        perspective_dy_bias_config = create_slider_config(
            key=self.DY_BIAS_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Perspective Center Y Bias (px)"),
            value=0.0,
            min_value=self.PERSPECTIVE_BIAS_MIN,
            max_value=self.PERSPECTIVE_BIAS_MAX,
            step=1,
            description=pgettext(
                "Controller Widgets",
                "Vertical bias between anchor center and ellipse center.",
            ),
        )
        perspective_deadzone_config = create_slider_config(
            key=self.DEADZONE_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Perspective Deadzone"),
            value=self.PERSPECTIVE_DEFAULT_DEADZONE,
            min_value=0.0,
            max_value=self.PERSPECTIVE_DEADZONE_MAX,
            step=0.01,
            description=pgettext(
                "Controller Widgets",
                "Normalized radius below which casting is treated as zero.",
            ),
        )
        perspective_max_clamp_config = create_slider_config(
            key=self.MAX_RADIUS_CLAMP_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Perspective Max Radius"),
            value=self.PERSPECTIVE_DEFAULT_MAX_CLAMP,
            min_value=self.PERSPECTIVE_MAX_CLAMP_MIN,
            max_value=self.PERSPECTIVE_MAX_CLAMP_MAX,
            step=0.01,
            description=pgettext(
                "Controller Widgets",
                "Maximum normalized radius clamp before overshoot.",
            ),
        )
        perspective_curve_mode_config = create_dropdown_config(
            key=self.DISTANCE_CURVE_MODE_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Perspective Distance Curve"),
            options=["linear", "gamma", "smoothstep"],
            option_labels={
                "linear": pgettext("Controller Widgets", "Linear"),
                "gamma": pgettext("Controller Widgets", "Gamma"),
                "smoothstep": pgettext("Controller Widgets", "Smoothstep"),
            },
            value="linear",
            description=pgettext(
                "Controller Widgets",
                "Distance curve applied after perspective correction.",
            ),
        )
        perspective_gamma_config = create_slider_config(
            key=self.GAMMA_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Perspective Gamma"),
            value=self.PERSPECTIVE_DEFAULT_GAMMA,
            min_value=self.PERSPECTIVE_GAMMA_MIN,
            max_value=self.PERSPECTIVE_GAMMA_MAX,
            step=0.05,
            description=pgettext(
                "Controller Widgets",
                "Gamma curve exponent for distance scaling.",
            ),
        )
        perspective_angle_bias_config = create_slider_config(
            key=self.ANGLE_BIAS_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Perspective Angle Bias (deg)"),
            value=self.PERSPECTIVE_DEFAULT_ANGLE_BIAS,
            min_value=self.PERSPECTIVE_ANGLE_BIAS_MIN,
            max_value=self.PERSPECTIVE_ANGLE_BIAS_MAX,
            step=0.1,
            description=pgettext(
                "Controller Widgets",
                "Small angle offset for fine-tuning.",
            ),
        )
        perspective_radius_scale_config = create_slider_config(
            key=self.RADIUS_SCALE_CONFIG_KEY,
            label=pgettext("Controller Widgets", "Perspective Radius Scale"),
            value=self.PERSPECTIVE_DEFAULT_RADIUS_SCALE,
            min_value=self.PERSPECTIVE_RADIUS_SCALE_MIN,
            max_value=self.PERSPECTIVE_RADIUS_SCALE_MAX,
            step=0.01,
            description=pgettext(
                "Controller Widgets",
                "Global multiplier applied to corrected distance.",
            ),
        )
        perspective_apply_cardinals_config = create_action_config(
            key=self.PERSPECTIVE_APPLY_CARDINALS_KEY,
            label=pgettext("Controller Widgets", "Apply Cardinal Calibration"),
            button_label=pgettext("Controller Widgets", "Apply"),
            description=pgettext(
                "Controller Widgets",
                "Compute ellipse parameters from N/S/W/E calibration points.",
            ),
        )
        perspective_mismatch_threshold_config = create_slider_config(
            key=self.PERSPECTIVE_MISMATCH_THRESHOLD_KEY,
            label=pgettext("Controller Widgets", "Perspective Mismatch Threshold (px)"),
            value=self.PERSPECTIVE_MISMATCH_THRESHOLD_DEFAULT,
            min_value=0.0,
            max_value=50.0,
            step=1,
            description=pgettext(
                "Controller Widgets",
                "Warn when left/right or up/down mismatch exceeds this threshold.",
            ),
        )
        perspective_cardinal_n_x = create_text_config(
            key=self.PERSPECTIVE_CARDINAL_N_X,
            label=pgettext("Controller Widgets", "Cardinal North X"),
            value="",
            description=pgettext(
                "Controller Widgets", "North boundary X coordinate at max range."
            ),
        )
        perspective_cardinal_n_y = create_text_config(
            key=self.PERSPECTIVE_CARDINAL_N_Y,
            label=pgettext("Controller Widgets", "Cardinal North Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "North boundary Y coordinate at max range."
            ),
        )
        perspective_cardinal_s_x = create_text_config(
            key=self.PERSPECTIVE_CARDINAL_S_X,
            label=pgettext("Controller Widgets", "Cardinal South X"),
            value="",
            description=pgettext(
                "Controller Widgets", "South boundary X coordinate at max range."
            ),
        )
        perspective_cardinal_s_y = create_text_config(
            key=self.PERSPECTIVE_CARDINAL_S_Y,
            label=pgettext("Controller Widgets", "Cardinal South Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "South boundary Y coordinate at max range."
            ),
        )
        perspective_cardinal_w_x = create_text_config(
            key=self.PERSPECTIVE_CARDINAL_W_X,
            label=pgettext("Controller Widgets", "Cardinal West X"),
            value="",
            description=pgettext(
                "Controller Widgets", "West boundary X coordinate at max range."
            ),
        )
        perspective_cardinal_w_y = create_text_config(
            key=self.PERSPECTIVE_CARDINAL_W_Y,
            label=pgettext("Controller Widgets", "Cardinal West Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "West boundary Y coordinate at max range."
            ),
        )
        perspective_cardinal_e_x = create_text_config(
            key=self.PERSPECTIVE_CARDINAL_E_X,
            label=pgettext("Controller Widgets", "Cardinal East X"),
            value="",
            description=pgettext(
                "Controller Widgets", "East boundary X coordinate at max range."
            ),
        )
        perspective_cardinal_e_y = create_text_config(
            key=self.PERSPECTIVE_CARDINAL_E_Y,
            label=pgettext("Controller Widgets", "Cardinal East Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "East boundary Y coordinate at max range."
            ),
        )
        perspective_diag_ne_x = create_text_config(
            key=self.PERSPECTIVE_DIAG_NE_X,
            label=pgettext("Controller Widgets", "Diagonal NE X"),
            value="",
            description=pgettext(
                "Controller Widgets", "Optional NE diagonal marker X coordinate."
            ),
        )
        perspective_diag_ne_y = create_text_config(
            key=self.PERSPECTIVE_DIAG_NE_Y,
            label=pgettext("Controller Widgets", "Diagonal NE Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "Optional NE diagonal marker Y coordinate."
            ),
        )
        perspective_diag_nw_x = create_text_config(
            key=self.PERSPECTIVE_DIAG_NW_X,
            label=pgettext("Controller Widgets", "Diagonal NW X"),
            value="",
            description=pgettext(
                "Controller Widgets", "Optional NW diagonal marker X coordinate."
            ),
        )
        perspective_diag_nw_y = create_text_config(
            key=self.PERSPECTIVE_DIAG_NW_Y,
            label=pgettext("Controller Widgets", "Diagonal NW Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "Optional NW diagonal marker Y coordinate."
            ),
        )
        perspective_diag_sw_x = create_text_config(
            key=self.PERSPECTIVE_DIAG_SW_X,
            label=pgettext("Controller Widgets", "Diagonal SW X"),
            value="",
            description=pgettext(
                "Controller Widgets", "Optional SW diagonal marker X coordinate."
            ),
        )
        perspective_diag_sw_y = create_text_config(
            key=self.PERSPECTIVE_DIAG_SW_Y,
            label=pgettext("Controller Widgets", "Diagonal SW Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "Optional SW diagonal marker Y coordinate."
            ),
        )
        perspective_diag_se_x = create_text_config(
            key=self.PERSPECTIVE_DIAG_SE_X,
            label=pgettext("Controller Widgets", "Diagonal SE X"),
            value="",
            description=pgettext(
                "Controller Widgets", "Optional SE diagonal marker X coordinate."
            ),
        )
        perspective_diag_se_y = create_text_config(
            key=self.PERSPECTIVE_DIAG_SE_Y,
            label=pgettext("Controller Widgets", "Diagonal SE Y"),
            value="",
            description=pgettext(
                "Controller Widgets", "Optional SE diagonal marker Y coordinate."
            ),
        )

        self.add_config_item(circle_radius_config)
        self.add_config_item(cast_timing_config)
        self.add_config_item(self.cancel_button_config)
        self.add_config_item(calibrate_center_config)
        self.add_config_item(reset_center_config)
        self.add_config_item(center_x_config)
        self.add_config_item(center_y_config)
        self.add_config_item(center_x_input_config)
        self.add_config_item(center_y_input_config)
        self.add_config_item(y_offset_config)
        self.add_config_item(apply_center_config)
        self.add_config_item(enable_perspective_config)
        self.add_config_item(perspective_radius_x_config)
        self.add_config_item(perspective_radius_y_config)
        self.add_config_item(perspective_dx_bias_config)
        self.add_config_item(perspective_dy_bias_config)
        self.add_config_item(perspective_deadzone_config)
        self.add_config_item(perspective_max_clamp_config)
        self.add_config_item(perspective_curve_mode_config)
        self.add_config_item(perspective_gamma_config)
        self.add_config_item(perspective_angle_bias_config)
        self.add_config_item(perspective_radius_scale_config)
        self.add_config_item(perspective_apply_cardinals_config)
        self.add_config_item(perspective_mismatch_threshold_config)
        self.add_config_item(perspective_cardinal_n_x)
        self.add_config_item(perspective_cardinal_n_y)
        self.add_config_item(perspective_cardinal_s_x)
        self.add_config_item(perspective_cardinal_s_y)
        self.add_config_item(perspective_cardinal_w_x)
        self.add_config_item(perspective_cardinal_w_y)
        self.add_config_item(perspective_cardinal_e_x)
        self.add_config_item(perspective_cardinal_e_y)
        self.add_config_item(perspective_diag_ne_x)
        self.add_config_item(perspective_diag_ne_y)
        self.add_config_item(perspective_diag_nw_x)
        self.add_config_item(perspective_diag_nw_y)
        self.add_config_item(perspective_diag_sw_x)
        self.add_config_item(perspective_diag_sw_y)
        self.add_config_item(perspective_diag_se_x)
        self.add_config_item(perspective_diag_se_y)

        self.add_config_change_callback("circle_radius", self._on_circle_radius_changed)
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
            self.Y_OFFSET_CONFIG_KEY, self._on_y_offset_changed
        )
        self.add_config_change_callback(
            self.PERSPECTIVE_APPLY_CARDINALS_KEY,
            self._on_apply_perspective_cardinals_clicked,
        )
        self.add_config_change_callback(
            self.ENABLE_PERSPECTIVE_CONFIG_KEY, self._on_perspective_setting_changed
        )
        self.add_config_change_callback(
            self.RADIUS_X_CONFIG_KEY, self._on_perspective_setting_changed
        )
        self.add_config_change_callback(
            self.RADIUS_Y_CONFIG_KEY, self._on_perspective_setting_changed
        )
        self.add_config_change_callback(
            self.DX_BIAS_CONFIG_KEY, self._on_perspective_setting_changed
        )
        self.add_config_change_callback(
            self.DY_BIAS_CONFIG_KEY, self._on_perspective_setting_changed
        )
        self.add_config_change_callback(
            self.DEADZONE_CONFIG_KEY, self._on_perspective_setting_changed
        )
        self.add_config_change_callback(
            self.MAX_RADIUS_CLAMP_CONFIG_KEY, self._on_perspective_setting_changed
        )
        self.add_config_change_callback(
            self.DISTANCE_CURVE_MODE_CONFIG_KEY, self._on_perspective_setting_changed
        )
        self.add_config_change_callback(
            self.GAMMA_CONFIG_KEY, self._on_perspective_setting_changed
        )
        self.add_config_change_callback(
            self.ANGLE_BIAS_CONFIG_KEY, self._on_perspective_setting_changed
        )
        self.add_config_change_callback(
            self.RADIUS_SCALE_CONFIG_KEY, self._on_perspective_setting_changed
        )
        self.add_config_change_callback(
            self.PERSPECTIVE_MISMATCH_THRESHOLD_KEY,
            self._on_perspective_setting_changed,
        )
        for key in (
            self.PERSPECTIVE_CARDINAL_N_X,
            self.PERSPECTIVE_CARDINAL_N_Y,
            self.PERSPECTIVE_CARDINAL_S_X,
            self.PERSPECTIVE_CARDINAL_S_Y,
            self.PERSPECTIVE_CARDINAL_W_X,
            self.PERSPECTIVE_CARDINAL_W_Y,
            self.PERSPECTIVE_CARDINAL_E_X,
            self.PERSPECTIVE_CARDINAL_E_Y,
            self.PERSPECTIVE_DIAG_NE_X,
            self.PERSPECTIVE_DIAG_NE_Y,
            self.PERSPECTIVE_DIAG_NW_X,
            self.PERSPECTIVE_DIAG_NW_Y,
            self.PERSPECTIVE_DIAG_SW_X,
            self.PERSPECTIVE_DIAG_SW_Y,
            self.PERSPECTIVE_DIAG_SE_X,
            self.PERSPECTIVE_DIAG_SE_Y,
        ):
            self.add_config_change_callback(
                key, self._on_perspective_setting_changed
            )

        self._sync_center_inputs()
        self.get_config_manager().connect(
            "confirmed",
            lambda *_args: (
                self._sync_center_inputs(),
                self._update_circle_if_selected(),
                self._emit_overlay_event("refresh"),
                self._update_perspective_diagnostics(),
            ),
        )

    def _on_circle_radius_changed(self, key: str, value: int, restoring:bool) -> None:
        """处理圆半径配置变更"""
        try:
            # self.circle_radius = int(value)
            # 如果当前选中状态，重新发送圆形绘制事件
            if self._radius_adjustment is not None and not self._radius_adjustment_updating:
                self._radius_adjustment_updating = True
                try:
                    self._radius_adjustment.set_value(float(value))
                finally:
                    self._radius_adjustment_updating = False
            self._update_circle_if_selected()
        except (ValueError, TypeError):
            pass

    def _on_y_offset_changed(self, key: str, value: str, restoring: bool) -> None:
        if restoring:
            return
        try:
            float(value)
        except (TypeError, ValueError):
            return
        self._update_circle_if_selected()
        self._emit_overlay_event("refresh")

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
                "Configure casting behavior and affine calibration.",
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

        radius_control = self._build_radius_control(config_manager)

        panel.append(
            build_section(
                pgettext("Controller Widgets", "Casting Behavior"),
                ["cast_timing", "enable_cancel_button"],
                description=pgettext(
                    "Controller Widgets",
                    "Adjust how the skill is cast and whether a cancel button is shown.",
                ),
                expanded=True,
                extra_widgets=[radius_control],
            )
        )

        status_label = Gtk.Label(label="", xalign=0)
        status_label.set_wrap(True)
        self._calibration_status_label = status_label
        self._update_calibration_status_label()
        self._update_calibration_button_label()

        panel.append(
            build_section(
                pgettext("Controller Widgets", "Anchor Calibration"),
                [
                    self.CALIBRATE_CENTER_CONFIG_KEY,
                    self.RESET_CENTER_CONFIG_KEY,
                    self.CENTER_X_INPUT_CONFIG_KEY,
                    self.CENTER_Y_INPUT_CONFIG_KEY,
                    self.Y_OFFSET_CONFIG_KEY,
                    self.APPLY_CENTER_CONFIG_KEY,
                ],
                description=pgettext(
                    "Controller Widgets",
                    "Calibrate the anchor center by clicking on screen, or enter pixel coordinates manually.",
                ),
                expanded=True,
                extra_widgets=[status_label],
            )
        )

        perspective_status = Gtk.Label(label="", xalign=0)
        perspective_status.set_wrap(True)
        self._perspective_diagnostics_label = perspective_status
        self._update_perspective_diagnostics()

        panel.append(
            build_section(
                pgettext("Controller Widgets", "Perspective Correction"),
                [
                    self.ENABLE_PERSPECTIVE_CONFIG_KEY,
                    self.RADIUS_X_CONFIG_KEY,
                    self.RADIUS_Y_CONFIG_KEY,
                    self.DX_BIAS_CONFIG_KEY,
                    self.DY_BIAS_CONFIG_KEY,
                    self.DEADZONE_CONFIG_KEY,
                    self.MAX_RADIUS_CLAMP_CONFIG_KEY,
                    self.DISTANCE_CURVE_MODE_CONFIG_KEY,
                    self.GAMMA_CONFIG_KEY,
                    self.ANGLE_BIAS_CONFIG_KEY,
                    self.RADIUS_SCALE_CONFIG_KEY,
                    self.PERSPECTIVE_MISMATCH_THRESHOLD_KEY,
                    self.PERSPECTIVE_CARDINAL_N_X,
                    self.PERSPECTIVE_CARDINAL_N_Y,
                    self.PERSPECTIVE_CARDINAL_S_X,
                    self.PERSPECTIVE_CARDINAL_S_Y,
                    self.PERSPECTIVE_CARDINAL_W_X,
                    self.PERSPECTIVE_CARDINAL_W_Y,
                    self.PERSPECTIVE_CARDINAL_E_X,
                    self.PERSPECTIVE_CARDINAL_E_Y,
                    self.PERSPECTIVE_DIAG_NE_X,
                    self.PERSPECTIVE_DIAG_NE_Y,
                    self.PERSPECTIVE_DIAG_NW_X,
                    self.PERSPECTIVE_DIAG_NW_Y,
                    self.PERSPECTIVE_DIAG_SW_X,
                    self.PERSPECTIVE_DIAG_SW_Y,
                    self.PERSPECTIVE_DIAG_SE_X,
                    self.PERSPECTIVE_DIAG_SE_Y,
                    self.PERSPECTIVE_APPLY_CARDINALS_KEY,
                ],
                description=pgettext(
                    "Controller Widgets",
                    "Calibrate ellipse radii/bias from cardinal points and apply "
                    "perspective-corrected angle + distance mapping.",
                ),
                expanded=False,
                extra_widgets=[perspective_status],
            )
        )

        return panel

    def _on_calibrate_center_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._set_calibration_mode(not self._center_calibration_active)

    def _on_reset_center_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        self._set_calibration_mode(False)
        self.set_config_value(self.CENTER_X_CONFIG_KEY, "")
        self.set_config_value(self.CENTER_Y_CONFIG_KEY, "")
        self._sync_center_inputs()
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

    def _on_apply_perspective_cardinals_clicked(
        self, key: str, value: bool, restoring: bool
    ) -> None:
        if restoring:
            return
        cardinals = self._get_cardinal_points()
        if cardinals is None:
            return
        center = self._get_window_center()
        north, south, west, east = cardinals
        model = PerspectiveEllipseModel.from_cardinals(
            center=center,
            north=north,
            south=south,
            west=west,
            east=east,
            deadzone=self._get_float_config(
                self.DEADZONE_CONFIG_KEY, self.PERSPECTIVE_DEFAULT_DEADZONE
            ),
            max_radius_clamp=self._get_float_config(
                self.MAX_RADIUS_CLAMP_CONFIG_KEY, self.PERSPECTIVE_DEFAULT_MAX_CLAMP
            ),
            distance_curve_mode=self._get_str_config(
                self.DISTANCE_CURVE_MODE_CONFIG_KEY, "linear"
            ),
            gamma=self._get_float_config(
                self.GAMMA_CONFIG_KEY, self.PERSPECTIVE_DEFAULT_GAMMA
            ),
            angle_bias_deg=self._get_float_config(
                self.ANGLE_BIAS_CONFIG_KEY, self.PERSPECTIVE_DEFAULT_ANGLE_BIAS
            ),
            radius_scale=self._get_float_config(
                self.RADIUS_SCALE_CONFIG_KEY, self.PERSPECTIVE_DEFAULT_RADIUS_SCALE
            ),
        )
        if not model.is_valid():
            return
        self.set_config_value(self.RADIUS_X_CONFIG_KEY, model.radius_x)
        self.set_config_value(self.RADIUS_Y_CONFIG_KEY, model.radius_y)
        self.set_config_value(self.DX_BIAS_CONFIG_KEY, model.dx_bias)
        self.set_config_value(self.DY_BIAS_CONFIG_KEY, model.dy_bias)
        self._update_circle_if_selected()
        self._emit_overlay_event("refresh")
        self._update_perspective_diagnostics()

    def _on_perspective_setting_changed(
        self, key: str, value: object, restoring: bool
    ) -> None:
        if restoring:
            return
        self._update_circle_if_selected()
        self._emit_overlay_event("refresh")
        self._update_perspective_diagnostics()

    def _on_mask_clicked(self, event: Event[dict[str, int]]) -> None:
        data = event.data or {}
        x = data.get("x")
        y = data.get("y")
        if x is None or y is None:
            return
        self._apply_calibration_click(float(x), float(y))

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

    def _set_calibration_mode(self, active: bool) -> None:
        self._center_calibration_active = active
        self._update_calibration_button_label()
        self._update_calibration_status_label()
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
        return self._center_calibration_active

    def cancel_calibration(self) -> None:
        if not self._center_calibration_active:
            return
        self._set_calibration_mode(False)

    def is_center_overlay_enabled(self) -> bool:
        return False

    def should_hide_settings_panel_on_calibration(self) -> bool:
        return False

    def handle_calibration_click(self, x: float, y: float, button: int) -> bool:
        if not self._center_calibration_active:
            return False
        if button != Gdk.BUTTON_PRIMARY:
            return False
        return self._apply_calibration_click(x, y)

    def _apply_calibration_click(self, x: float, y: float) -> bool:
        if not self._center_calibration_active:
            return False
        w, h = self._get_window_size()
        if x < 0 or y < 0 or x >= w or y >= h:
            return False
        self.set_config_value(self.CENTER_X_CONFIG_KEY, float(x))
        self.set_config_value(self.CENTER_Y_CONFIG_KEY, float(y))
        self._sync_center_inputs()
        self._set_calibration_mode(False)
        self._emit_overlay_event("refresh")
        return True

    def _get_float_config(self, key: str, default: float) -> float:
        raw_value = self.get_config_value(key)
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return default

    def _get_str_config(self, key: str, default: str) -> str:
        raw_value = self.get_config_value(key)
        if raw_value is None:
            return default
        return str(raw_value)

    def _get_point_config(self, key_x: str, key_y: str) -> tuple[float, float] | None:
        raw_x = self.get_config_value(key_x)
        raw_y = self.get_config_value(key_y)
        if raw_x in (None, "") or raw_y in (None, ""):
            return None
        try:
            x = float(raw_x)
            y = float(raw_y)
        except (TypeError, ValueError):
            return None
        return (x, y)

    def _get_cardinal_points(
        self,
    ) -> tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ] | None:
        north = self._get_point_config(
            self.PERSPECTIVE_CARDINAL_N_X, self.PERSPECTIVE_CARDINAL_N_Y
        )
        south = self._get_point_config(
            self.PERSPECTIVE_CARDINAL_S_X, self.PERSPECTIVE_CARDINAL_S_Y
        )
        west = self._get_point_config(
            self.PERSPECTIVE_CARDINAL_W_X, self.PERSPECTIVE_CARDINAL_W_Y
        )
        east = self._get_point_config(
            self.PERSPECTIVE_CARDINAL_E_X, self.PERSPECTIVE_CARDINAL_E_Y
        )
        if None in (north, south, west, east):
            return None
        return north, south, west, east

    def _get_perspective_model(
        self, allow_disabled: bool = False
    ) -> PerspectiveEllipseModel | None:
        enabled = bool(self.get_config_value(self.ENABLE_PERSPECTIVE_CONFIG_KEY))
        if not enabled and not allow_disabled:
            return None
        center_x, center_y = self._get_window_center()
        radius_x = self._get_float_config(
            self.RADIUS_X_CONFIG_KEY, self.PERSPECTIVE_DEFAULT_RADIUS_X
        )
        radius_y = self._get_float_config(
            self.RADIUS_Y_CONFIG_KEY, self.PERSPECTIVE_DEFAULT_RADIUS_Y
        )
        dx_bias = self._get_float_config(self.DX_BIAS_CONFIG_KEY, 0.0)
        dy_bias = self._get_float_config(self.DY_BIAS_CONFIG_KEY, 0.0)
        deadzone = self._get_float_config(
            self.DEADZONE_CONFIG_KEY, self.PERSPECTIVE_DEFAULT_DEADZONE
        )
        max_radius_clamp = self._get_float_config(
            self.MAX_RADIUS_CLAMP_CONFIG_KEY, self.PERSPECTIVE_DEFAULT_MAX_CLAMP
        )
        distance_curve_mode = self._get_str_config(
            self.DISTANCE_CURVE_MODE_CONFIG_KEY, "linear"
        )
        gamma = self._get_float_config(
            self.GAMMA_CONFIG_KEY, self.PERSPECTIVE_DEFAULT_GAMMA
        )
        angle_bias_deg = self._get_float_config(
            self.ANGLE_BIAS_CONFIG_KEY, self.PERSPECTIVE_DEFAULT_ANGLE_BIAS
        )
        radius_scale = self._get_float_config(
            self.RADIUS_SCALE_CONFIG_KEY, self.PERSPECTIVE_DEFAULT_RADIUS_SCALE
        )
        model = PerspectiveEllipseModel(
            center_x=center_x,
            center_y=center_y,
            radius_x=radius_x,
            radius_y=radius_y,
            dx_bias=dx_bias,
            dy_bias=dy_bias,
            deadzone=deadzone,
            max_radius_clamp=max_radius_clamp,
            distance_curve_mode=distance_curve_mode,
            gamma=gamma,
            angle_bias_deg=angle_bias_deg,
            radius_scale=radius_scale,
        )
        if not model.is_valid():
            return None
        return model

    def _update_perspective_diagnostics(self) -> None:
        if self._perspective_diagnostics_label is None:
            return
        model = self._get_perspective_model(allow_disabled=True)
        center = self._get_window_center()
        lines: list[str] = []
        lines.append(
            pgettext(
                "Controller Widgets",
                "Anchor Center: ({x:.1f}, {y:.1f})",
            ).format(x=center[0], y=center[1])
        )
        cardinals = self._get_cardinal_points()
        if cardinals is None:
            lines.append(
                pgettext(
                    "Controller Widgets",
                    "Cardinal points: incomplete.",
                )
            )
        else:
            north, south, west, east = cardinals
            lines.append(
                pgettext(
                    "Controller Widgets",
                    "N: ({x:.1f}, {y:.1f})  S: ({sx:.1f}, {sy:.1f})",
                ).format(x=north[0], y=north[1], sx=south[0], sy=south[1])
            )
            lines.append(
                pgettext(
                    "Controller Widgets",
                    "W: ({x:.1f}, {y:.1f})  E: ({ex:.1f}, {ey:.1f})",
                ).format(x=west[0], y=west[1], ex=east[0], ey=east[1])
            )
        enabled = bool(self.get_config_value(self.ENABLE_PERSPECTIVE_CONFIG_KEY))
        if model is None:
            lines.append(
                pgettext(
                    "Controller Widgets",
                    "Perspective parameters: invalid.",
                )
            )
            self._perspective_diagnostics_label.set_label("\n".join(lines))
            return
        lines.append(
            pgettext(
                "Controller Widgets",
                "Perspective enabled: {enabled}",
            ).format(enabled="yes" if enabled else "no")
        )
        ccx, ccy = model.corrected_center
        scale_ratio = model.radius_y / model.radius_x if model.radius_x else 0.0
        lines.append(
            pgettext(
                "Controller Widgets",
                "r_x={rx:.1f}, r_y={ry:.1f}, dx_bias={dx:.1f}, dy_bias={dy:.1f}",
            ).format(
                rx=model.radius_x,
                ry=model.radius_y,
                dx=model.dx_bias,
                dy=model.dy_bias,
            )
        )
        lines.append(
            pgettext(
                "Controller Widgets",
                "Corrected Center: ({x:.1f}, {y:.1f}), scale ratio={s:.4f}",
            ).format(x=ccx, y=ccy, s=scale_ratio)
        )

        threshold = self._get_float_config(
            self.PERSPECTIVE_MISMATCH_THRESHOLD_KEY,
            self.PERSPECTIVE_MISMATCH_THRESHOLD_DEFAULT,
        )
        if cardinals is not None:
            north, south, west, east = cardinals
            lr_mismatch = abs((east[0] - center[0]) - (center[0] - west[0]))
            ud_mismatch = abs((center[1] - north[1]) - (south[1] - center[1]))
            if lr_mismatch > threshold or ud_mismatch > threshold:
                lines.append(
                    pgettext(
                        "Controller Widgets",
                        "Mismatch warning: L/R={lr:.1f}px, U/D={ud:.1f}px",
                    ).format(lr=lr_mismatch, ud=ud_mismatch)
                )
        diag_points = [
            (self.PERSPECTIVE_DIAG_NE_X, self.PERSPECTIVE_DIAG_NE_Y, 45.0, "NE"),
            (self.PERSPECTIVE_DIAG_NW_X, self.PERSPECTIVE_DIAG_NW_Y, 135.0, "NW"),
            (self.PERSPECTIVE_DIAG_SW_X, self.PERSPECTIVE_DIAG_SW_Y, -135.0, "SW"),
            (self.PERSPECTIVE_DIAG_SE_X, self.PERSPECTIVE_DIAG_SE_Y, -45.0, "SE"),
        ]
        for key_x, key_y, expected_deg, label in diag_points:
            point = self._get_point_config(key_x, key_y)
            if point is None:
                continue
            _, _, _, angle_rad = model.normalize_point(point[0], point[1])
            angle_deg = math.degrees(angle_rad)
            error = angle_deg - expected_deg
            lines.append(
                pgettext(
                    "Controller Widgets",
                    "{label} angle={angle:.1f}° (Δ {error:.1f}°)",
                ).format(label=label, angle=angle_deg, error=error)
            )

        self._perspective_diagnostics_label.set_label("\n".join(lines))

    def _update_calibration_button_label(self) -> None:
        manager = self.get_config_manager()
        widget = manager.ui_widgets.get(self.CALIBRATE_CENTER_CONFIG_KEY)
        if not isinstance(widget, Gtk.Box):
            return
        button = widget.get_last_child()
        if not isinstance(button, Gtk.Button):
            return
        label = (
            pgettext("Controller Widgets", "Cancel")
            if self._center_calibration_active
            else pgettext("Controller Widgets", "Calibrate")
        )
        button.set_label(label)

    def _update_calibration_status_label(self) -> None:
        if self._calibration_status_label is None:
            return
        if self._center_calibration_active:
            self._calibration_status_label.set_label(
                pgettext(
                    "Controller Widgets",
                    "Click on the screen to set the anchor center, or press Esc to cancel.",
                )
            )
        else:
            self._calibration_status_label.set_label("")

    def _build_radius_control(self, config_manager) -> Gtk.Widget:
        config = config_manager.get_config("circle_radius")
        min_value = 1
        max_value = 10000
        current_value = 200
        if config is not None:
            min_value = getattr(config, "min_value", min_value)
            max_value = getattr(config, "max_value", max_value)
            current_value = config.value if config.value is not None else current_value

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        label = Gtk.Label(label=pgettext("Controller Widgets", "Casting Radius"), xalign=0)
        if config is not None:
            label.set_tooltip_text(config.description)
        box.append(label)

        adjustment = Gtk.Adjustment(
            value=float(current_value),
            lower=float(min_value),
            upper=float(max_value),
            step_increment=1.0,
            page_increment=10.0,
        )
        self._radius_adjustment = adjustment

        spin = Gtk.SpinButton()
        spin.set_adjustment(adjustment)
        spin.set_digits(0)
        spin.set_numeric(True)
        spin.set_width_chars(6)
        spin.set_increments(1, 10)

        def on_radius_changed(_adjustment):
            if self._radius_adjustment_updating:
                return
            value = int(round(adjustment.get_value()))
            value = max(int(min_value), min(int(max_value), value))
            self._radius_adjustment_updating = True
            try:
                adjustment.set_value(value)
            finally:
                self._radius_adjustment_updating = False
            self.set_config_value("circle_radius", value)

        adjustment.connect("value-changed", on_radius_changed)

        box.append(spin)
        box.set_visible(True)
        return box

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

    def _update_circle_if_selected(self):
        """如果当前组件被选中，更新圆形绘制"""
        if self.is_selected and not self.mapping_mode:
            calibration = self._get_v2_calibration()
            perspective_model = self._get_perspective_model()
            circle_data = {
                "widget_id": id(self),
                "widget_type": "skill_casting",
                "circle_radius": calibration.radius,
                "center": (calibration.center_x, calibration.center_y),
                "anchor_center": (calibration.center_x, calibration.center_y),
                "vertical_scale_ratio": calibration.vertical_scale_ratio,
                "y_offset": calibration.y_offset,
                "action": "show",
            }
            if perspective_model is not None:
                circle_data.update(
                    {
                        "ellipse_radius_x": perspective_model.radius_x,
                        "ellipse_radius_y": perspective_model.radius_y,
                        "ellipse_dx_bias": perspective_model.dx_bias,
                        "ellipse_dy_bias": perspective_model.dy_bias,
                        "ellipse_center": perspective_model.corrected_center,
                    }
                )
        else:
            circle_data = {
                "widget_id": id(self),
                "widget_type": "skill_casting",
                "action": "hide",
            }
        self.event_bus.emit(Event(EventType.WIDGET_SELECTION_OVERLAY, self, circle_data))

    def _on_selection_changed(self, widget, pspec):
        """当选中状态变化时的回调"""
        self._update_circle_if_selected()

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

    def _get_v2_calibration(self) -> SkillCastingCalibration:
        center_x, center_y = self._get_window_center()
        outer_radius = self.get_config_value("circle_radius")
        if not isinstance(outer_radius, (int, float)) or outer_radius <= 0:
            outer_radius = 200
        raw_y_offset = self.get_config_value(self.Y_OFFSET_CONFIG_KEY)
        try:
            y_offset = float(raw_y_offset)
        except (TypeError, ValueError):
            y_offset = 0.0
        return SkillCastingCalibration(
            center_x=center_x,
            center_y=center_y,
            radius=float(outer_radius),
            vertical_scale_ratio=self.VERTICAL_SCALE_RATIO,
            y_offset=y_offset,
        )

    def _map_circle_to_circle(
        self, mouse_x: float, mouse_y: float
    ) -> tuple[float, float]:
        """
        将鼠标在圆形范围内的坐标映射到虚拟摇杆圆形范围内的坐标

        外圆：窗口中心为圆心，半径按百分比缩放
        内圆：widget中心为圆心，宽度/2为半径
        """
        widget_center_x = self.center_x
        widget_center_y = self.center_y
        widget_radius = self.width / 2
        perspective_model = self._get_perspective_model()
        if perspective_model is not None:
            angle, distance = perspective_model.point_to_angle_distance(mouse_x, mouse_y)
            target_x = widget_center_x + math.cos(angle) * distance * widget_radius
            target_y = widget_center_y + math.sin(angle) * distance * widget_radius
            return (target_x, target_y)

        calibration = self._get_v2_calibration()

        return map_pointer_to_widget_target(
            mouse_x,
            mouse_y,
            calibration,
            widget_center_x,
            widget_center_y,
            widget_radius,
        )

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

    def set_mapping_mode(self, mapping_mode: bool) -> None:
        super().set_mapping_mode(mapping_mode)
        self._update_circle_if_selected()
