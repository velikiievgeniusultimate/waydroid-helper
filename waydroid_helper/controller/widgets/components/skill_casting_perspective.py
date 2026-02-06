#!/usr/bin/env python3
"""Perspective ellipse correction helpers for skill casting."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PerspectiveEllipseModel:
    """Analytic model for mapping screen points onto a corrected circle."""

    center_x: float
    center_y: float
    radius_x: float
    radius_y: float
    dx_bias: float = 0.0
    dy_bias: float = 0.0
    deadzone: float = 0.0
    max_radius_clamp: float = 1.0
    distance_curve_mode: str = "linear"
    gamma: float = 1.0
    angle_bias_deg: float = 0.0
    radius_scale: float = 1.0

    @property
    def corrected_center(self) -> tuple[float, float]:
        return (self.center_x + self.dx_bias, self.center_y + self.dy_bias)

    @property
    def angle_bias_rad(self) -> float:
        return math.radians(self.angle_bias_deg)

    def is_valid(self) -> bool:
        return self.radius_x > 0 and self.radius_y > 0

    @classmethod
    def from_cardinals(
        cls,
        center: tuple[float, float],
        north: tuple[float, float],
        south: tuple[float, float],
        west: tuple[float, float],
        east: tuple[float, float],
        **kwargs,
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
            **kwargs,
        )

    def normalize_point(
        self, px: float, py: float
    ) -> tuple[float, float, float, float]:
        ccx, ccy = self.corrected_center
        u = (px - ccx) / self.radius_x
        v = (py - ccy) / self.radius_y
        raw_radius = math.hypot(u, v)
        raw_angle = math.atan2(v, u) + self.angle_bias_rad
        return u, v, raw_radius, raw_angle

    def point_to_angle_distance(self, px: float, py: float) -> tuple[float, float]:
        _, _, raw_radius, raw_angle = self.normalize_point(px, py)
        if raw_radius <= self.deadzone:
            return raw_angle, 0.0

        clamped_radius = min(raw_radius, self.max_radius_clamp)
        if clamped_radius <= 1.0:
            curved = self._apply_distance_curve(clamped_radius)
        else:
            curved = clamped_radius

        curved *= self.radius_scale
        curved = max(0.0, min(curved, self.max_radius_clamp))
        return raw_angle, curved

    def angle_distance_to_point(
        self, angle_rad: float, distance_norm: float
    ) -> tuple[float, float]:
        distance_norm = max(0.0, distance_norm)
        if self.radius_scale > 0:
            distance_norm /= self.radius_scale
        distance_norm = min(distance_norm, self.max_radius_clamp)

        if distance_norm <= 1.0:
            raw_radius = self._inverse_distance_curve(distance_norm)
        else:
            raw_radius = distance_norm

        ccx, ccy = self.corrected_center
        angle = angle_rad - self.angle_bias_rad
        x = ccx + self.radius_x * raw_radius * math.cos(angle)
        y = ccy + self.radius_y * raw_radius * math.sin(angle)
        return (x, y)

    def _apply_distance_curve(self, radius: float) -> float:
        if self.distance_curve_mode == "gamma":
            return radius ** max(self.gamma, 1e-6)
        if self.distance_curve_mode == "smoothstep":
            return radius * radius * (3.0 - 2.0 * radius)
        return radius

    def _inverse_distance_curve(self, distance: float) -> float:
        if self.distance_curve_mode == "gamma":
            return distance ** (1.0 / max(self.gamma, 1e-6))
        if self.distance_curve_mode == "smoothstep":
            return self._inverse_smoothstep(distance)
        return distance

    def _inverse_smoothstep(self, distance: float) -> float:
        distance = max(0.0, min(distance, 1.0))
        return 0.5 - math.sin(math.asin(1.0 - 2.0 * distance) / 3.0)
