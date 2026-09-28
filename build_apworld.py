#!/usr/bin/env python3
"""Build the native DLLs and package feeding_frenzy_2.apworld into build/.

Steps:
  1. Configure + build native/ with CMake (clang-cl cross toolchain on Linux,
     Visual Studio Win32 on Windows).
  2. Copy dsound.dll and ff2ap_hooks.dll into feeding_frenzy_2/native/.
  3. Zip feeding_frenzy_2/ (minus caches) into build/feeding_frenzy_2.apworld.

Usage:
  python build_apworld.py               # full build
  python build_apworld.py --skip-native # package the DLLs already in feeding_frenzy_2/native
  python build_apworld.py --clean       # wipe the native build dir before building
"""
import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORLD_NAME = "feeding_frenzy_2"
WORLD_DIR = ROOT / WORLD_NAME
NATIVE_SRC = ROOT / "native"
NATIVE_ASSET_DIR = WORLD_DIR / "native"
OUT_DIR = ROOT / "build"
DLL_NAMES = ("dsound.dll", "ff2ap_hooks.dll")
EXCLUDE_DIRS = {"__pycache__"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def run(cmd):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def build_native(clean: bool) -> Path:
    """Build the DLLs and return the directory containing them."""
    if sys.platform == "win32":
        build_dir = NATIVE_SRC / "build"
        configure = ["cmake", "-S", NATIVE_SRC, "-B", build_dir, "-A", "Win32"]
        bin_dir = build_dir / "bin" / "Release"
    else:
        build_dir = NATIVE_SRC / "build-linux"
        configure = ["cmake", "-S", NATIVE_SRC, "-B", build_dir, "-G", "Ninja",
                     "-DCMAKE_TOOLCHAIN_FILE=cmake/clang-cl-win32.cmake",
                     "-DCMAKE_BUILD_TYPE=Release"]
        bin_dir = build_dir / "bin"

    if clean and build_dir.exists():
        shutil.rmtree(build_dir)
    if not (build_dir / "CMakeCache.txt").exists():
        run(configure)
    run(["cmake", "--build", build_dir, "--config", "Release"])
    return bin_dir


def copy_dlls(bin_dir: Path) -> None:
    NATIVE_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for name in DLL_NAMES:
        src = bin_dir / name
        if not src.is_file():
            sys.exit(f"error: expected build output missing: {src}")
        shutil.copy2(src, NATIVE_ASSET_DIR / name)
        print(f"copied {src.relative_to(ROOT)} -> {(NATIVE_ASSET_DIR / name).relative_to(ROOT)}")


def package() -> Path:
    for name in DLL_NAMES:
        if not (NATIVE_ASSET_DIR / name).is_file():
            sys.exit(f"error: {NATIVE_ASSET_DIR / name} missing; build without --skip-native")

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"{WORLD_NAME}.apworld"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(WORLD_DIR.rglob("*")):
            rel = path.relative_to(ROOT)
            if not path.is_file() or EXCLUDE_DIRS.intersection(rel.parts) \
                    or path.suffix in EXCLUDE_SUFFIXES:
                continue
            zf.write(path, rel.as_posix())
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-native", action="store_true",
                        help="don't build the DLLs; package the ones already in feeding_frenzy_2/native")
    parser.add_argument("--clean", action="store_true",
                        help="delete the native build directory before building")
    args = parser.parse_args()

    if not args.skip_native:
        copy_dlls(build_native(args.clean))
    out = package()

    with zipfile.ZipFile(out) as zf:
        for info in zf.infolist():
            print(f"  {info.file_size:>8}  {info.filename}")
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
