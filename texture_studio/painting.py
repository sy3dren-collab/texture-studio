"""Periodic clone and dodge strokes, independent of Qt and preview size."""
import cv2
import numpy as np
from .core import validate


class PeriodicBrushStroke:
    def __init__(self, image, diameter=64, opacity=1):
        validate(image)
        if not np.isfinite([diameter, opacity]).all() or diameter < 1 or not 0 <= opacity <= 1:
            raise ValueError("畫筆大小或透明度無效")
        self.base = image
        self.image = image.copy()
        self.h, self.w = image.shape[:2]
        self.radius = min(diameter, self.h, self.w)/2
        self.opacity = opacity
        self.coverage = np.zeros(image.shape[:2], dtype="float32")
        self.last = None
        self.changed = False

    def paint_to(self, point):
        point = np.asarray(point, dtype=float)
        if point.shape != (2,) or not np.isfinite(point).all():
            raise ValueError("畫筆位置無效")
        if self.last is None:
            self._dab(point)
        else:
            steps = max(1, int(np.ceil(np.linalg.norm(point-self.last)/max(.5, self.radius*.2))))
            for step in range(1, steps+1):
                self._dab(self.last+(point-self.last)*(step/steps))
        self.last = point

    def _dab(self, point):
        if self.opacity == 0:
            return
        cx, cy = point % [self.w, self.h]
        r = self.radius
        xs = np.unique(np.arange(int(np.floor(cx-r)), int(np.ceil(cx+r))+1) % self.w)
        ys = np.unique(np.arange(int(np.floor(cy-r)), int(np.ceil(cy+r))+1) % self.h)
        dx = (xs-cx+self.w/2) % self.w-self.w/2
        dy = (ys-cy+self.h/2) % self.h-self.h/2
        distance = np.sqrt(dy[:, None]**2+dx[None, :]**2)
        # Half-pixel antialiasing also lets a 1 px brush paint between samples.
        edge = np.clip((r+.5-distance)/(r*.25+.5), 0, 1)
        alpha = (edge*edge*(3-2*edge)*self.opacity).astype("float32")
        region = np.ix_(ys, xs)
        alpha = np.maximum(alpha, self.coverage[region])
        if not np.any(alpha > self.coverage[region]):
            return
        self.coverage[region] = alpha
        original = self.base[region]
        sampled = self.sample(xs, ys)
        result = original*(1-alpha[..., None])+sampled*alpha[..., None]
        if np.any(np.abs(result-original) > 1e-7):
            self.changed = True
        self.image[region] = result

    def sample(self, xs, ys):
        raise NotImplementedError


class PeriodicCloneStroke(PeriodicBrushStroke):
    def __init__(self, image, offset, diameter=64, opacity=1):
        offset = np.asarray(offset, dtype="float32")
        if offset.shape != (2,) or not np.isfinite(offset).all():
            raise ValueError("印章參考點無效")
        super().__init__(image, diameter, opacity)
        self.offset = offset

    def sample(self, xs, ys):
        shape = (len(ys), len(xs))
        map_x = np.broadcast_to((xs+self.offset[0]) % self.w, shape).astype("float32").copy()
        map_y = np.broadcast_to(((ys+self.offset[1]) % self.h)[:, None], shape).astype("float32").copy()
        return cv2.remap(self.base, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


class PeriodicDodgeStroke(PeriodicBrushStroke):
    def __init__(self, image, diameter=64, opacity=1, lighten=True):
        super().__init__(image, diameter, opacity)
        self.lighten = lighten

    def sample(self, xs, ys):
        original = self.base[np.ix_(ys, xs)]
        # Change exposure by one stop, keeping channel ratios and detail.
        gain = np.minimum(2, 1/np.maximum(original.max(axis=2, keepdims=True), 1e-6)) if self.lighten else .5
        return original*gain
