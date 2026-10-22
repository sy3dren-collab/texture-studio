import numpy as np
import pytest
from texture_studio.boards import BoardSettings, generate_boards


@pytest.mark.parametrize("pattern", ["herringbone", "chevron", "basketweave"])
def test_special_layout_is_covered_deterministic_and_periodic(pattern):
    image = np.full((32, 192, 3), .5, "float32")
    c = BoardSettings(width=512, height=256, pattern=pattern, brightness=0)
    a = generate_boards([image], c)
    b = generate_boards([image], c)
    assert np.all(a["base_color"] > 0)
    assert all(np.array_equal(a[key], b[key]) for key in a)
    # Two fundamental periods horizontally must repeat, including grout.
    np.testing.assert_allclose(a["base_color"][:, :256], a["base_color"][:, 256:], atol=1e-6)
    assert a["gap_mask"].max() > .1


def test_special_rejects_incompatible_period():
    with pytest.raises(ValueError, match="週期"):
        generate_boards([np.ones((16, 64, 3), "float32")], BoardSettings(pattern="herringbone", world_height_mm=1600))
