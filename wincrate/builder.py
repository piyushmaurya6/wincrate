"""Standalone .exe Installer Builder using Windows built-in C# compiler + PE-overlay ZIP streaming."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .icon_extractor import save_ico_file
from .scanner import CACHE_DIR_NAMES, InstalledAppRecord, SoftwareScanner, is_safe_app_folder

import ctypes
from ctypes import wintypes

MAGIC_FOOTER = b"WCRATE01"
DRIVE_FIXED = 3

_kernel32 = ctypes.windll.kernel32
_kernel32.GetLogicalDrives.argtypes = []
_kernel32.GetLogicalDrives.restype = wintypes.DWORD
_kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetDriveTypeW.restype = wintypes.UINT


def get_free_bytes(path: str) -> int:
    """Return free bytes available on the volume containing path."""
    try:
        probe = path if os.path.exists(path) else os.path.splitdrive(os.path.abspath(path))[0] + os.sep
        return shutil.disk_usage(probe).free
    except OSError:
        return 0


def pick_best_default_output_dir() -> str:
    """Prefer Downloads\\WinCrate_Packages when >= 1.5 GB free; otherwise pick largest fixed drive."""
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    dl_free = get_free_bytes(downloads)
    if dl_free >= int(1.5 * 1024**3):
        return os.path.join(downloads, "WinCrate_Packages")

    best_root = ""
    best_free = dl_free
    bitmask = _kernel32.GetLogicalDrives()
    for i in range(26):
        if bitmask & (1 << i):
            root = f"{chr(65 + i)}:\\"
            dtype = _kernel32.GetDriveTypeW(root)
            if dtype == DRIVE_FIXED:
                free = get_free_bytes(root)
                if free > best_free:
                    best_free = free
                    best_root = root

    if best_root and best_free > dl_free:
        return os.path.join(best_root, "WinCrate_Packages")
    return os.path.join(downloads, "WinCrate_Packages")


def find_csc_compiler() -> str:
    """Locate Windows' built-in .NET Framework C# compiler (csc.exe)."""
    windir = os.environ.get("SystemRoot", r"C:\Windows")
    candidates = [
        os.path.join(windir, r"Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
        os.path.join(windir, r"Microsoft.NET\Framework\v4.0.30319\csc.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise FileNotFoundError(
        "Windows built-in C# compiler (csc.exe) was not found under C:\\Windows\\Microsoft.NET\\Framework64\\v4.0.30319."
    )


@dataclass
class BuildRequest:
    app_id: str
    package_name: str
    package_version: str
    publisher: str
    install_location: str
    main_exe_rel: str
    output_dir: str
    output_filename: str
    include_appdata: bool = False
    exclude_appdata_cache: bool = True
    include_registry: bool = True
    desktop_shortcut: bool = True
    start_menu_shortcut: bool = True
    register_uninstaller: bool = True


@dataclass
class BuildJobState:
    job_id: str
    app_id: str
    package_name: str
    status: str = "running"  # "running", "done", "error", "cancelled"
    stage: str = "initializing"
    percent: int = 0
    message: str = "Preparing build..."
    output_path: str = ""
    output_bytes: int = 0
    sha256: str = ""
    files_packed: int = 0
    skipped_locked_files: int = 0
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    cancel_requested: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "app_id": self.app_id,
            "package_name": self.package_name,
            "status": self.status,
            "stage": self.stage,
            "percent": self.percent,
            "message": self.message,
            "output_path": self.output_path,
            "output_bytes": self.output_bytes,
            "sha256": self.sha256,
            "files_packed": self.files_packed,
            "skipped_locked_files": self.skipped_locked_files,
            "error": self.error,
            "elapsed_sec": round((self.finished_at or time.time()) - self.started_at, 1),
        }


class PackageBuilder:
    """Compiles standalone Windows Setup .exe installers from installed software directories."""

    def __init__(self, scanner: SoftwareScanner, default_output_dir: Optional[str] = None) -> None:
        self.scanner = scanner
        base_out = default_output_dir or pick_best_default_output_dir()
        self.output_dir = os.path.normpath(base_out)
        os.makedirs(self.output_dir, exist_ok=True)

        self._jobs: Dict[str, BuildJobState] = {}
        self._lock = threading.Lock()
        self._pkg_dir = Path(__file__).resolve().parent
        self._cached_uninstaller_bytes: Optional[bytes] = None

    def list_built_packages(self) -> List[Dict[str, Any]]:
        """List standalone .exe installers present in the current output directory."""
        os.makedirs(self.output_dir, exist_ok=True)
        items: List[Dict[str, Any]] = []
        try:
            for entry in os.scandir(self.output_dir):
                if entry.is_file() and entry.name.lower().endswith(".exe"):
                    st = entry.stat()
                    is_wincrate = False
                    try:
                        if st.st_size > 24:
                            with open(entry.path, "rb") as f:
                                f.seek(st.st_size - 8)
                                is_wincrate = f.read(8) == MAGIC_FOOTER
                    except OSError:
                        pass
                    items.append(
                        {
                            "filename": entry.name,
                            "path": entry.path,
                            "bytes": st.st_size,
                            "modified_ts": int(st.st_mtime),
                            "verified_wincrate": is_wincrate,
                        }
                    )
        except OSError:
            pass
        items.sort(key=lambda x: x["modified_ts"], reverse=True)
        return items

    def start_build(self, req: BuildRequest) -> BuildJobState:
        job_id = hashlib.sha1(f"{req.app_id}:{time.time()}".encode("utf-8")).hexdigest()[:10]
        job = BuildJobState(job_id=job_id, app_id=req.app_id, package_name=req.package_name)
        with self._lock:
            self._jobs[job_id] = job

        t = threading.Thread(target=self._run_build_worker, args=(job, req), daemon=True)
        t.start()
        return job

    def get_job(self, job_id: str) -> Optional[BuildJobState]:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.status == "running":
                job.cancel_requested = True
                return True
        return False

    def _compile_csharp(
        self,
        cs_path: Path,
        out_exe: Path,
        references: List[str],
        ico_path: Optional[Path] = None,
    ) -> None:
        csc = find_csc_compiler()
        cmd = [
            csc,
            "/nologo",
            "/optimize+",
            "/target:winexe",
            "/platform:anycpu",
            f"/out:{out_exe}",
        ]
        for ref in references:
            cmd.append(f"/r:{ref}")
        if ico_path and ico_path.is_file():
            cmd.append(f"/win32icon:{ico_path}")
        cmd.append(str(cs_path))

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=creationflags,
            timeout=60,
        )
        if proc.returncode != 0 or not out_exe.is_file():
            detail = (proc.stdout + "\n" + proc.stderr).strip()
            raise RuntimeError(f"C# stub compiler failed (exit {proc.returncode}): {detail}")

    def _get_uninstaller_bytes(self, temp_dir: Path) -> bytes:
        if self._cached_uninstaller_bytes is not None:
            return self._cached_uninstaller_bytes
        uninst_cs = self._pkg_dir / "uninstaller_template.cs"
        uninst_exe = temp_dir / "uninstaller_built.exe"
        self._compile_csharp(
            uninst_cs,
            uninst_exe,
            references=[
                "System.dll",
                "System.Core.dll",
                "System.Web.Extensions.dll",
                "System.Windows.Forms.dll",
            ],
        )
        data = uninst_exe.read_bytes()
        self._cached_uninstaller_bytes = data
        return data

    def _run_build_worker(self, job: BuildJobState, req: BuildRequest) -> None:
        try:
            if not is_safe_app_folder(req.install_location):
                raise ValueError(
                    "Application folder is missing or points to a protected Windows directory."
                )

            out_dir = os.path.normpath(req.output_dir or self.output_dir)
            os.makedirs(out_dir, exist_ok=True)
            fname = req.output_filename.strip()
            if not fname.lower().endswith(".exe"):
                fname += ".exe"
            fname = re.sub(r'[<>:"/\\|?*]+', "_", fname)
            final_exe_path = os.path.join(out_dir, fname)

            rec = self.scanner.get_record(req.app_id)

            # 1. Enumerate files to pack so progress is strictly determinate
            job.stage = "scanning"
            job.percent = 4
            job.message = "Indexing application files..."

            app_files: List[Tuple[str, str, int]] = []
            app_bytes = 0
            for dirpath, dirnames, filenames in os.walk(req.install_location):
                if job.cancel_requested:
                    raise InterruptedError("Build cancelled.")
                dirnames[:] = [
                    d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))
                ]
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    if os.path.islink(full):
                        continue
                    # Avoid packing a pre-existing target output .exe if output_dir were inside install_location
                    if os.path.normcase(full) == os.path.normcase(final_exe_path):
                        continue
                    try:
                        sz = os.stat(full).st_size
                        rel = os.path.relpath(full, req.install_location).replace("\\", "/")
                        app_files.append((full, f"app/{rel}", sz))
                        app_bytes += sz
                    except OSError:
                        continue

            if not app_files:
                raise ValueError("No readable files were found inside the selected application folder.")

            appdata_files: List[Tuple[str, str, int]] = []
            appdata_bytes = 0
            if req.include_appdata and rec is not None:
                job.message = "Indexing AppData configuration files..."
                ad_info = self.scanner.discover_appdata_folders(rec)
                for folder_item in ad_info.get("folders", []):
                    scope = folder_item["scope"]  # "Roaming" or "Local"
                    prefix = "appdata_roaming" if scope == "Roaming" else "appdata_local"
                    rel_root = folder_item["rel_path"].replace("\\", "/")
                    full_ad_dir = folder_item["full_path"]

                    for dirpath, dirnames, filenames in os.walk(full_ad_dir):
                        if job.cancel_requested:
                            raise InterruptedError("Build cancelled.")
                        dirnames[:] = [
                            d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))
                        ]
                        if req.exclude_appdata_cache:
                            dirnames[:] = [
                                d for d in dirnames if d.lower() not in CACHE_DIR_NAMES
                            ]
                        for fn in filenames:
                            full = os.path.join(dirpath, fn)
                            if os.path.islink(full):
                                continue
                            try:
                                sz = os.stat(full).st_size
                                sub_rel = os.path.relpath(full, full_ad_dir).replace("\\", "/")
                                arc_name = f"{prefix}/{rel_root}/{sub_rel}"
                                appdata_files.append((full, arc_name, sz))
                                appdata_bytes += sz
                            except OSError:
                                continue

            reg_entries: List[Dict[str, Any]] = []
            if req.include_registry and rec is not None:
                job.stage = "capturing_registry"
                job.percent = 10
                job.message = "Capturing application Registry keys..."
                reg_entries = self.scanner.capture_app_registry(rec)

            # Preflight disk space check on output volume (temporary build staging lives inside out_dir)
            total_raw_bytes = app_bytes + appdata_bytes
            # Need roughly ~1.2x raw size temporarily while binding payload.zip -> final .exe (minimum 32 MB)
            estimated_needed = max(32 * 1024 * 1024, int(total_raw_bytes * 1.15))
            avail_bytes = get_free_bytes(out_dir)
            if avail_bytes > 0 and avail_bytes < estimated_needed:
                drive_lbl = os.path.splitdrive(out_dir)[0] or out_dir
                avail_mb = avail_bytes // (1024 * 1024)
                need_mb = estimated_needed // (1024 * 1024)
                raise RuntimeError(
                    f"Not enough free disk space on {drive_lbl} ({avail_mb} MB free, ~{need_mb} MB required for staging). "
                    "Choose an output folder on another drive with more free space."
                )

            with tempfile.TemporaryDirectory(prefix=".wc_stage_", dir=out_dir) as tmp_str:
                tmp_dir = Path(tmp_str)

                # 2. Extract .ico & compile native Setup .exe stub
                job.stage = "compiling_stub"
                job.percent = 15
                job.message = "Compiling native Windows Setup .exe stub..."

                ico_path = tmp_dir / "app_icon.ico"
                icon_source = ""
                if req.main_exe_rel:
                    cand_main = os.path.join(req.install_location, req.main_exe_rel)
                    if os.path.isfile(cand_main):
                        icon_source = cand_main
                if not icon_source and rec and rec.icon_spec:
                    icon_source = rec.icon_spec

                has_ico = save_ico_file(icon_source, str(ico_path)) if icon_source else False

                stub_exe = tmp_dir / "setup_stub.exe"
                self._compile_csharp(
                    self._pkg_dir / "stub_template.cs",
                    stub_exe,
                    references=[
                        "System.dll",
                        "System.Core.dll",
                        "System.Drawing.dll",
                        "System.IO.Compression.dll",
                        "System.Web.Extensions.dll",
                        "System.Windows.Forms.dll",
                    ],
                    ico_path=ico_path if has_ico else None,
                )

                uninst_bytes = self._get_uninstaller_bytes(tmp_dir)

                # 3. Write 0-based ZIP archive, then append to Setup .exe stub as PE overlay
                job.stage = "archiving"
                job.percent = 22
                temp_payload_zip = tmp_dir / "payload.zip"
                temp_final_exe = tmp_dir / "package_building.exe"
                shutil.copyfile(stub_exe, temp_final_exe)
                payload_offset = temp_final_exe.stat().st_size

                all_to_pack = app_files + appdata_files
                total_bytes_to_pack = max(1, sum(x[2] for x in all_to_pack))
                packed_bytes_so_far = 0
                files_packed = 0
                skipped_locked = 0

                default_dir_name = Path(req.install_location).name or req.package_name
                manifest = {
                    "appName": req.package_name,
                    "appVersion": req.package_version or "1.0",
                    "publisher": req.publisher,
                    "mainExeRel": req.main_exe_rel.replace("\\", "/"),
                    "defaultDirName": default_dir_name,
                    "hasAppData": len(appdata_files) > 0,
                    "hasRegistry": len(reg_entries) > 0,
                    "defaultDesktopShortcut": req.desktop_shortcut,
                    "defaultStartMenuShortcut": req.start_menu_shortcut,
                    "defaultRegisterUninstaller": req.register_uninstaller,
                    "appBytes": app_bytes,
                    "appDataBytes": appdata_bytes,
                    "createdUtc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                }

                with zipfile.ZipFile(
                    temp_payload_zip,
                    mode="w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=5,
                    allowZip64=True,
                ) as zf:
                    zf.writestr("manifest.json", json.dumps(manifest, indent=2).encode("utf-8"))
                    zf.writestr("uninstaller.exe", uninst_bytes)
                    if reg_entries:
                        zf.writestr("registry.json", json.dumps(reg_entries).encode("utf-8"))

                    for idx, (src_full, arc_name, est_sz) in enumerate(all_to_pack):
                        if job.cancel_requested:
                            raise InterruptedError("Build cancelled.")
                        try:
                            zf.write(src_full, arcname=arc_name)
                            files_packed += 1
                        except (PermissionError, OSError):
                            skipped_locked += 1

                        packed_bytes_so_far += est_sz
                        if idx % 8 == 0 or idx == len(all_to_pack) - 1:
                            ratio = min(1.0, packed_bytes_so_far / total_bytes_to_pack)
                            job.percent = 22 + int(ratio * 66)
                            job.message = f"Compressing {os.path.basename(src_full)} ({files_packed}/{len(all_to_pack)})"

                job.stage = "appending_payload"
                job.percent = 90
                job.message = "Binding archive into standalone .exe..."
                with open(temp_final_exe, "ab") as exe_out, open(temp_payload_zip, "rb") as zip_in:
                    shutil.copyfileobj(zip_in, exe_out, length=1024 * 1024)
                    exe_out.write(struct.pack("<q", payload_offset))
                    exe_out.write(MAGIC_FOOTER)
                temp_payload_zip.unlink(missing_ok=True)

                if job.cancel_requested:
                    raise InterruptedError("Build cancelled.")

                # 4. Verify & compute SHA-256 + move into destination folder
                job.stage = "verifying"
                job.percent = 94
                job.message = "Verifying standalone .exe integrity..."

                h = hashlib.sha256()
                with open(temp_final_exe, "rb") as vf:
                    while True:
                        chunk = vf.read(1024 * 1024)
                        if not chunk:
                            break
                        h.update(chunk)
                    vf.seek(temp_final_exe.stat().st_size - 16)
                    chk_off, chk_magic = struct.unpack("<q8s", vf.read(16))
                    if chk_magic != MAGIC_FOOTER or chk_off != payload_offset:
                        raise RuntimeError("Footer verification failed on generated .exe.")

                shutil.move(str(temp_final_exe), final_exe_path)
                final_size = os.path.getsize(final_exe_path)

                job.output_path = final_exe_path
                job.output_bytes = final_size
                job.sha256 = h.hexdigest()
                job.files_packed = files_packed
                job.skipped_locked_files = skipped_locked
                job.percent = 100
                job.stage = "complete"
                job.status = "done"
                job.finished_at = time.time()
                job.message = f"Built {fname} ({files_packed} files packed)"

        except InterruptedError:
            job.status = "cancelled"
            job.stage = "cancelled"
            job.finished_at = time.time()
            job.message = "Build cancelled."
        except Exception as exc:
            job.status = "error"
            job.stage = "error"
            job.finished_at = time.time()
            job.error = str(exc)
            job.message = f"Build failed: {exc}"
