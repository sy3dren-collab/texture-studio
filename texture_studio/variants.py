"""Seeded variations. Transformations do not synthesize new material features."""
import cv2
import numpy as np
from .core import seamless, validate


def random_tile_offsets(shift_x, shift_y, seed, columns=2, rows=2):
    """Independent offsets in material widths/heights for a configurable repeat."""
    if not np.isfinite([shift_x, shift_y]).all() or not (0 <= shift_x <= 1 and 0 <= shift_y <= 1):
        raise ValueError("隨機位移幅度必須介於 0% 與 100%")
    if any(not isinstance(value, int) or not 1 <= value <= 8 for value in (columns, rows)):
        raise ValueError("橫向與縱向素材張數須介於 1 與 8")
    return (np.random.default_rng(seed).uniform(-1, 1, (rows, columns, 2))*[shift_x, shift_y]).astype("float32")


def stagger_tiles(image, shift_x=0, shift_y=0, seed=42, progress=lambda value: None, output_size=None, columns=2, rows=2):
    """Compose independently jittered material copies on a periodic domain.

    The output contains 2x2 full-resolution copies by default. A separate
    output_size is used for interactive previews only. Each copy moves rigidly. Nearest
    patches fill gaps with wrapped source samples; narrow feathering softens
    overlaps. Toroidal distances preserve the same layout across all edges.
    """
    validate(image)
    offsets = random_tile_offsets(shift_x, shift_y, seed, columns, rows).reshape(-1, 2)
    tile_h, tile_w = image.shape[:2]
    # Keep native detail crisp: random moves land on whole source pixels.
    offsets = np.rint(offsets*[tile_w, tile_h])/[tile_w, tile_h]
    w, h = output_size if output_size is not None else (tile_w*columns, tile_h*rows)
    if not isinstance(w, int) or not isinstance(h, int) or min(w, h) < 4 or w*h > 160_000_000:
        raise ValueError("隨機排列尺寸過大，請降低單張素材大小；不會自動縮小像素")
    tile = image
    grid_y, grid_x = np.mgrid[:rows, :columns]
    centers = (np.stack((grid_x, grid_y), axis=-1).reshape(-1, 2)+.5+offsets) % [columns, rows]
    centers = centers.astype("float32")
    all_xs = (np.arange(w, dtype="float32")+.5)*(columns/w)
    result = np.empty((h, w, 3), dtype="float32")
    for start in range(0, h, 64):
        progress(90+int(6*start/h))
        end = min(h, start+64)
        ys = (np.arange(start, end, dtype="float32")+.5)*(rows/h)
        for left in range(0, w, 8192):
            xs = all_xs[left:left+8192]
            shape = (end-start, len(xs))
            best = np.full(shape, np.inf, dtype="float32")
            second = best.copy()
            first_index = np.zeros(shape, dtype="uint8")
            second_index = first_index.copy()
            for index, (cx, cy) in enumerate(centers):
                dx = (xs-cx+columns/2) % columns-columns/2
                dy = (ys-cy+rows/2) % rows-rows/2
                distance = dy[:, None]**2+dx[None, :]**2
                closer = distance < best
                runner_up = (~closer) & (distance < second)
                second[closer], second_index[closer] = best[closer], first_index[closer]
                second[runner_up], second_index[runner_up] = distance[runner_up], index
                best[closer], first_index[closer] = distance[closer], index

            def sample(indices):
                center = centers[indices]
                dx = (xs[None, :]-center[..., 0]+columns/2) % columns-columns/2
                dy = (ys[:, None]-center[..., 1]+rows/2) % rows-rows/2
                map_x = ((dx+.5)*tile_w-.5).astype("float32")
                map_y = ((dy+.5)*tile_h-.5).astype("float32")
                return cv2.remap(tile, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)

            base, neighbor = sample(first_index), sample(second_index)
            # Only the closest two patches contribute, preventing all-over blur.
            gap = np.clip((np.sqrt(second)-np.sqrt(best))/.12, 0, 1)
            weight = (.5*(1-gap*gap*(3-2*gap)))[..., None]
            result[start:end, left:left+len(xs)] = base*(1-weight)+neighbor*weight
    return result


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


def rotation_angle(rng, direction=True, arbitrary_angle=False):
    return rng.uniform(0, 360) if arbitrary_angle and not direction else int(rng.choice([0, 180] if direction else [0, 90, 180, 270]))


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
        angle = rotation_angle(rng, direction, arbitrary_angle)
        result = periodic_rotate(image, angle)
        if mirror and rng.random() < .5:
            result = result[:, ::-1]
        if mirror and rng.random() < .5:
            result = result[::-1]
        if translate:
            result = np.roll(result, (rng.integers(result.shape[0]), rng.integers(result.shape[1])), axis=(0, 1))
        if not any((brightness, hue, saturation, contrast)):
            outputs.append(result.astype("float32", copy=True))
            continue
        result = (result - .5) * (1 + rng.uniform(-contrast, contrast)) + .5 + rng.uniform(-brightness, brightness)
        hsv = cv2.cvtColor(np.clip(result, 0, 1).astype("float32"), cv2.COLOR_RGB2HSV)
        hsv[..., 0] = (hsv[..., 0] + rng.uniform(-hue, hue) * 360) % 360
        hsv[..., 1] *= 1 + rng.uniform(-saturation, saturation)
        result = cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)
        outputs.append(np.clip(result, 0, 1).astype("float32"))
    return outputs
