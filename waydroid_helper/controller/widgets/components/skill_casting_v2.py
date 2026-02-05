#!/usr/bin/env python3
"""Skill Casting geometry helpers.

The in-game skill range is rendered as an ellipse on screen, while the joystick
widget itself remains a perfect circle.  The mapper below keeps these two spaces
in sync by:

1) Treating ``center_x/center_y`` as the *character* anchor center.
2) Treating ``y_offset`` as the vertical shift from character center to the
   ellipse center.
3) Projecting the cursor direction from the character center onto the ellipse
   border, then normalizing into the joystick circle.
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
    # Method 1 (affine): pre-scale cursor Y delta to compensate projection tilt.
    # Values < 1.0 reduce vertical influence and help angle matching on diagonals.
    angle_affine_y_scale: float = 0.745

    @property
    def ellipse_center_y(self) -> float:
        return self.center_y + self.y_offset

    @property
    def ellipse_vertical_radius(self) -> float:
        return self.radius * self.vertical_scale_ratio


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

    # Method 1 (affine): remap pointer delta before computing joystick direction.
    # Keep the anchor point fixed at character center.
    dx = mouse_x - calibration.center_x
    dy = mouse_y - calibration.center_y
    if math.isfinite(calibration.angle_affine_y_scale) and calibration.angle_affine_y_scale > 0:
        dy *= calibration.angle_affine_y_scale
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
    if math.isfinite(calibration.angle_affine_y_scale) and calibration.angle_affine_y_scale > 0:
        dy *= calibration.angle_affine_y_scale
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
