"""Headless processing interface, sharing the desktop's real algorithms."""
import argparse
from dataclasses import fields
import json
from pathlib import Path
from . import __version__
from .core import load_image, save_image, correct_lighting, seamless
from .variants import generate_variants
from .boards import BoardSettings, generate_boards
from .maps import derive_maps


def main(argv=None):
    parser = argparse.ArgumentParser(description="Texture Studio 本機批次處理")
    parser.add_argument("mode", choices=["tile", "variants", "boards"])
    parser.add_argument("images", nargs="+")
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", help="JSON object with BoardSettings fields")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--maps", action="store_true")
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    images = [load_image(path) for path in args.images]
    metadata = {"version": __version__, "inputs": args.images, "seed": args.seed,
                "map_notice": "Height, Roughness, Normal are RGB-derived references, not measured PBR.",
                "base_color_space": "sRGB", "data_color_space": "linear/non-color"}
    if args.mode == "boards":
        settings = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else {}
        unknown = settings.keys()-{field.name for field in fields(BoardSettings)}
        if unknown:
            raise ValueError(f"Unknown board settings: {unknown}")
        settings["seed"] = args.seed
        config = BoardSettings(**settings)
        outputs = generate_boards(images, config)
        metadata["boards"] = config.metadata()
    else:
        tile = seamless(correct_lighting(images[0]))
        if args.mode == "tile":
            outputs = {"base_color": tile}
        else:
            outputs = {f"variant_{i:02d}": image for i, image in enumerate(generate_variants(tile, args.count, args.seed))}
        metadata.update(lighting_strength=.85, lighting_radius=.1, preserve_contrast=.7, seam_strength=1)
    if args.maps:
        for name, image in list(outputs.items()):
            if name == "base_color" or name.startswith("variant_"):
                maps = derive_maps(image, outputs.get("height_reference"))
                prefix = "" if name == "base_color" else name+"_"
                outputs.update({prefix+key: value for key, value in maps.items()})
    paths = [output / f"{name}.png" for name in outputs]
    paths.append(output / "project.json")
    if any(path.exists() for path in paths):
        raise FileExistsError("輸出已存在；請使用新的輸出資料夾")
    if {path.resolve() for path in paths} & {Path(path).resolve() for path in args.images}:
        raise ValueError("不可覆寫原始素材")
    for (name, image), path in zip(outputs.items(), paths):
        save_image(image, path, "sRGB" if name == "base_color" or (name.startswith("variant_") and "reference" not in name) else "linear")
    metadata["outputs"] = [path.name for path in paths[:-1]]
    paths[-1].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已輸出 {len(outputs)} 張貼圖與專案資訊")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
