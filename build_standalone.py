"""Build standalone shareable .exe distributables of WinCrate (Portable .exe + Setup .exe).

Produces zero-dependency Windows executables that run on any Windows 10 / Windows 11 PC
without requiring Python, pip, or external libraries on the target machine:
  1. WinCrate_Portable.exe    — Single-file portable app (double-click to run directly)
  2. WinCrate_1.0.0_Setup.exe — Standalone Windows installer with shortcuts & Uninstaller
"""

from __future__ import annotations

import hashlib
import importlib.metadata as importlib_md
import os
import shutil
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wincrate.builder import (
    MAGIC_FOOTER,
    BuildRequest,
    PackageBuilder,
    find_csc_compiler,
    get_free_bytes,
    pick_best_default_output_dir,
)
from wincrate.scanner import SoftwareScanner

RUNTIME_DIST_NAMES = [
    "pywebview",
    "pythonnet",
    "clr-loader",
    "proxy-tools",
    "bottle",
    "pillow",
    "cffi",
    "pycparser",
    "typing_extensions",
]

SKIP_DLL_PREFIXES = (
    "tcl",
    "tk",
    "_tkinter",
    "sqlite3",
    "_sqlite3",
    "_test",
    "_ctypes_test",
)

SKIP_STDLIB_DIRS = {
    "site-packages",
    "__pycache__",
    "test",
    "tests",
    "idlelib",
    "tkinter",
    "turtledemo",
    "ensurepip",
    "pydoc_data",
    "venv",
    "sqlite3",
    "dbm",
}

SKIP_PIL_BINARIES = (
    "_avif",
    "_imagingft",
    "_webp",
    "_imagingcms",
)


def _copy_tree_filtered(src: Path, dst: Path, skip_dirs: set[str] | None = None) -> None:
    skip_dirs = skip_dirs or set()
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in skip_dirs and d != "__pycache__"]
        rel_dir = Path(root).relative_to(src)
        target_dir = dst / rel_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        for fname in files:
            if fname.endswith((".pyc", ".pyo", ".pdb", ".lib")):
                continue
            if src.name == "PIL" and fname.startswith(SKIP_PIL_BINARIES):
                continue
            shutil.copy2(Path(root) / fname, target_dir / fname)


def assemble_embedded_runtime(runtime_dst: Path) -> None:
    """Create a lean, isolated Python 3.x runtime with pywebview + pythonnet + Pillow."""
    py_base = Path(sys.base_prefix)
    runtime_dst.mkdir(parents=True, exist_ok=True)

    # 1. Core interpreter binaries & VC++ runtime DLLs
    for fname in os.listdir(py_base):
        fpath = py_base / fname
        if not fpath.is_file():
            continue
        low = fname.lower()
        if low in ("python.exe", "pythonw.exe", "license.txt") or (
            low.endswith(".dll") and (low.startswith("python") or low.startswith("vcruntime"))
        ):
            shutil.copy2(fpath, runtime_dst / fname)

    # 2. Isolated ._pth file so host PYTHONPATH / PYTHONHOME / Registry never interfere
    py_ver_tag = f"python{sys.version_info.major}{sys.version_info.minor}"
    pth_file = runtime_dst / f"{py_ver_tag}._pth"
    pth_file.write_text(
        ".\nDLLs\nLib\nLib\\site-packages\n..\\app\nimport site\n",
        encoding="utf-8",
    )

    # 3. Extension modules & native DLLs (libffi, ctypes, socket, ssl, hashlib, etc.)
    dlls_src = py_base / "DLLs"
    dlls_dst = runtime_dst / "DLLs"
    dlls_dst.mkdir(parents=True, exist_ok=True)
    for item in dlls_src.iterdir():
        if not item.is_file():
            continue
        low = item.name.lower()
        if low.endswith((".pdb", ".lib", ".ico")):
            continue
        if any(low.startswith(prefix) for prefix in SKIP_DLL_PREFIXES):
            continue
        shutil.copy2(item, dlls_dst / item.name)

    # 4. Standard library
    lib_src = py_base / "Lib"
    lib_dst = runtime_dst / "Lib"
    _copy_tree_filtered(lib_src, lib_dst, skip_dirs=SKIP_STDLIB_DIRS)

    # 5. Exact site-packages closure
    sp_src = lib_src / "site-packages"
    sp_dst = lib_dst / "site-packages"
    sp_dst.mkdir(parents=True, exist_ok=True)

    copied_top: set[str] = set()
    for dist_name in RUNTIME_DIST_NAMES:
        try:
            dist = importlib_md.distribution(dist_name)
        except importlib_md.PackageNotFoundError:
            continue
        for f in dist.files or []:
            top = str(f).replace("\\", "/").split("/")[0]
            if not top or top in ("..", "__pycache__") or top in copied_top:
                continue
            copied_top.add(top)
            src_entry = sp_src / top
            dst_entry = sp_dst / top
            if src_entry.is_dir():
                _copy_tree_filtered(src_entry, dst_entry)
            elif src_entry.is_file():
                shutil.copy2(src_entry, dst_entry)


