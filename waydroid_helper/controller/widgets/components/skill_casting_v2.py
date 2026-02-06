#!/usr/bin/env python3
"""Skill Casting geometry helpers.

The in-game skill range is rendered as an ellipse on screen, while the joystick
widget itself remains a perfect circle.  Two models are supported:

1) A legacy ray-ellipse mapper that projects from the character anchor to the
   ellipse border.
2) A perspective ellipse model that normalizes screen points into a unit circle
   space so angles remain stable under camera tilt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class SkillCastingCalibration:
    """Geometry parameters for converting map-space cursor to joystick-space."""

    # Character/anchor center (must not be replaced with widget center).
    center_x: float
    center_y: float
    # Ellipse horizontal radius in screen pixels.
    radius: float
    # Ellipse vertical radius ratio relative to horizontal radius.
    vertical_scale_ratio: float = 0.745
    # Ellipse-center Y offset relative to character center.
    y_offset: float = 0.0

    @property
    def ellipse_center_y(self) -> float:
        return self.center_y + self.y_offset

    @property
    def ellipse_vertical_radius(self) -> float:
        return self.radius * self.vertical_scale_ratio


@dataclass(frozen=True)
class PerspectiveEllipseModel:
    """Projective-like correction model for skill casting."""

    center_x: float
    center_y: float
    radius_x: float
    radius_y: float
    dx_bias: float = 0.0
    dy_bias: float = 0.0

    @classmethod
    def from_cardinals(
        cls,
        center: tuple[float, float],
        north: tuple[float, float],
        south: tuple[float, float],
        west: tuple[float, float],
        east: tuple[float, float],
    ) -> "PerspectiveEllipseModel":
        cx, cy = center
        nx, ny = north
        sx, sy = south
        wx, _wy = west
        ex, _ey = east

        radius_x = (ex - wx) / 2.0
        radius_y = (sy - ny) / 2.0
        dx_bias = ((ex + wx) / 2.0) - cx
        dy_bias = ((sy + ny) / 2.0) - cy
        return cls(
            center_x=cx,
            center_y=cy,
            radius_x=radius_x,
            radius_y=radius_y,
            dx_bias=dx_bias,
            dy_bias=dy_bias,
        )

    @property
    def corrected_center(self) -> tuple[float, float]:
        return (self.center_x + self.dx_bias, self.center_y + self.dy_bias)

    def normalize_point(
        self, px: float, py: float
    ) -> tuple[float, float, float, float] | None:
        if self.radius_x <= 0 or self.radius_y <= 0:
            return None
        ccx, ccy = self.corrected_center
        u = (px - ccx) / self.radius_x
        v = (py - ccy) / self.radius_y
        raw_radius = math.hypot(u, v)
        raw_angle = math.atan2(v, u)
        return (u, v, raw_radius, raw_angle)

    def point_to_angle_distance(
        self, px: float, py: float
    ) -> tuple[float, float] | None:
        normalized = self.normalize_point(px, py)
        if normalized is None:
            return None
        _u, _v, raw_radius, raw_angle = normalized
        return (raw_angle, raw_radius)

    def angle_distance_to_point(
        self, angle_rad: float, distance_norm: float
    ) -> tuple[float, float] | None:
        if self.radius_x <= 0 or self.radius_y <= 0:
            return None
        ccx, ccy = self.corrected_center
        x = ccx + self.radius_x * distance_norm * math.cos(angle_rad)
        y = ccy + self.radius_y * distance_norm * math.sin(angle_rad)
        return (x, y)


def _ray_ellipse_intersection_distance(
    dir_x: float,
    dir_y: float,
    calibration: SkillCastingCalibration,
) -> float | None:
    """Return distance from character center to ellipse border along a ray."""
    a = calibration.radius
    b = calibration.ellipse_vertical_radius
    if a <= 0 or b <= 0:
        return None

    # Ray origin is character center C, ellipse center is E.
    ox = calibration.center_x - calibration.center_x
    oy = calibration.center_y - calibration.ellipse_center_y

    inv_a2 = 1.0 / (a * a)
    inv_b2 = 1.0 / (b * b)

    qa = (dir_x * dir_x) * inv_a2 + (dir_y * dir_y) * inv_b2
    qb = 2.0 * ((ox * dir_x) * inv_a2 + (oy * dir_y) * inv_b2)
    qc = (ox * ox) * inv_a2 + (oy * oy) * inv_b2 - 1.0
    if qa <= 0:
        return None

    discriminant = qb * qb - 4.0 * qa * qc
    if discriminant < 0:
        return None

    sqrt_disc = math.sqrt(discriminant)
    t1 = (-qb - sqrt_disc) / (2.0 * qa)
    t2 = (-qb + sqrt_disc) / (2.0 * qa)
    positive_hits = [t for t in (t1, t2) if t > 0]
    if not positive_hits:
        return None
    return max(positive_hits)


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

    # Direction must be measured from character center, not from ellipse center.
    dx = mouse_x - calibration.center_x
    dy = mouse_y - calibration.center_y
    pointer_distance = math.hypot(dx, dy)
    if pointer_distance == 0:
        return (widget_center_x, widget_center_y)

    unit_x = dx / pointer_distance
    unit_y = dy / pointer_distance
    max_distance = _ray_ellipse_intersection_distance(unit_x, unit_y, calibration)
    if max_distance is None or max_distance <= 0:
        return (widget_center_x, widget_center_y)

    ratio = min(pointer_distance / max_distance, 1.0)

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
    dy = mouse_y - calibration.center_y
    pointer_distance = math.hypot(dx, dy)
    if pointer_distance == 0:
        return None

    unit_x = dx / pointer_distance
    unit_y = dy / pointer_distance
    max_distance = _ray_ellipse_intersection_distance(unit_x, unit_y, calibration)
    if max_distance is None or max_distance <= 0:
        return None

    scale = min(pointer_distance, max_distance)
    dx_scaled = unit_x * scale
    dy_scaled = unit_y * scale

    x_vis = calibration.center_x + dx_scaled
    y_vis = calibration.center_y + dy_scaled

    return (x_vis, y_vis)
