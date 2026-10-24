"""Build and validate one portable Windows GUI executable."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET


def command(*args, env=None):
    subprocess.run([sys.executable, *args], check=True, env=env)


def main():
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise SystemExit("Build on 64-bit Windows with Python 3.12; this script does not cross-compile.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--allow-wine", action="store_true", help="Build under Wine and explicitly label compatibility-layer validation")
    args = parser.parse_args()
    try:
        ctypes.windll.ntdll.wine_get_version
        wine = True
    except AttributeError:
        wine = False
    if wine and not args.allow_wine:
        raise SystemExit("Wine requires --allow-wine; results must not be described as native Windows verification.")
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    command("-m", "pip", "--disable-pip-version-check", "install", "-r", str(root / "requirements-dev.txt"))
    test_env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    junit = output / "pytest.xml"
    command("-m", "pytest", "-q", f"--junitxml={junit}", env=test_env)
    suites = ET.parse(junit).getroot().findall("testsuite")
    test_results = {key: sum(int(suite.get(key, 0)) for suite in suites) for key in ("tests", "failures", "errors", "skipped")}
    test_results["passed"] = test_results["tests"]-test_results["failures"]-test_results["errors"]-test_results["skipped"]
    if test_results["passed"] <= 0:
        raise RuntimeError("No successful Windows tests were recorded")
    # Read the dependency-free version module without importing GUI packages.
    version_scope = {}
    exec((root / "texture_studio" / "__init__.py").read_text(encoding="utf-8"), version_scope)
    version = version_scope["__version__"]
    numbers = tuple(int(part) for part in version.split("."))+(0,)
    metadata = output / "version.txt"
    metadata.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers!r}, prodvers={numbers!r}, mask=0x3f,
    flags=0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('FileDescription', 'Texture Studio'),
    StringStruct('FileVersion', '{version}'),
    StringStruct('ProductName', 'Texture Studio'),
    StringStruct('ProductVersion', '{version}'),
    StringStruct('OriginalFilename', 'TextureStudio.exe')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")
    command("-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--noupx",
            "--name", "TextureStudio", "--collect-submodules", "texture_studio", "--exclude-module", "pytest",
            "--version-file", str(metadata), "--distpath", str(output / "dist"),
            "--workpath", str(output / "build"), "--specpath", str(output), str(root / "launch.py"))
    executable = output / "dist" / "TextureStudio.exe"
    with executable.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise RuntimeError("Output is not a Windows executable")
        stream.seek(0x3c)
        pe = struct.unpack("<I", stream.read(4))[0]
        stream.seek(pe)
        if stream.read(4) != b"PE\x00\x00" or struct.unpack("<H", stream.read(2))[0] != 0x8664:
            raise RuntimeError("Output is not Windows x64")
        stream.seek(pe+24+68)
        if struct.unpack("<H", stream.read(2))[0] != 2:
            raise RuntimeError("Executable is not a windowed GUI application")
    # Launch ONLY the EXE from a different directory with source/Python paths
    # removed. This proves it can load bundled Qt, OpenCV, NumPy and Pillow.
    with tempfile.TemporaryDirectory(prefix="Texture Studio 獨立測試 ", ignore_cleanup_errors=True) as isolated:
        isolated = Path(isolated)
        portable = isolated / executable.name
        shutil.copy2(executable, portable)
        smoke_output = isolated / "檢查結果"
        smoke_env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "PYTHONHOME")}
        system_root = os.environ["SystemRoot"]
        smoke_env["PATH"] = str(Path(system_root) / "System32")+os.pathsep+system_root
        smoke_env["QT_QPA_PLATFORM"] = "windows"
        process = subprocess.Popen([str(portable), "--smoke-test", str(smoke_output)], cwd=isolated, env=smoke_env)
        try:
            code = process.wait(timeout=120)
        except subprocess.TimeoutExpired as error:
            # Kill only the build's own onefile parent/child processes.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False)
            raise RuntimeError("Standalone EXE did not finish its checks within 120 seconds") from error
        if code != 0:
            raise RuntimeError(f"Standalone EXE failed with exit code {code}")
        report = json.loads((smoke_output / "smoke.json").read_text(encoding="utf-8"))
        if not report["frozen"] or report["platform"] != "win32" or report["console_window"] != 0 or report["qt_platform"] != "windows":
            raise RuntimeError("Standalone GUI validation failed")
    release = output / "release"
    release.mkdir(exist_ok=True)
    shutil.copy2(executable, release / executable.name)
    checksum = hashlib.sha256(executable.read_bytes()).hexdigest()
    report.update(test_suite=test_results, architecture="x64", subsystem="GUI", sha256=checksum,
                  native_windows_verified=not wine)
    (release / "TextureStudio.exe.sha256").write_text(f"{checksum}  TextureStudio.exe\n", encoding="ascii")
    (release / "windows-validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with zipfile.ZipFile(release / "TextureStudio-Windows-x64.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(executable, executable.name)
        archive.writestr("使用說明.txt", "完整解壓縮後，雙擊 TextureStudio.exe。\n不需要安裝 Python，啟動不顯示終端機。\n錯誤紀錄位於 %LOCALAPPDATA%\\TextureStudio\\logs。\n")
    print(json.dumps({"version": version, "sha256": checksum, "release": str(release), "standalone_smoke": "passed"}))


if __name__ == "__main__":
    main()
