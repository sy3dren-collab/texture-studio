"""Independent, periodic BUMP and OpenGL normal-map generation."""
import numpy as np
from .core import validate


def make_bump(image, brightness=0, contrast=1):
    validate(image)
    if not np.isfinite([brightness, contrast]).all() or not -1 <= brightness <= 1 or not 0 <= contrast <= 3:
        raise ValueError("BUMP 明暗或對比數值無效")
    luminance = np.sum(image*np.array([.2126, .7152, .0722], dtype="float32"), axis=2)
    return np.clip((luminance-.5)*contrast+.5+brightness, 0, 1).astype("float32")


def bump_normal(height, strength=2):
    if height.ndim != 2 or min(height.shape) < 4 or not np.isfinite(height).all():
        raise ValueError("需要有效的黑白 BUMP 圖片")
    if not np.isfinite(strength) or not 0 <= strength <= 8:
        raise ValueError("法線強度數值無效")
    dx = (np.roll(height, -1, axis=1)-np.roll(height, 1, axis=1))*.5*strength
    dy = (np.roll(height, -1, axis=0)-np.roll(height, 1, axis=0))*.5*strength
    # Image rows point down; OpenGL tangent-space +Y points up.
    normal = np.stack((-dx, dy, np.ones_like(height)), axis=2)
    normal /= np.linalg.norm(normal, axis=2, keepdims=True)
    return ((normal+1)*.5).astype("float32")
