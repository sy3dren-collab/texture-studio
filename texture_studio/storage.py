"""Explicit, atomic replacement of a user-selected source image."""
import os
from pathlib import Path
import stat
import tempfile
from PIL import Image
from .core import save_image, validate


def file_signature(path):
    value = Path(path).stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def replace_source(image, path, expected_signature, repeat=1):
    validate(image)
    target = Path(path).resolve(strict=True)
    if file_signature(target) != expected_signature:
        raise OSError("原檔案已在外部變更，未覆蓋；請重新確認後儲存")
    original_mode = stat.S_IMODE(target.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".texture-save-", suffix=target.suffix, dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        # Keep the source intact until a complete, decodable image is ready.
        save_image(image, temporary, repeat=repeat)
        with Image.open(temporary) as check:
            check.load()
            if check.size != (image.shape[1]*repeat, image.shape[0]*repeat):
                raise OSError("儲存圖片尺寸不符，未覆蓋原檔")
        os.chmod(temporary, original_mode)
        if file_signature(target) != expected_signature:
            raise OSError("原檔案已在運算期間變更，未覆蓋")
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.chmod(stat.S_IREAD | stat.S_IWRITE)
            temporary.unlink()
