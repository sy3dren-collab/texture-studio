import numpy as np
import pytest
from texture_studio.painting import PeriodicCloneStroke, PeriodicDodgeStroke


def source():
    image = np.zeros((64, 80, 3), dtype="float32")
    image[20:44, 28:52] = [.2, .6, 1]
    return image


def test_clone_wraps_both_edges_and_samples_frozen_source():
    image = source()
    before = image.copy()
    stroke = PeriodicCloneStroke(image, (40-79, 32-63), diameter=16)
    stroke.paint_to((79, 63))
    for y, x in [(0, 0), (0, 79), (63, 0), (63, 79)]:
        np.testing.assert_allclose(stroke.image[y, x], [.2, .6, 1], atol=1e-7)
    np.testing.assert_array_equal(image, before)
    np.testing.assert_array_equal(stroke.image[12:50, 12:68], before[12:50, 12:68])
    assert stroke.changed


def test_opacity_is_per_stroke_instead_of_accumulating_with_dabs():
    image = source()
    stroke = PeriodicCloneStroke(image, (30, 22), diameter=8, opacity=.25)
    for _ in range(20):
        stroke.paint_to((10, 10))
    np.testing.assert_allclose(stroke.image[10, 10], [.05, .15, .25], atol=1e-7)
    next_stroke = PeriodicCloneStroke(stroke.image, (30, 22), diameter=8, opacity=.25)
    next_stroke.paint_to((10, 10))
    np.testing.assert_allclose(next_stroke.image[10, 10], np.array([.2, .6, 1])*.4375, atol=1e-7)


def test_fast_drag_has_no_gaps_and_clone_follows_source_offset():
    image = np.zeros((64, 80, 3), dtype="float32")
    image[10:25] = 1
    stroke = PeriodicCloneStroke(image, (0, -30), diameter=8)
    stroke.paint_to((8, 46))
    stroke.paint_to((70, 46))
    np.testing.assert_allclose(stroke.image[46, 8:71], 1)


def test_overlapping_clone_does_not_read_its_own_paint():
    image = np.repeat(np.linspace(0, 1, 80, dtype="float32")[None, :, None], 64, axis=0)
    image = np.repeat(image, 3, axis=2)
    stroke = PeriodicCloneStroke(image, (-8, 0), diameter=6)
    stroke.paint_to((20, 32))
    stroke.paint_to((60, 32))
    np.testing.assert_allclose(stroke.image[32, 20:61], image[32, 12:53], atol=1e-7)


def test_zero_opacity_and_oversized_brush_are_well_defined():
    image = source()
    stroke = PeriodicCloneStroke(image, (10, 10), diameter=512, opacity=0)
    stroke.paint_to((-2, 70))
    assert not stroke.changed
    np.testing.assert_array_equal(stroke.image, image)
    stroke = PeriodicCloneStroke(image, (10, 10), diameter=512)
    stroke.paint_to((79.4, 63.4))
    assert np.isfinite(stroke.image).all()
    assert stroke.image.min() >= 0 and stroke.image.max() <= 1


@pytest.mark.parametrize("diameter,opacity", [(0, 1), (8, -1), (8, 1.1), (float("nan"), 1)])
def test_invalid_brush_values_are_rejected(diameter, opacity):
    with pytest.raises(ValueError):
        PeriodicCloneStroke(source(), (0, 0), diameter, opacity)


@pytest.mark.parametrize("lighten,factor", [(True, 1.5), (False, .75)])
def test_light_dark_brush_wraps_keeps_color_and_opacity_does_not_accumulate(lighten, factor):
    image = np.full((64, 80, 3), [.1, .2, .3], dtype="float32")
    stroke = PeriodicDodgeStroke(image, diameter=16, opacity=.5, lighten=lighten)
    for _ in range(10):
        stroke.paint_to((79, 63))
    for y, x in [(0, 0), (0, 79), (63, 0), (63, 79)]:
        np.testing.assert_allclose(stroke.image[y, x], image[y, x]*factor, atol=1e-7)
    np.testing.assert_array_equal(stroke.image[32, 40], image[32, 40])
    assert stroke.changed


def test_lightening_retains_highlight_ratios_and_darkening_retains_texture():
    image = np.full((64, 80, 3), [.4, .6, .8], dtype="float32")
    stroke = PeriodicDodgeStroke(image, diameter=20)
    stroke.paint_to((40, 32))
    np.testing.assert_allclose(stroke.image[32, 40], [.5, .75, 1], atol=1e-7)
    image[30:35, 38:43] *= .5
    dark = PeriodicDodgeStroke(image, diameter=20, lighten=False)
    dark.paint_to((40, 32))
    np.testing.assert_allclose(dark.image[30:35, 38:43], image[30:35, 38:43]*.5, atol=1e-7)


def test_one_pixel_brush_paints_at_fractional_coordinates():
    image = np.full((32, 32, 3), .2, dtype="float32")
    stroke = PeriodicDodgeStroke(image, diameter=1)
    stroke.paint_to((10.5, 10.5))
    assert stroke.changed
    assert (stroke.image[10:12, 10:12] > image[10:12, 10:12]).all()
