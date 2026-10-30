"""Rectify a user-selected quadrilateral in a full-resolution RGB image."""
import cv2
import numpy as np

from .core import validate


def perspective_geometry(shape, corners):
    """Validate normalized TL, TR, BR, BL corners and estimate output size."""
    h, w = shape[:2]
    points = np.asarray(corners, dtype=np.float64)
    if points.shape != (4, 2) or not np.isfinite(points).all() or np.any(points < 0) or np.any(points > 1):
        raise ValueError("四個角必須位於圖片範圍內")
    if h >= 32767 or w >= 32767:
        raise ValueError("素材單邊超過 32766 像素，請先縮小圖片")
    points = points * [w - 1, h - 1]
    edges = np.roll(points, -1, axis=0) - points
    lengths = np.linalg.norm(edges, axis=1)
    crosses = edges[:, 0]*np.roll(edges[:, 1], -1) - edges[:, 1]*np.roll(edges[:, 0], -1)
    if np.min(lengths) < 3 or np.min(crosses) <= 0.01:
        raise ValueError("請依順序拖曳四角，圍成不交叉、至少 4×4 像素的範圍")
    # Choose the longer opposite edges so the far side is not needlessly
    # downsampled. The physical proportions cannot be inferred from four
    # points alone, so these dimensions are an image-based estimate.
    width = round(max(lengths[0], lengths[2])) + 1
    height = round(max(lengths[1], lengths[3])) + 1
    if min(width, height) < 4 or max(width, height) >= 32767 or width*height > 160_000_000:
        raise ValueError("矯正後圖片尺寸過大或過小，請調整選取範圍")
    return points.astype(np.float32), (width, height)


def rectify_perspective(image, corners):
    """Return a rectangular image, using the original pixels, not the preview."""
    validate(image)
    points, (width, height) = perspective_geometry(image.shape, corners)
    target = np.array([[0, 0], [width-1, 0], [width-1, height-1], [0, height-1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(points, target)
    corrected = cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_LINEAR,
                                    borderMode=cv2.BORDER_REPLICATE)
    return np.clip(corrected, 0, 1).astype(np.float32)
