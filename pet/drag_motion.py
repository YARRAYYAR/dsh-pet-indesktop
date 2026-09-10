"""Time-based pointer velocity and the original bouncy drag spring."""

from __future__ import annotations

import math

# Original drag acceleration: (target - position) * 80 - velocity * 10.
DRAG_STIFFNESS = 80.0
DRAG_DAMPING = 10.0
VELOCITY_SMOOTHING_SECONDS = 0.04
RELEASE_STALE_SECONDS = 0.08
# Runtime drag sampling cap. The catalog re-exports this value so the window
# and the pure motion helpers cannot silently drift apart.
MAX_THROW_SPEED = 5200.0


def spring_step(position: float, velocity: float, target: float, dt: float) -> tuple[float, float]:
    """Exact underdamped solution, preserving the original spring's rebound."""
    if dt <= 0:
        return position, velocity
    offset = position - target
    decay_rate = DRAG_DAMPING / 2.0
    frequency = math.sqrt(DRAG_STIFFNESS - decay_rate * decay_rate)
    sine = math.sin(frequency * dt)
    cosine = math.cos(frequency * dt)
    coupled = (velocity + decay_rate * offset) / frequency
    decay = math.exp(-decay_rate * dt)
    shifted = offset * cosine + coupled * sine
    return (
        target + shifted * decay,
        ((-offset * frequency * sine + coupled * frequency * cosine) - decay_rate * shifted) * decay,
    )


def pointer_velocity(
    previous: tuple[float, float],
    dx: float,
    dy: float,
    dt: float,
    *,
    max_speed: float = MAX_THROW_SPEED,
) -> tuple[float, float]:
    """Smooth pointer samples by elapsed time, independently of spring velocity."""
    if dt <= 0:
        return previous
    if dt > RELEASE_STALE_SECONDS:
        previous = (0.0, 0.0)
    vx, vy = dx / dt, dy / dt
    speed = math.hypot(vx, vy)
    try:
        limit = float(max_speed)
    except (TypeError, ValueError, OverflowError):
        limit = MAX_THROW_SPEED
    if not math.isfinite(limit) or limit <= 0:
        limit = MAX_THROW_SPEED
    if speed > limit:
        factor = limit / speed
        vx, vy = vx * factor, vy * factor
    weight = -math.expm1(-dt / VELOCITY_SMOOTHING_SECONDS)
    return tuple(old + (new - old) * weight for old, new in zip(previous, (vx, vy)))


def release_velocity(velocity: tuple[float, float], elapsed: float) -> tuple[float, float]:
    """Holding the pointer still before release must not replay an old fling."""
    return velocity if 0 <= elapsed <= RELEASE_STALE_SECONDS else (0.0, 0.0)
