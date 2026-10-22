import numpy as np
import pytest
from texture_studio.boards import BoardSettings, generate_boards


@pytest.mark.parametrize("pattern", ["straight", "half", "third", "quarter", "random", "variable", "custom"])
def test_layout_reproducible_and_masks(pattern):
    config = BoardSettings(width=256, height=128, pattern=pattern)
    images = [np.full((16, 64, 3), value, "float32") for value in (.3, .6, .8)]
    a, b = generate_boards(images, config), generate_boards(images, config)
    assert a["base_color"].shape == (128, 256, 3)
    assert all(np.array_equal(a[key], b[key]) for key in a)
    assert a["gap_mask"].max() > 0
    assert a["gap_mask"].min() == 0
    assert np.isfinite(a["height_reference"]).all()


def test_periodicity_and_incompatible_rejection():
    # Random offsets place the wrap inside a board, not at a legitimate joint.
    config = BoardSettings(width=256, height=128, gap_mm=0, pattern="random")
    images = [np.full((16, 64, 3), .5, "float32")]
    result = generate_boards(images, config)["base_color"]
    assert np.max(abs(result[:, 0] - result[:, -1])) < 1e-6
    with pytest.raises(ValueError, match="週期"):
        generate_boards(images, BoardSettings(world_width_mm=3500))


def test_no_source_mutation():
    image = np.random.default_rng(0).random((32, 128, 3), dtype=np.float32)
    original = image.copy()
    generate_boards([image], BoardSettings(width=64, height=64))
    np.testing.assert_array_equal(image, original)
