"""Run with a 64-bit Windows Python 3.12; no production data is packaged."""
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    if sys.platform != "win32":
        raise SystemExit("请在 Windows 10/11 上运行，或使用 GitHub Actions 的 Windows package 工作流。")
    root = Path(__file__).resolve().parent
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onedir", "--windowed", "--name", "LensMatch",
        "--hidden-import", "openpyxl", "--hidden-import", "xlrd",
        "desktop.py",
    ], cwd=root, check=True)
    target = root / "dist" / "LensMatch"
    shutil.copy2(root / "config.json", target)
    shutil.copy2(root / "便携版使用说明.txt", target)
    shutil.copytree(root / "examples", target / "examples", dirs_exist_ok=True)
    (target / "input").mkdir(exist_ok=True)
    (target / "output").mkdir(exist_ok=True)
    archive = shutil.make_archive(str(root / "dist" / "LensMatch-Windows-x64"), "zip", root / "dist", "LensMatch")
    print(archive)


if __name__ == "__main__":
    main()
