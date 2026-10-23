"""RGB-derived reference maps; these are estimates, never measured PBR data."""
import cv2
import numpy as np
from .core import validate
from .bump import bump_normal


def derive_maps(image, height=None, normal_strength=2):
    validate(image)
    luminance = np.sum(image * [0.2126, .7152, .0722], axis=2).astype("float32")
    if height is None:
        low, high = np.percentile(luminance, (1, 99))
        height = np.clip((luminance-low)/max(float(high-low), 1e-6), 0, 1)
    else:
        height = np.asarray(height, dtype="float32")
        if height.shape != image.shape[:2] or not np.isfinite(height).all():
            raise ValueError("高度圖尺寸與 Base Color 不一致或含無效值")
    normal = bump_normal(height, normal_strength)
    # Local contrast is only a visual roughness proxy, not a reflectance estimate.
    mean = cv2.GaussianBlur(luminance, (0, 0), 3)
    roughness = np.clip(.6+np.abs(luminance-mean), 0, 1)
    return {"height_reference": height.astype("float32"), "roughness_reference": roughness.astype("float32"),
            "normal_reference": normal}
