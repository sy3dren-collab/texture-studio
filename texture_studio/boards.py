"""Physical-size board layouts. Periodic layouts are built on a torus, never feathered."""
from dataclasses import dataclass, asdict
import cv2
import numpy as np
from .core import correct_lighting, validate


@dataclass
class BoardSettings:
    width: int = 1024
    height: int = 1024
    board_width_mm: float = 150
    board_length_mm: float = 900
    world_width_mm: float = 3600
    world_height_mm: float = 1800
    gap_mm: float = 2
    bevel_mm: float = 1
    pattern: str = "half"
    offset: float = .5
    seed: int = 42
    periodic: bool = True
    min_length_mm: float = 450
    max_length_mm: float = 1200
    brightness: float = .03
    mirror: bool = False
    weights: tuple = ()

    def metadata(self):
        return {**asdict(self), "uv_ratio": self.world_width_mm / self.world_height_mm,
                "base_color_space": "sRGB", "data_map_color_space": "linear / non-color",
                "derived_maps": "RGB-derived reference only; not measured physical material"}


def _check(config, images):
    if not images:
        raise ValueError("至少需要一張板材素材")
    for image in images:
        validate(image)
    c = config
    if not 4 <= c.width <= 8192 or not 4 <= c.height <= 8192:
        raise ValueError("解析度必須介於 4 與 8192")
    if min(c.board_width_mm, c.board_length_mm, c.world_width_mm, c.world_height_mm) <= 0:
        raise ValueError("實際尺寸必須大於零")
    if not 0 <= c.gap_mm < min(c.board_width_mm, c.board_length_mm):
        raise ValueError("板縫必須小於板寬與板長")
    if c.bevel_mm < 0 or not 0 <= c.offset <= 1:
        raise ValueError("倒角或錯縫比例無效")
    if c.min_length_mm <= 0 or c.max_length_mm < c.min_length_mm:
        raise ValueError("最短／最長板長無效")
    if c.weights and (len(c.weights) != len(images) or min(c.weights) < 0 or sum(c.weights) <= 0):
        raise ValueError("素材權重必須與素材數量相同，且總和大於零")
    if c.pattern not in {"straight", "half", "third", "quarter", "random", "variable", "custom", "herringbone", "chevron", "basketweave"}:
        raise ValueError("不支援的排列")
    if c.periodic:
        lengths = [(c.world_height_mm, c.board_width_mm)]
        if c.pattern not in {"variable", "herringbone", "chevron", "basketweave"}:
            lengths.append((c.world_width_mm, c.board_length_mm))
        if c.pattern in {"herringbone", "basketweave"}:
            ratio = c.board_length_mm / c.board_width_mm
            if not np.isclose(ratio, round(ratio)):
                raise ValueError("週期性特殊拼法需要整數板長寬比")
            period = 2 * c.board_length_mm
            lengths = [(c.world_width_mm, period), (c.world_height_mm, period)]
        if c.pattern == "chevron":
            lengths = [(c.world_width_mm, 2*c.board_length_mm), (c.world_height_mm, c.board_width_mm)]
        if any(not np.isclose(size / unit, round(size / unit)) for size, unit in lengths):
            raise ValueError("尺寸無法形成週期；請調整整面尺寸為排列週期的整數倍，或關閉週期性輸出")


