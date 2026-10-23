import numpy as np
import cv2
import pytest
from texture_studio.variants import generate_variants, periodic_rotate, stagger_tiles, random_tile_offsets
from texture_studio.core import seam_quality


def texture():
    y, x = np.mgrid[:64, :64] / 64
    return np.repeat((.5 + .1 * np.cos(2*np.pi*4*x) * np.sin(2*np.pi*3*y))[..., None], 3, axis=2).astype("float32")


def test_seed_reproducible_and_different():
    image = texture()
    first = generate_variants(image, 4, 12)
    second = generate_variants(image, 4, 12)
    other = generate_variants(image, 4, 13)
    assert all(np.array_equal(a, b) for a, b in zip(first, second))
    assert any(not np.array_equal(a, b) for a, b in zip(first, other))


def test_arbitrary_rotation_restores_boundary():
    image = texture()
    result = periodic_rotate(image, 33)
    quality = seam_quality(result)
    assert max(quality["left_right"], quality["top_bottom"]) < .04
    assert result.shape == image.shape


def test_direction_and_disabled_changes():
    image = texture()
    variants = generate_variants(image, 4, seed=3, direction=True, mirror=False,
        brightness=0, hue=0, saturation=0, contrast=0, translate=False)
    assert all(np.array_equal(v, image) or np.array_equal(v, np.rot90(image, 2)) for v in variants)


def stagger_source():
    y, x = np.mgrid[:128, :128]
    return np.stack((.5+.3*np.sin(2*np.pi*x/128), .5+.3*np.cos(2*np.pi*y/128),
                     .5+.2*np.sin(2*np.pi*(x+y)/128)), axis=-1).astype("float32")


def test_zero_stagger_preserves_every_source_pixel_in_four_by_four_output():
    source = stagger_source()
    result = stagger_tiles(source)
    np.testing.assert_allclose(result, np.tile(source, (4, 4, 1)), atol=1e-7)


def test_random_offsets_are_independent_bounded_and_scale_without_rerolling():
    low = random_tile_offsets(.2, .1, 17)
    high = random_tile_offsets(.8, .4, 17)
    np.testing.assert_allclose(high, low*4)
    assert (abs(high[..., 0]) <= .8).all() and (abs(high[..., 1]) <= .4).all()
    assert len(np.unique(high.reshape(-1, 2), axis=0)) == 16
    assert not np.array_equal(high, random_tile_offsets(.8, .4, 18))
    np.testing.assert_array_equal(random_tile_offsets(0, .5, 17)[..., 0], 0)


def test_each_material_marker_moves_independently_in_rendered_pixels():
    y, x = np.mgrid[:256, :256]
    spot = np.exp(-((x-127.5)**2+(y-127.5)**2)/(2*12**2))
    image = np.repeat(spot[..., None], 3, axis=-1).astype("float32")
    base = stagger_tiles(image, 0, 0, 17)
    low = stagger_tiles(image, .1, .1, 17)
    high = stagger_tiles(image, .3, .3, 17)
    def markers(render):
        count, labels, stats, centers = cv2.connectedComponentsWithStats((render[..., 0] > .7).astype("uint8"))
        assert count-1 == 16
        # Match each spot to its original grid position; jitter is < half a cell.
        order = np.argsort((centers[1:, 1]//256)*4+centers[1:, 0]//256)
        return centers[1:][order]
    original, small, large = markers(base), markers(low), markers(high)
    small_delta, large_delta = small-original, large-original
    assert np.unique(np.round(large_delta, 1), axis=0).shape[0] >= 12
    np.testing.assert_allclose(large_delta, small_delta*3, atol=1.5)
    assert np.abs(large_delta).max() <= 256*.3+1
    assert np.linalg.norm(large_delta) > 2*np.linalg.norm(small_delta)


@pytest.mark.parametrize("axis", [0, 1])
def test_random_axis_does_not_shift_other_coordinate(axis):
    source = stagger_source()
    base = stagger_tiles(source)
    result = stagger_tiles(source, .4 if axis == 0 else 0, .4 if axis == 1 else 0, 17)
    unaffected_channel = 1 if axis == 0 else 0
    np.testing.assert_allclose(result[..., unaffected_channel], base[..., unaffected_channel], atol=1e-6)
    assert not np.allclose(result, base)


@pytest.mark.parametrize("shape", [(128, 128), (95, 161), (4, 9)])
def test_combined_stagger_handles_rectangles_and_odd_sizes(shape):
    image = cv2.resize(stagger_source(), shape[::-1])
    result = stagger_tiles(image, .37, .28)
    assert result.shape == (image.shape[0]*4, image.shape[1]*4, 3)
    assert result.dtype == np.float32
    assert np.isfinite(result).all()
    assert 0 <= result.min() <= result.max() <= 1
    np.testing.assert_array_equal(result, stagger_tiles(image, .37, .28))


def test_random_repeat_has_continuous_edges_and_retains_detail():
    source = cv2.resize(stagger_source(), (512, 512), interpolation=cv2.INTER_CUBIC)
    result = stagger_tiles(source, .5, .5)
    quality = seam_quality(result)
    assert max(quality["left_right"], quality["top_bottom"]) < .035
    assert result.std() > .15
    half_h, half_w = result.shape[0]//2, result.shape[1]//2
    assert not np.allclose(result[:half_h], result[half_h:])
    assert not np.allclose(result[:, :half_w], result[:, half_w:])


def test_maximum_random_offsets_fill_all_pixels_without_dark_gaps():
    source = np.full((161, 257, 3), [.2, .5, .8], dtype="float32")
    result = stagger_tiles(source, 1, 1, 123)
    np.testing.assert_allclose(result, np.tile(source, (4, 4, 1)), atol=1e-6)


def test_random_layout_can_be_cancelled_between_blocks():
    def cancelled(value):
        raise InterruptedError("已取消")
    with pytest.raises(InterruptedError, match="已取消"):
        stagger_tiles(stagger_source(), .5, .5, progress=cancelled)


@pytest.mark.parametrize("x,y", [(1.1, 0), (0, -.1), (float("nan"), 0)])
def test_stagger_rejects_invalid_offsets(x, y):
    with pytest.raises(ValueError, match="隨機位移"):
        stagger_tiles(stagger_source(), x, y)


def test_native_random_layout_keeps_single_pixel_color_detail():
    y, x = np.mgrid[:32, :48]
    image = np.stack(((x % 2).astype("float32"), (y % 2).astype("float32"),
                       ((x+y) % 2).astype("float32")), axis=-1)
    result = stagger_tiles(image)
    assert result.shape == (128, 192, 3)
    np.testing.assert_allclose(result, np.tile(image, (4, 4, 1)), atol=1e-7)


def test_only_interactive_preview_can_request_a_smaller_layout():
    image = stagger_source()
    full = stagger_tiles(image, .2, .3, 42)
    preview = stagger_tiles(image, .2, .3, 42, output_size=(256, 256))
    assert full.shape == (512, 512, 3)
    assert preview.shape == (256, 256, 3)
    assert image.shape == (128, 128, 3)
