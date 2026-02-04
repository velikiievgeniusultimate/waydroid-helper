#!/usr/bin/env python3
"""Minimal Skill Casting geometry helpers."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from waydroid_helper.util.log import logger


@dataclass(frozen=True)
class SkillCastingCalibration:
    center_x: float
    center_y: float
    radius: float
    vertical_scale_ratio: float = 0.745
    y_offset: float = 0.0

    @property
    def math_center_y(self) -> float:
        return self.center_y + self.y_offset


def map_pointer_to_widget_target(
    mouse_x: float,
    mouse_y: float,
    calibration: SkillCastingCalibration,
    widget_center_x: float,
    widget_center_y: float,
    widget_radius: float,
) -> tuple[float, float]:
    if not math.isfinite(calibration.radius) or calibration.radius <= 0:
        return (widget_center_x, widget_center_y)

    dx = mouse_x - calibration.center_x
    dy = mouse_y - calibration.math_center_y

    if calibration.vertical_scale_ratio == 0:
        return (widget_center_x, widget_center_y)

    dy_corr = dy / calibration.vertical_scale_ratio
    r_corr = math.hypot(dx, dy_corr)
    angle = math.atan2(dy_corr, dx)

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "SkillCasting v2 mapping: angle=%.4f r_corr=%.2f", angle, r_corr
        )

    if r_corr == 0:
        return (widget_center_x, widget_center_y)

    unit_x = dx / r_corr
    unit_y = dy_corr / r_corr
    ratio = min(r_corr / calibration.radius, 1.0)

    target_x = widget_center_x + unit_x * ratio * widget_radius
    target_y = widget_center_y + unit_y * ratio * widget_radius

    return (target_x, target_y)


def clamp_visual_point(
    mouse_x: float,
    mouse_y: float,
    calibration: SkillCastingCalibration,
) -> tuple[float, float] | None:
    if not math.isfinite(calibration.radius) or calibration.radius <= 0:
        return None

    dx = mouse_x - calibration.center_x
    dy = mouse_y - calibration.math_center_y

    if calibration.vertical_scale_ratio == 0:
        return None

    dy_corr = dy / calibration.vertical_scale_ratio
    r_corr = math.hypot(dx, dy_corr)
    if r_corr == 0:
        return None

    scale = min(calibration.radius / r_corr, 1.0)
    dx_scaled = dx * scale
    dy_corr_scaled = dy_corr * scale

    x_vis = calibration.center_x + dx_scaled
    y_vis = (
        calibration.math_center_y
        + (dy_corr_scaled * calibration.vertical_scale_ratio)
    )

    return (x_vis, y_vis)
