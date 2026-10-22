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


def correct_lighting(image, strength=0.7, radius=0.15, preserve_contrast=0.4, color=False):
    """Multiscale log illumination estimate; cannot distinguish albedo from lighting."""
    validate(image)
    if not 0 <= strength <= 1 or not 0.01 <= radius <= 0.5 or not 0 <= preserve_contrast <= 1:
        raise ValueError("光照參數超出範圍")
    luminance = image if color else np.sum(image * [0.2126, 0.7152, 0.0722], axis=2, keepdims=True)
    log = np.log(np.maximum(luminance, 1 / 1024)).astype(np.float32)
    sigma = max(1, min(image.shape[:2]) * radius)
    low = sum(cv2.GaussianBlur(log, (0, 0), s, borderType=cv2.BORDER_REFLECT) for s in (sigma, sigma * 2, sigma * 4)) / 3
    if low.ndim == 2:
        low = low[..., None]
    gain = np.exp((low.mean(axis=(0, 1), keepdims=True) - low) * strength * (1 - preserve_contrast))
    return np.clip(image * gain, 0, 1).astype(np.float32)


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
