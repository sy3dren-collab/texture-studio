import json
import numpy as np
import pytest
from PIL import Image
from texture_studio.core import save_image
from texture_studio.cli import main


@pytest.mark.parametrize("mode", ["tile", "variants", "boards"])
def test_real_file_workflow(tmp_path, mode):
    path = tmp_path / "原始木板.png"
    save_image(np.random.default_rng(2).uniform(.3, .7, (32, 128, 3)).astype("float32"), path)
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"width":128,"height":64}), encoding="utf-8")
    target = tmp_path / mode
    main([mode, str(path), "--output", str(target), "--config", str(config), "--maps"])
    metadata = json.loads((target/"project.json").read_text(encoding="utf-8"))
    assert metadata["seed"] == 42
    assert metadata["outputs"]
    for name in metadata["outputs"]:
        with Image.open(target/name) as image:
            image.load()
            assert "icc_profile" in image.info if name == "base_color.png" else True
            if "normal_reference" in name:
                assert "icc_profile" not in image.info
    with pytest.raises(FileExistsError):
        main([mode, str(path), "--output", str(target), "--config", str(config)])