def assemble_app_bundle(bundle_dir: Path, csc_path: str) -> None:
    """Populate bundle_dir with WinCrate.exe launcher, runtime/, and app/."""
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    print("[1/4] Assembling isolated Python + WebView2 runtime...")
    assemble_embedded_runtime(bundle_dir / "runtime")

    print("[2/4] Copying WinCrate application & UI assets...")
    app_dst = bundle_dir / "app"
    app_dst.mkdir(parents=True, exist_ok=True)
    for fname in ("app.py", "DESIGN.md", "README.md"):
        src = PROJECT_ROOT / fname
        if src.is_file():
            shutil.copy2(src, app_dst / fname)

    _copy_tree_filtered(PROJECT_ROOT / "ui", app_dst / "ui")
    _copy_tree_filtered(PROJECT_ROOT / "wincrate", app_dst / "wincrate")

    # Compile bundle_dir/WinCrate.exe (native GUI launcher pointing to ./runtime/pythonw.exe)
    launcher_cs = PROJECT_ROOT / "wincrate" / "launcher.cs"
    ico_path = PROJECT_ROOT / "wincrate" / "wincrate.ico"
    launcher_exe = bundle_dir / "WinCrate.exe"

    cmd = [
        csc_path,
        "/nologo",
        "/target:winexe",
        "/optimize+",
        f"/out:{launcher_exe}",
        f"/win32icon:{ico_path}",
        "/r:System.dll",
        "/r:System.Windows.Forms.dll",
        str(launcher_cs),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not launcher_exe.is_file():
        raise RuntimeError(f"Failed to compile WinCrate.exe launcher:\n{res.stdout}\n{res.stderr}")


def build_portable_single_exe(bundle_dir: Path, out_exe: Path, stage_dir: Path, csc_path: str) -> str:
    """Compile portable_stub.cs and append compressed runtime/ + app/ payload."""
    print(f"[3/4] Building single-file portable executable -> {out_exe} ...")
    stub_cs = PROJECT_ROOT / "wincrate" / "portable_stub.cs"
    ico_path = PROJECT_ROOT / "wincrate" / "wincrate.ico"
    stub_exe = stage_dir / "portable_stub_raw.exe"

    cmd = [
        csc_path,
        "/nologo",
        "/target:winexe",
        "/optimize+",
        f"/out:{stub_exe}",
        f"/win32icon:{ico_path}",
        "/r:System.dll",
        "/r:System.Drawing.dll",
        "/r:System.IO.Compression.dll",
        "/r:System.Windows.Forms.dll",
        str(stub_cs),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not stub_exe.is_file():
        raise RuntimeError(f"Failed to compile portable_stub.cs:\n{res.stdout}\n{res.stderr}")

    payload_zip = stage_dir / "portable_payload.zip"
    with zipfile.ZipFile(payload_zip, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for sub in ("runtime", "app"):
            sub_root = bundle_dir / sub
            for root, _, files in os.walk(sub_root):
                for fname in files:
                    fpath = Path(root) / fname
                    arcname = fpath.relative_to(bundle_dir).as_posix()
                    zf.write(fpath, arcname=arcname)

    tmp_out = out_exe.with_suffix(".exe.part")
    shutil.copy2(stub_exe, tmp_out)
    payload_offset = tmp_out.stat().st_size

    with open(tmp_out, "ab") as dst, open(payload_zip, "rb") as src:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
        dst.write(struct.pack("<q8s", payload_offset, MAGIC_FOOTER))

    if out_exe.exists():
        out_exe.unlink()
    tmp_out.replace(out_exe)
    payload_zip.unlink(missing_ok=True)

    h = hashlib.sha256()
    with open(out_exe, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def build_installer_setup_exe(bundle_dir: Path, out_dir: Path) -> Path:
    """Use WinCrate's own PackageBuilder to build WinCrate_1.0.0_Setup.exe."""
    print(f"[4/4] Building standalone Setup Wizard installer in {out_dir} ...")
    scanner = SoftwareScanner()
    summary = scanner.register_custom_folder(str(bundle_dir))
    app_id = summary["id"]

    builder = PackageBuilder(scanner)
    req = BuildRequest(
        app_id=app_id,
        package_name="WinCrate",
        package_version="1.0.0",
        publisher="WinCrate",
        install_location=str(bundle_dir),
        main_exe_rel="WinCrate.exe",
        output_dir=str(out_dir),
        output_filename="WinCrate_1.0.0_Setup.exe",
        include_appdata=False,
        exclude_appdata_cache=True,
        include_registry=False,
        desktop_shortcut=True,
        start_menu_shortcut=True,
    )
    job = builder.start_build(req)
    while True:
        st = builder.get_job(job.job_id)
        if not st:
            raise RuntimeError("Lost build job state")
        if st.status in ("done", "completed"):
            return Path(st.output_path)
        if st.status in ("error", "failed", "cancelled"):
            raise RuntimeError(f"Setup installer build failed: {st.error}")
        time.sleep(0.25)


def main() -> int:
    t0 = time.perf_counter()
    out_dir = Path(pick_best_default_output_dir())
    out_dir.mkdir(parents=True, exist_ok=True)
    csc_path = find_csc_compiler()

    stage_root = out_dir / ".standalone_stage"
    bundle_dir = stage_root / "WinCrate"
    try:
        assemble_app_bundle(bundle_dir, csc_path)

        portable_exe = out_dir / "WinCrate_Portable.exe"
        portable_sha = build_portable_single_exe(bundle_dir, portable_exe, stage_root, csc_path)

        setup_exe = build_installer_setup_exe(bundle_dir, out_dir)

        # Also update root WinCrate.exe if C: has comfortable free space (>= 120 MB remaining)
        root_exe = PROJECT_ROOT / "WinCrate.exe"
        p_size = portable_exe.stat().st_size
        if get_free_bytes(str(PROJECT_ROOT)) - p_size >= 120 * 1024 * 1024:
            shutil.copy2(portable_exe, root_exe)
            print(f"Updated root {root_exe} to standalone portable executable.")

        elapsed = time.perf_counter() - t0
        print("\n=== Standalone Build Complete ===")
        print(f"Portable single-file .exe : {portable_exe} ({p_size / (1024*1024):.2f} MB, sha256={portable_sha[:16]})")
        print(f"Setup Wizard .exe         : {setup_exe} ({setup_exe.stat().st_size / (1024*1024):.2f} MB)")
        print(f"Completed in {elapsed:.1f}s")
        return 0
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