def _sample(image, u, v, aspect):
    # Center crop to physical aspect, preserving texel proportions.
    h, w = image.shape[:2]
    if h > w:
        image = np.rot90(image)
        h, w = image.shape[:2]
    crop_w = min(w, h * aspect)
    crop_h = min(h, w / aspect)
    x = ((w - crop_w) / 2 + u * max(0, crop_w - 1)).astype("float32")
    y = ((h - crop_h) / 2 + v * max(0, crop_h - 1)).astype("float32")
    return cv2.remap(image, x, y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def generate_boards(images, config=None, progress=lambda value: None):
    c = config or BoardSettings()
    _check(c, images)
    rng = np.random.default_rng(c.seed)
    images = [correct_lighting(image, .35) for image in images]
    base = np.zeros((c.height, c.width, 3), "float32")
    gap = np.zeros((c.height, c.width), "float32")
    height = np.zeros_like(gap)
    weights = np.asarray(c.weights or [1] * len(images), dtype=float)
    weights /= weights.sum()
    # Render each board independently, wrapping its geometry and source samples.
    # Adjacent duplicates are avoided greedily when weights permit alternatives.
    previous = -1
    boards = []
    rows = int(np.ceil(c.world_height_mm / c.board_width_mm))
    offsets = {"straight": 0, "half": .5, "third": 1/3, "quarter": .25, "custom": c.offset}
    if c.pattern in {"herringbone", "chevron", "basketweave"}:
        return _special(images, c, progress)
    for row in range(rows):
        shift = rng.uniform(0, c.board_length_mm) if c.pattern in {"random", "variable"} else row * offsets[c.pattern] * c.board_length_mm
        if c.pattern == "variable":
            low = int(np.ceil(c.world_width_mm / c.max_length_mm))
            high = int(np.floor(c.world_width_mm / c.min_length_mm))
            if low > high:
                raise ValueError("整面寬度與最短／最長板長無法形成週期")
            count = max(low, min(high, round(c.world_width_mm / c.board_length_mm)))
            lengths = np.full(count, c.world_width_mm / count)
            # Pairwise transfers preserve exact period and all length bounds.
            for i in range(count * 4):
                a, b = rng.integers(count, size=2)
                if a != b:
                    delta = rng.uniform(max(c.min_length_mm-lengths[a], lengths[b]-c.max_length_mm),
                                        min(c.max_length_mm-lengths[a], lengths[b]-c.min_length_mm))
                    lengths[a] += delta
                    lengths[b] -= delta
        else:
            lengths = np.full(int(np.ceil(c.world_width_mm / c.board_length_mm)) + (0 if c.periodic else 1), c.board_length_mm)
        x = -shift % c.world_width_mm if c.periodic else -shift
        for length in lengths:
            probabilities = weights.copy()
            if len(images) > 1 and probabilities.sum() - probabilities[previous] > 0 and previous >= 0:
                probabilities[previous] = 0
                probabilities /= probabilities.sum()
            asset = int(rng.choice(len(images), p=probabilities))
            previous = asset
            boards.append((x, row * c.board_width_mm, length, c.board_width_mm, asset,
                           rng.random() < .5, c.mirror and rng.random() < .5,
                           rng.uniform(-c.brightness, c.brightness)))
            x = (x + length) % c.world_width_mm if c.periodic else x + length
    for index, (x, y, length, width, asset, rotate, mirror, brightness) in enumerate(boards):
        progress(60 + int(index / max(1, len(boards)) * 35))
        for shift in (-c.world_width_mm, 0, c.world_width_mm) if c.periodic else (0,):
            left = max(0, int(np.floor((x+shift) / c.world_width_mm*c.width)))
            right = min(c.width, int(np.ceil((x+shift+length) / c.world_width_mm*c.width)))
            top = max(0, int(np.floor(y / c.world_height_mm*c.height)))
            bottom = min(c.height, int(np.ceil((y+width) / c.world_height_mm*c.height)))
            if right <= left or bottom <= top:
                continue
            xx = (np.arange(left, right)+.5)*c.world_width_mm/c.width-x-shift
            yy = (np.arange(top, bottom)+.5)*c.world_height_mm/c.height-y
            u, v = np.meshgrid(xx/length, yy/width)
            valid = (u >= 0) & (u < 1) & (v >= 0) & (v < 1)
            distance = np.minimum(np.minimum(u, 1-u)*length, np.minimum(v, 1-v)*width)
            material = _sample(images[asset], 1-u if rotate else u, 1-v if rotate != mirror else v, length/width)
            _paint(base[top:bottom, left:right], gap[top:bottom, left:right], height[top:bottom, left:right],
                   material, distance, valid, brightness, c)
    return {"base_color": base, "gap_mask": gap, "height_reference": height}


def _paint(base, gap, height, material, distance, valid, brightness, c):
    # Smooth subpixel grout coverage, measured in physical units.
    footprint = min(c.world_width_mm/c.width, c.world_height_mm/c.height)
    coverage = np.clip((c.gap_mm/2-distance)/footprint+.5, 0, 1) if c.gap_mm else np.zeros_like(distance)
    shaded = np.clip(material+brightness, 0, 1)*(1-coverage[..., None])+.08*coverage[..., None]
    base[valid] = shaded[valid]
    gap[valid] = coverage[valid]
    elevation = np.clip((distance-c.gap_mm/2)/max(c.bevel_mm, .001), 0, 1)
    height[valid] = elevation[valid]


def _special(images, c, progress):
    """Rasterize analytic herringbone, chevron and basketweave lattices in strips."""
    base = np.zeros((c.height, c.width, 3), "float32")
    gap = np.zeros((c.height, c.width), "float32")
    height = np.zeros_like(gap)
    n = c.board_length_mm / c.board_width_mm
    period_x = max(1, round(c.world_width_mm/c.board_width_mm))
    period_y = max(1, round(c.world_height_mm/c.board_width_mm))
    weights = np.asarray(c.weights or [1]*len(images), dtype=float)
    cumulative = np.cumsum(weights/weights.sum())
    for start in range(0, c.height, 128):
        progress(60+int(start/c.height*35))
        stop = min(c.height, start+128)
        x, y = np.meshgrid((np.arange(c.width)+.5)*c.world_width_mm/c.width/c.board_width_mm,
                          (np.arange(start, stop)+.5)*c.world_height_mm/c.height/c.board_width_mm)
        ix, iy = np.floor(x), np.floor(y)
        if c.pattern == "herringbone":
            k = np.floor((ix+iy)/(2*n))
            horizontal = (ix+iy) % (2*n) < n
            ox = np.where(horizontal, 2*n*k-iy, ix)
            oy = np.where(horizontal, iy, 2*n*k+n-ix)
            u = np.where(horizontal, (x-ox)/n, (y-oy)/n)
            v = np.where(horizontal, y-oy, x-ox)
        elif c.pattern == "basketweave":
            bx, by = np.floor(x/n), np.floor(y/n)
            horizontal = (bx+by) % 2 == 0
            ox = np.where(horizontal, bx*n, ix)
            oy = np.where(horizontal, iy, by*n)
            u = np.where(horizontal, (x-ox)/n, (y-oy)/n)
            v = np.where(horizontal, y-oy, x-ox)
        else:
            bx = np.floor(x/n)
            sign = np.where(bx % 2 == 0, 1, -1)
            local_x = x-bx*n
            slope = np.where(sign == 1, local_x, n-local_x)
            row = np.floor(y-slope)
            ox, oy = bx*n, row
            u, v = local_x/n, y-slope-row
        # Stateless board identity: adjacent strips reproduce identical choices.
        ax = np.mod(ox, period_x) if c.periodic else ox
        ay = np.mod(oy, period_y) if c.periodic else oy
        identity = np.mod(ax*73856093+ay*19349663+c.seed*83492791, 2147483647).astype("int64")
        random = np.mod(identity*48271, 2147483647)/2147483647
        asset = np.minimum(np.searchsorted(cumulative, random), len(images)-1)
        rotate = identity % 2 == 0
        material = np.zeros((*u.shape, 3), "float32")
        for i, image in enumerate(images):
            sample = _sample(image, np.where(rotate, 1-u, u), np.where(rotate, 1-v, v), n)
            material[asset == i] = sample[asset == i]
        distance = np.minimum(np.minimum(u, 1-u)*c.board_length_mm, np.minimum(v, 1-v)*c.board_width_mm)
        _paint(base[start:stop], gap[start:stop], height[start:stop], material, distance,
               np.ones(u.shape, bool), (random-.5)[..., None]*2*c.brightness, c)
    return {"base_color": base, "gap_mask": gap, "height_reference": height}
