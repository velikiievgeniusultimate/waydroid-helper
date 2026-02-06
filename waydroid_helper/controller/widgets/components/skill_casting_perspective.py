#!/usr/bin/env python3
"""Perspective ellipse correction helpers for skill casting."""

from __future__ import annotations

import math
from dataclasses import dataclass


DEFAULT_DISTANCE_CURVE = "linear"


@dataclass(frozen=True)
class PerspectiveEllipseModel:
    """Analytic ellipse correction model for skill casting."""

    center_x: float
    center_y: float
    radius_x: float
    radius_y: float
    dx_bias: float = 0.0
    dy_bias: float = 0.0
    deadzone: float = 0.0
    max_radius_clamp: float = 1.0
    distance_curve_mode: str = DEFAULT_DISTANCE_CURVE
    gamma: float = 1.0
    angle_bias_deg: float = 0.0
    radius_scale: float = 1.0

    @property
    def corrected_center(self) -> tuple[float, float]:
        return (self.center_x + self.dx_bias, self.center_y + self.dy_bias)

    @property
    def angle_bias_rad(self) -> float:
        return math.radians(self.angle_bias_deg)

    @classmethod
    def from_cardinals(
        cls,
        center: tuple[float, float],
        north: tuple[float, float],
        south: tuple[float, float],
        west: tuple[float, float],
        east: tuple[float, float],
    ) -> "PerspectiveEllipseModel":
        center_x, center_y = center
        radius_x = (east[0] - west[0]) / 2.0
        radius_y = (south[1] - north[1]) / 2.0
        dx_bias = ((east[0] + west[0]) / 2.0) - center_x
        dy_bias = ((south[1] + north[1]) / 2.0) - center_y
        return cls(
            center_x=center_x,
            center_y=center_y,
            radius_x=radius_x,
            radius_y=radius_y,
            dx_bias=dx_bias,
            dy_bias=dy_bias,
        )

    def normalize_point(self, px: float, py: float) -> tuple[float, float, float, float]:
        if self.radius_x == 0 or self.radius_y == 0:
            return (0.0, 0.0, 0.0, 0.0)
        ccx, ccy = self.corrected_center
        u = (px - ccx) / self.radius_x
        v = (py - ccy) / self.radius_y
        raw_radius = math.hypot(u, v)
        raw_angle = math.atan2(v, u)
        return (u, v, raw_radius, raw_angle)

    def point_to_angle_distance(self, px: float, py: float) -> tuple[float, float]:
        _, _, raw_radius, raw_angle = self.normalize_point(px, py)
        angle = raw_angle + self.angle_bias_rad
        distance = self._apply_distance_curve(raw_radius)
        return (angle, distance)

    def angle_distance_to_point(
        self, angle_rad: float, distance_norm: float
    ) -> tuple[float, float]:
        radius = self._invert_distance_curve(distance_norm)
        ccx, ccy = self.corrected_center
        angle = angle_rad - self.angle_bias_rad
        x = ccx + self.radius_x * radius * math.cos(angle)
        y = ccy + self.radius_y * radius * math.sin(angle)
        return (x, y)

    def _apply_distance_curve(self, raw_radius: float) -> float:
        if not math.isfinite(raw_radius):
            return 0.0
        if raw_radius < self.deadzone:
            return 0.0
        max_radius = self.max_radius_clamp if self.max_radius_clamp > 0 else 1.0
        clamped = min(raw_radius, max_radius)
        if clamped <= 1.0:
            distance = self._curve(clamped)
        else:
            distance = clamped
        distance *= self.radius_scale
        return min(distance, max_radius)

    def _invert_distance_curve(self, distance_norm: float) -> float:
        if not math.isfinite(distance_norm):
            return 0.0
        max_radius = self.max_radius_clamp if self.max_radius_clamp > 0 else 1.0
        distance = distance_norm
        if self.radius_scale != 0:
            distance = distance_norm / self.radius_scale
        distance = max(0.0, distance)
        if distance > 1.0:
            return min(distance, max_radius)
        mode = self.distance_curve_mode or DEFAULT_DISTANCE_CURVE
        if mode == "gamma":
            gamma = self.gamma if self.gamma > 0 else 1.0
            return distance ** (1.0 / gamma)
        if mode == "smoothstep":
            return _inverse_smoothstep(distance)
        return distance

    def _curve(self, value: float) -> float:
        mode = self.distance_curve_mode or DEFAULT_DISTANCE_CURVE
        if mode == "gamma":
            gamma = self.gamma if self.gamma > 0 else 1.0
            return value ** gamma
        if mode == "smoothstep":
            return value * value * (3.0 - 2.0 * value)
        return value


def _inverse_smoothstep(value: float, iterations: int = 16) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    low = 0.0
    high = 1.0
    for _ in range(iterations):
        mid = (low + high) / 2.0
        test = mid * mid * (3.0 - 2.0 * mid)
        if test < value:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0
