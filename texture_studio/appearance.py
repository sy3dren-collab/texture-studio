"""Pointwise color edits and centered, wrapped material transforms."""
import cv2
import numpy as np
from .core import validate, seamless


def adjust_material(image, saturation=1., brightness=0., tint=None, scale=1., angle=0.):
    """Keep the canvas fixed while changing one material's color and motif size.

    Inputs must already be seamless. Arbitrary geometry is reconstructed on
    the output torus; wrap sampling prevents empty corners when zooming out.
    """
    validate(image)
    if not 0 <= saturation <= 2 or not -1 <= brightness <= 1 or not .25 <= scale <= 4 or not -180 <= angle <= 180:
        raise ValueError("素材調整參數超出範圍")
    result = image.copy()
    if tint is not None:
        target = np.asarray(tint, dtype="float32")
        if target.shape != (3,) or not np.isfinite(target).all() or np.any((target < 0) | (target > 1)):
            raise ValueError("上色顏色格式無效")
        luminance = np.sum(result*np.array([.2126, .7152, .0722], "float32"), axis=2)
        detail = luminance/max(float(luminance.mean()), 1e-6)
        # Replace original chroma, preserving the original light/dark texture.
        detail = np.minimum(detail, 1/max(float(target.max()), 1e-6))
        result = detail[..., None]*target
    if saturation != 1:
        hsv = cv2.cvtColor(result, cv2.COLOR_RGB2HSV)
        hsv[..., 1] = np.clip(hsv[..., 1]*saturation, 0, 1)
        result = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
    if brightness:
        result *= 2**(brightness*2)
    result = np.clip(result, 0, 1).astype("float32")
    if scale != 1 or angle != 0:
        h, w = result.shape[:2]
        matrix = cv2.getRotationMatrix2D(((w-1)/2, (h-1)/2), angle, scale)
        result = cv2.warpAffine(result, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_WRAP)
        result = seamless(np.clip(result, 0, 1))
    return result
