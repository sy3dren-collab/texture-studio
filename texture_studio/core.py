"""UI-independent RGB image processing. Arrays are float32 sRGB in [0, 1]."""
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageOps


def load_image(path):
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        # Honor embedded profiles when available; reject invalid profiles explicitly.
        if image.info.get("icc_profile"):
            from PIL import ImageCms
            from io import BytesIO
            image = ImageCms.profileToProfile(
                image.convert("RGB"), ImageCms.ImageCmsProfile(BytesIO(image.info["icc_profile"])),
                ImageCms.createProfile("sRGB"), outputMode="RGB")
        return np.asarray(image.convert("RGB"), dtype=np.float32) / 255


def save_image(image, path, color_space="sRGB"):
    from PIL import ImageCms
    path = Path(path)
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        raise ValueError("輸出格式必須是 PNG、JPG 或 TIFF")
    path.parent.mkdir(parents=True, exist_ok=True)
    pixels = np.round(np.clip(image, 0, 1) * 255).astype(np.uint8)
    options = {"icc_profile": ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()} if pixels.ndim == 3 and color_space == "sRGB" else {}
    Image.fromarray(pixels).save(path, **options)


def validate(image):
    if image.ndim != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 4:
        raise ValueError("需要至少 4×4 的 RGB 圖片")
    if not np.isfinite(image).all():
        raise ValueError("圖片包含無效數值")


def crop_image(image, region=None):
    """Non-destructive source selection in normalized (left, top, right, bottom)."""
    validate(image)
    if region is None:
        return image
    values = np.asarray(region, dtype=float)
    if values.shape != (4,) or not np.isfinite(values).all():
        raise ValueError("製圖範圍格式無效")
    left, top, right, bottom = values
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("製圖範圍超出圖片")
    h, w = image.shape[:2]
    x0, y0 = int(np.floor(left*w+1e-7)), int(np.floor(top*h+1e-7))
    x1, y1 = int(np.ceil(right*w-1e-7)), int(np.ceil(bottom*h-1e-7))
    if min(x1-x0, y1-y0) < 4:
        raise ValueError("製圖範圍至少需要 4×4 像素")
    return image[y0:y1, x0:x1]


def _illumination(log_image, radius, preserve_contrast):
    """Robust broad shading fit followed by a texture-resistant residual filter."""
    h, w = log_image.shape
    # Fit on a fixed grid, keeping large inputs fast and the fit well-conditioned.
    grid = cv2.resize(log_image, (32, 32), interpolation=cv2.INTER_AREA)
    y, x = np.mgrid[-1:1:32j, -1:1:32j]
    basis = np.stack((np.ones_like(x), x, y, x*x, x*y, y*y, x**4, y**4, x*x*y*y), axis=-1)
    design = basis.reshape(-1, basis.shape[-1])
    values = grid.ravel()
    weights = np.ones_like(values)
    for _ in range(5):
        root = np.sqrt(weights)
        coefficients = np.linalg.lstsq(design*root[:, None], values*root, rcond=None)[0]
        residual = values-design@coefficients
        scale = max(.025, 1.4826*np.median(np.abs(residual-np.median(residual))))
        weights = 1/(1+(residual/(scale*2))**2)
    y, x = np.mgrid[-1:1:complex(h), -1:1:complex(w)]
    surface = sum(coefficient*term for coefficient, term in zip(coefficients,
        (np.ones_like(x), x, y, x*x, x*y, y*y, x**4, y**4, x*x*y*y))).astype("float32")
    residual = log_image-surface
    scale = max(.025, 1.4826*np.median(np.abs(residual-np.median(residual))))
    # Dark narrow veins get little influence on the illumination estimate.
    # preserve_contrast protects texture outliers, rather than weakening all
    # shadow removal as the old strength*(1-preserve_contrast) implementation did.
    cutoff = scale*(3.5-2*preserve_contrast)
    weights = (1/(1+(residual/cutoff)**2)).astype("float32")
    sigma = max(1.2, min(h, w)*radius)
    smooth = np.zeros_like(log_image)
    for factor in (.6, 1.3):
        numerator = cv2.GaussianBlur(residual*weights, (0, 0), sigma*factor, borderType=cv2.BORDER_REFLECT)
        denominator = cv2.GaussianBlur(weights, (0, 0), sigma*factor, borderType=cv2.BORDER_REFLECT)
        smooth += .5*numerator/np.maximum(denominator, 1e-6)
    return surface+smooth


