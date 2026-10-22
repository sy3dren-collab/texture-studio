"""Seeded variations. Transformations do not synthesize new material features."""
import cv2
import numpy as np
from .core import seamless, validate


def periodic_rotate(image, angle):
    validate(image)
    if angle % 90 == 0:
        return np.rot90(image, round(angle / 90) % 4).copy()
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D(((w - 1) / 2, (h - 1) / 2), angle, 1)
    # Wrap input samples, then reconstruct output boundaries: rotating a torus
    # by an arbitrary angle does not preserve its original rectangular lattice.
    rotated = cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP)
    return seamless(rotated)


def generate_variants(image, count=4, seed=42, direction=True, mirror=False,
        brightness=.05, hue=.01, saturation=.05, contrast=.05, translate=True,
        arbitrary_angle=False, progress=lambda value: None):
    validate(image)
    if not 1 <= count <= 50:
        raise ValueError("變體數量必須介於 1 與 50")
    if any(not 0 <= v <= 1 for v in (brightness, hue, saturation, contrast)):
        raise ValueError("變化強度必須介於 0 與 1")
    rng = np.random.default_rng(seed)
    outputs = []
    for index in range(count):
        progress(60 + int(index / count * 35))
        angle = rng.uniform(0, 360) if arbitrary_angle and not direction else rng.choice([0, 180] if direction else [0, 90, 180, 270])
        result = periodic_rotate(image, angle)
        if mirror and rng.random() < .5:
            result = result[:, ::-1]
        if mirror and rng.random() < .5:
            result = result[::-1]
        if translate:
            result = np.roll(result, (rng.integers(result.shape[0]), rng.integers(result.shape[1])), axis=(0, 1))
        result = (result - .5) * (1 + rng.uniform(-contrast, contrast)) + .5 + rng.uniform(-brightness, brightness)
        hsv = cv2.cvtColor(np.clip(result, 0, 1).astype("float32"), cv2.COLOR_RGB2HSV)
        hsv[..., 0] = (hsv[..., 0] + rng.uniform(-hue, hue) * 360) % 360
        hsv[..., 1] *= 1 + rng.uniform(-saturation, saturation)
        result = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
        outputs.append(np.clip(result, 0, 1).astype("float32"))
    return outputs