def correct_lighting(image, strength=0.85, radius=0.1, preserve_contrast=0.7, color=False):
    """Correct vignettes/gradients on a bounded working image; retain RGB detail.

    A single RGB image cannot uniquely separate material color from lighting.
    Strength zero is an exact bypass; gains are limited to avoid extreme noise.
    """
    validate(image)
    if not 0 <= strength <= 1 or not 0.01 <= radius <= 0.5 or not 0 <= preserve_contrast <= 1:
        raise ValueError("光照參數超出範圍")
    if strength == 0:
        return image.copy()
    h, w = image.shape[:2]
    ratio = min(1, 384/max(h, w))
    small = cv2.resize(image, (max(4, round(w*ratio)), max(4, round(h*ratio))), interpolation=cv2.INTER_AREA)
    luminance = small if color else np.sum(small*np.array([.2126, .7152, .0722], "float32"), axis=2, keepdims=True)
    log = np.log(np.maximum(luminance, 1/4096))
    channels = []
    for channel in range(log.shape[2]):
        field = _illumination(log[..., channel], radius, preserve_contrast)
        # Use the well-lit portion as reference, instead of retaining a darkened
        # overall mean when most corners are underexposed.
        gain_log = np.clip(strength*(np.percentile(field, 75)-field), -np.log(4), np.log(4))
        channels.append(cv2.resize(gain_log, (w, h), interpolation=cv2.INTER_LINEAR))
    gain = np.exp(np.stack(channels, axis=2))
    if not color:
        gain = np.minimum(gain, 1/np.maximum(image.max(axis=2, keepdims=True), 1e-6))
    return np.clip(image*gain, 0, 1).astype(np.float32)


def seamless(image, strength=1.0):
    """Periodic-plus-smooth decomposition (Poisson solution on a torus).

    Removes the smooth component responsible for boundary jumps, without a
    blurred cross in the center. The first/last pixel need not be identical:
    they are adjacent samples, one pixel apart on the periodic domain.
    """
    validate(image)
    if not 0 <= strength <= 1:
        raise ValueError("融合強度必須介於 0 與 1")
    h, w = image.shape[:2]
    boundary = np.zeros_like(image)
    boundary[0] += image[-1] - image[0]
    boundary[-1] += image[0] - image[-1]
    boundary[:, 0] += image[:, -1] - image[:, 0]
    boundary[:, -1] += image[:, 0] - image[:, -1]
    denominator = (2 * np.cos(2 * np.pi * np.arange(h) / h)[:, None]
                   + 2 * np.cos(2 * np.pi * np.arange(w) / w)[None, :] - 4)
    denominator[0, 0] = 1
    spectrum = np.fft.fft2(boundary, axes=(0, 1)) / denominator[..., None]
    spectrum[0, 0] = 0
    smooth = np.fft.ifft2(spectrum, axes=(0, 1)).real
    return np.clip(image - strength * smooth, 0, 1).astype(np.float32)


def seam_quality(image):
    validate(image)
    horizontal = np.abs(image[:, 0] - image[:, -1]).mean(axis=1)
    vertical = np.abs(image[0] - image[-1]).mean(axis=1)
    return {"left_right": float(horizontal.mean()), "top_bottom": float(vertical.mean()),
            "horizontal_difference": horizontal, "vertical_difference": vertical}


def repeat_preview(image, count=3):
    if count not in (1, 2, 3, 5):
        raise ValueError("重複次數須為 1、2、3、5")
    return np.tile(image, (count, count, 1))
