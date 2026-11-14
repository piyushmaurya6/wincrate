"""Windows Installed Software Scanner, .lnk Parser, Footprint & Registry Inspector."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import struct
import winreg
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .icon_extractor import get_icon_data_uri, parse_icon_spec

CACHE_DIR_NAMES: Set[str] = {
    "cache",
    "code cache",
    "gpucache",
    "dawncache",
    "dawnwebgpucache",
    "shadercache",
    "grshadercache",
    "crashpad",
    "crash reports",
    "crashes",
    "logs",
    "log",
    "temp",
    "tmp",
    "blob_storage",
    "service worker",
    "jumpListIcons",
    "jumplisticonsmostvisited",
    "jumplisticonsrecent",
    "squirreltemp",
    "update",
    "updates",
}

GENERIC_VENDOR_NAMES: Set[str] = {
    "microsoft",
    "microsoft corporation",
    "windows",
    "google",
    "apple",
    "adobe",
    "intel",
    "amd",
    "nvidia",
    "common files",
    "packages",
    "programs",
    "temp",
    "roaming",
    "local",
    "locallow",
}

UNINSTALLER_RE = re.compile(
    r"(unins\d*|uninstall.*|setup|installer|update|updater|crashpad_handler|createdump|elevate)\.exe$",
    re.IGNORECASE,
)


def _norm_path(p: str) -> str:
    if not p:
        return ""
    try:
        expanded = os.path.expandvars(p.strip().strip('"').strip("'"))
        return os.path.normcase(os.path.normpath(expanded))
    except Exception:
        return ""


def _build_forbidden_roots() -> Tuple[Set[str], List[str]]:
    """Return exact forbidden directory paths and forbidden prefixes (like C:\\Windows)."""
    exact: Set[str] = set()
    prefixes: List[str] = []

    win_dir = _norm_path(os.environ.get("SystemRoot", r"C:\Windows"))
    if win_dir:
        prefixes.append(win_dir)

    for env_key in (
        "ProgramFiles",
        "ProgramFiles(x86)",
        "ProgramW6432",
        "ProgramData",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "PUBLIC",
        "TEMP",
        "TMP",
    ):
        val = os.environ.get(env_key, "")
        if val:
            exact.add(_norm_path(val))

    local_app = os.environ.get("LOCALAPPDATA", "")
    if local_app:
        exact.add(_norm_path(os.path.join(local_app, "Programs")))
        exact.add(_norm_path(os.path.join(local_app, "Temp")))
        prefixes.append(_norm_path(os.path.join(local_app, "Microsoft", "WindowsApps")))

    prog_data = os.environ.get("ProgramData", r"C:\ProgramData")
    if prog_data:
        exact.add(_norm_path(os.path.join(prog_data, "Package Cache")))

    for pf_key in ("ProgramFiles", "ProgramFiles(x86)"):
        pf = os.environ.get(pf_key, "")
        if pf:
            exact.add(_norm_path(os.path.join(pf, "Common Files")))
            prefixes.append(_norm_path(os.path.join(pf, "WindowsApps")))

    # Drive roots A:\ .. Z:\
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        exact.add(_norm_path(f"{ch}:\\"))

    return exact, prefixes


_FORBIDDEN_EXACT, _FORBIDDEN_PREFIXES = _build_forbidden_roots()


def is_safe_app_folder(folder: str) -> bool:
    """Verify folder is a dedicated application directory, never a system or shared root."""
    if not folder:
        return False
    norm = _norm_path(folder)
    if not norm or not os.path.isdir(folder):
        return False
    if norm in _FORBIDDEN_EXACT:
        return False
    for pref in _FORBIDDEN_PREFIXES:
        if norm == pref or norm.startswith(pref + os.sep):
            return False
    # Must be at least depth 2 from drive root (e.g. C:\Apps\MyApp or C:\PortableTool)
    parts = Path(norm).parts
    if len(parts) < 2:
        return False
    return True


def parse_lnk_file(lnk_path: str) -> Optional[Dict[str, str]]:
    """Fast binary [MS-SHLLINK] parser extracting target_path, arguments, working_dir, icon."""
    try:
        with open(lnk_path, "rb") as f:
            data = f.read(65536)
        if len(data) < 0x4C:
            return None
        hdr_size, link_flags = struct.unpack_from("<II", data, 0)
        if hdr_size != 0x4C:
            return None
        # Note: link_flags is actually at offset 0x14 (after 4-byte HeaderSize + 16-byte CLSID)
        link_flags = struct.unpack_from("<I", data, 0x14)[0]
        offset = 0x4C

        # HasLinkTargetIDList (0x01)
        if link_flags & 0x01:
            if offset + 2 > len(data):
                return None
            id_list_size = struct.unpack_from("<H", data, offset)[0]
            offset += 2 + id_list_size

        target_path = ""
        # HasLinkInfo (0x02)
        if link_flags & 0x02:
            if offset + 28 > len(data):
                return None
            li_size, li_hdr_size, li_flags = struct.unpack_from("<III", data, offset)
            if li_flags & 0x01:  # VolumeIDAndLocalBasePath
                local_base_off = struct.unpack_from("<I", data, offset + 16)[0]
                common_sfx_off = struct.unpack_from("<I", data, offset + 24)[0]
                if li_hdr_size >= 0x24 and offset + 36 <= len(data):
                    u_base_off, u_sfx_off = struct.unpack_from("<II", data, offset + 28)
                    if u_base_off:
                        pos = offset + u_base_off
                        end = data.find(b"\x00\x00", pos)
                        if end != -1:
                            if (end - pos) % 2 == 1:
                                end += 1
                            base_s = data[pos:end].decode("utf-16-le", errors="ignore")
                            sfx_s = ""
                            if u_sfx_off:
                                sp = offset + u_sfx_off
                                se = data.find(b"\x00\x00", sp)
                                if se != -1:
                                    if (se - sp) % 2 == 1:
                                        se += 1
                                    sfx_s = data[sp:se].decode("utf-16-le", errors="ignore")
                            target_path = base_s + sfx_s
                if not target_path and local_base_off:
                    pos = offset + local_base_off
                    end = data.find(b"\x00", pos)
                    if end != -1:
                        base_s = data[pos:end].decode("mbcs", errors="ignore")
                        sfx_s = ""
                        if common_sfx_off:
                            sp = offset + common_sfx_off
                            se = data.find(b"\x00", sp)
                            if se != -1:
                                sfx_s = data[sp:se].decode("mbcs", errors="ignore")
                        target_path = base_s + sfx_s
            offset += li_size

        is_unicode = bool(link_flags & 0x80)

        def _read_string_data(cur: int) -> Tuple[str, int]:
            if cur + 2 > len(data):
                return "", cur
            count = struct.unpack_from("<H", data, cur)[0]
            cur += 2
            if is_unicode:
                byte_len = count * 2
                s = data[cur : cur + byte_len].decode("utf-16-le", errors="ignore")
                return s, cur + byte_len
            else:
                s = data[cur : cur + count].decode("mbcs", errors="ignore")
                return s, cur + count

        name_str = rel_path = work_dir = args_str = icon_loc = ""
        if link_flags & 0x04:  # HasName
            name_str, offset = _read_string_data(offset)
        if link_flags & 0x08:  # HasRelativePath
            rel_path, offset = _read_string_data(offset)
        if link_flags & 0x10:  # HasWorkingDir
            work_dir, offset = _read_string_data(offset)
        if link_flags & 0x20:  # HasArguments
            args_str, offset = _read_string_data(offset)
        if link_flags & 0x40:  # HasIconLocation
            icon_loc, offset = _read_string_data(offset)

        if not target_path and rel_path:
            candidate = os.path.normpath(os.path.join(os.path.dirname(lnk_path), rel_path))
            if os.path.exists(candidate):
                target_path = candidate

        if target_path:
            target_path = os.path.expandvars(target_path)

        return {
            "lnk_path": lnk_path,
            "name": Path(lnk_path).stem,
            "description": name_str,
            "target_path": target_path,
            "working_dir": os.path.expandvars(work_dir) if work_dir else "",
            "arguments": args_str,
            "icon_location": os.path.expandvars(icon_loc) if icon_loc else "",
        }
    except Exception:
        return None


def _collect_all_shortcuts() -> List[Dict[str, str]]:
    roots: List[str] = []
    for env_key, rel in (
        ("ProgramData", r"Microsoft\Windows\Start Menu\Programs"),
        ("APPDATA", r"Microsoft\Windows\Start Menu\Programs"),
        ("USERPROFILE", "Desktop"),
        ("PUBLIC", "Desktop"),
    ):
        base = os.environ.get(env_key, "")
        if base:
            full = os.path.join(base, rel)
            if os.path.isdir(full):
                roots.append(full)

    shortcuts: List[Dict[str, str]] = []
    for root_dir in roots:
        is_desktop = root_dir.lower().endswith("desktop")
        for dirpath, _, filenames in os.walk(root_dir):
            for fn in filenames:
                if fn.lower().endswith(".lnk"):
                    parsed = parse_lnk_file(os.path.join(dirpath, fn))
                    if parsed and parsed.get("target_path"):
                        parsed["location_kind"] = "desktop" if is_desktop else "start_menu"
                        shortcuts.append(parsed)
    return shortcuts


def _extract_exe_from_command(cmd: str) -> str:
    if not cmd:
        return ""
    s = os.path.expandvars(cmd.strip())
    if s.startswith('"'):
        end = s.find('"', 1)
        if end != -1:
            cand = s[1:end]
            if cand.lower().endswith(".exe") and os.path.isfile(cand):
                return cand
    lower = s.lower()
    idx = lower.find(".exe")
    if idx != -1:
        cand = s[: idx + 4].strip('"')
        if os.path.isfile(cand):
            return cand
    return ""


def _read_reg_str(key: winreg.HKEYType, name: str) -> str:
    try:
        val, _ = winreg.QueryValueEx(key, name)
        return str(val).strip() if val is not None else ""
    except OSError:
        return ""


def _read_reg_int(key: winreg.HKEYType, name: str) -> int:
    try:
        val, _ = winreg.QueryValueEx(key, name)
        return int(val)
    except (OSError, ValueError, TypeError):
        return 0


def _quick_folder_estimate(folder: str, max_files: int = 1200) -> int:
    """Fast bounded size walk when EstimatedSize is absent from Registry."""
    total = 0
    seen = 0
    try:
        stack = [folder]
        while stack and seen < max_files:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for entry in it:
                        if entry.is_symlink():
                            continue
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                            seen += 1
                            if seen >= max_files:
                                break
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
            except OSError:
                continue
    except OSError:
        pass
    return total


def _scan_service_paths() -> List[Tuple[str, str]]:
    """Return list of (normalized_exe_dir_or_path, service_display_name) for Windows services/drivers."""
    results: List[Tuple[str, str]] = []
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Services",
            0,
            winreg.KEY_READ,
        ) as svc_root:
            num_sub, _, _ = winreg.QueryInfoKey(svc_root)
            for i in range(num_sub):
                try:
                    sub_name = winreg.EnumKey(svc_root, i)
                    with winreg.OpenKey(svc_root, sub_name) as sk:
                        img = _read_reg_str(sk, "ImagePath")
                        if not img:
                            continue
                        if img.startswith("\\??\\"):
                            img = img[4:]
                        exe = _extract_exe_from_command(img)
                        if not exe and img.lower().endswith(".sys"):
                            cand = os.path.expandvars(img.strip('"'))
                            if os.path.exists(cand):
                                exe = cand
                        if exe:
                            norm_exe = _norm_path(exe)
                            if not norm_exe.startswith(_norm_path(os.environ.get("SystemRoot", r"C:\Windows"))):
                                disp = _read_reg_str(sk, "DisplayName") or sub_name
                                results.append((norm_exe, disp))
                except OSError:
                    continue
    except OSError:
        pass
    return results


@dataclass
class InstalledAppRecord:
    id: str
    name: str
    version: str
    publisher: str
    install_location: str
    main_exe: str
    icon_spec: str
    estimated_bytes: int
    scope: str  # "user" or "machine"
    reg_hive_name: str
    reg_subkey_path: str
    reg_key_name: str
    readiness: str  # "ready", "service_warning", "manual_folder"
    readiness_detail: str
    shortcuts: List[Dict[str, str]] = field(default_factory=list)


class SoftwareScanner:
    """Discovers installed Windows programs and inspects their full disk/Registry/AppData footprint."""

    def __init__(self) -> None:
        self._apps: Dict[str, InstalledAppRecord] = {}
        self._shortcuts: List[Dict[str, str]] = []
        self._services: List[Tuple[str, str]] = []

    def scan_installed_apps(self) -> List[Dict[str, Any]]:
        self._shortcuts = _collect_all_shortcuts()
        self._services = _scan_service_paths()
        found: Dict[str, InstalledAppRecord] = {}
        seen_signatures: Set[Tuple[str, str]] = set()

        sources = [
            (
                "HKCU",
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                winreg.KEY_READ,
                "user",
            ),
            (
                "HKLM",
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
                "machine",
            ),
            (
                "HKLM32",
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
                winreg.KEY_READ,
                "machine",
            ),
        ]

        for hive_label, hive, uninstall_path, access_flags, scope in sources:
            try:
                with winreg.OpenKey(hive, uninstall_path, 0, access_flags) as root_key:
                    sub_count, _, _ = winreg.QueryInfoKey(root_key)
                    for i in range(sub_count):
                        try:
                            key_name = winreg.EnumKey(root_key, i)
                            with winreg.OpenKey(root_key, key_name, 0, access_flags) as ak:
                                if _read_reg_int(ak, "SystemComponent") == 1:
                                    continue
                                if _read_reg_str(ak, "ParentKeyName"):
                                    continue
                                release_type = _read_reg_str(ak, "ReleaseType").lower()
                                if release_type in ("security update", "update", "hotfix"):
                                    continue

                                name = _read_reg_str(ak, "DisplayName")
                                if not name:
                                    continue
                                # Skip noise redistributable sub-entries unless standalone
                                if re.match(r"^Microsoft Visual C\+\+ \d{4}.*Redistributable", name, re.I):
                                    continue

                                version = _read_reg_str(ak, "DisplayVersion")
                                publisher = _read_reg_str(ak, "Publisher")
                                raw_loc = _read_reg_str(ak, "InstallLocation")
                                raw_icon = _read_reg_str(ak, "DisplayIcon")
                                uninst = _read_reg_str(ak, "UninstallString")
                                est_kb = _read_reg_int(ak, "EstimatedSize")

                                install_loc, main_exe, matched_lnks = self._resolve_paths(
                                    name, publisher, raw_loc, raw_icon, uninst
                                )

                                dedup_sig = (
                                    name.lower().strip(),
                                    _norm_path(install_loc) if install_loc else version.lower(),
                                )
                                if dedup_sig in seen_signatures:
                                    continue
                                seen_signatures.add(dedup_sig)

                                icon_spec = raw_icon
                                if (not icon_spec or not os.path.isfile(parse_icon_spec(icon_spec)[0])) and main_exe:
                                    icon_spec = main_exe

                                est_bytes = est_kb * 1024 if est_kb > 0 else 0
                                if est_bytes == 0 and install_loc:
                                    est_bytes = _quick_folder_estimate(install_loc, max_files=160)

                                readiness, detail = self._assess_readiness(install_loc, main_exe)

                                app_id = hashlib.sha1(
                                    f"{hive_label}:{key_name}:{name}".encode("utf-8")
                                ).hexdigest()[:12]

                                rec = InstalledAppRecord(
                                    id=app_id,
                                    name=name,
                                    version=version or "1.0",
                                    publisher=publisher or "Unknown publisher",
                                    install_location=install_loc,
                                    main_exe=main_exe,
                                    icon_spec=icon_spec,
                                    estimated_bytes=est_bytes,
                                    scope=scope,
                                    reg_hive_name=hive_label,
                                    reg_subkey_path=f"{uninstall_path}\\{key_name}",
                                    reg_key_name=key_name,
                                    readiness=readiness,
                                    readiness_detail=detail,
                                    shortcuts=matched_lnks,
                                )
                                found[app_id] = rec
                        except OSError:
                            continue
            except OSError:
                continue

        # Sort: packable apps first, then alphabetically by name
        rank = {"ready": 0, "service_warning": 1, "manual_folder": 2}
        ordered = sorted(found.values(), key=lambda r: (rank.get(r.readiness, 9), r.name.lower()))
        self._apps = {r.id: r for r in ordered}

        return [self._serialize_summary(r) for r in ordered]

    def _resolve_paths(
        self,
        name: str,
        publisher: str,
        raw_loc: str,
        raw_icon: str,
        uninst: str,
    ) -> Tuple[str, str, List[Dict[str, str]]]:
        install_loc = ""
        if raw_loc:
            cand = os.path.expandvars(raw_loc.strip().strip('"'))
            if is_safe_app_folder(cand):
                install_loc = os.path.normpath(cand)

        icon_path, _ = parse_icon_spec(raw_icon)
        if not install_loc and icon_path and icon_path.lower().endswith(".exe") and os.path.isfile(icon_path):
            parent = os.path.dirname(icon_path)
            if is_safe_app_folder(parent):
                install_loc = os.path.normpath(parent)

        if not install_loc and uninst:
            u_exe = _extract_exe_from_command(uninst)
            if u_exe and os.path.basename(u_exe).lower() not in (
                "msiexec.exe",
                "rundll32.exe",
                "cmd.exe",
                "powershell.exe",
            ):
                parent = os.path.dirname(u_exe)
                if is_safe_app_folder(parent):
                    install_loc = os.path.normpath(parent)

        # Narrow umbrella vendor folders (e.g. "C:\Program Files\Adobe" -> "C:\Program Files\Adobe\Adobe Premiere Pro 2025")
        if install_loc and os.path.isdir(install_loc):
            install_loc = self._narrow_umbrella_folder(install_loc, name, icon_path)

        # Match Start Menu / Desktop shortcuts
        matched_lnks: List[Dict[str, str]] = []
        norm_loc = _norm_path(install_loc) if install_loc else ""
        clean_title = re.sub(r"\s*\([^)]*\)|\s+\d+(\.\d+)*.*$", "", name).strip().lower()

        for lnk in self._shortcuts:
            t_path = lnk.get("target_path", "")
            if not t_path or not t_path.lower().endswith(".exe") or not os.path.isfile(t_path):
                continue
            norm_t = _norm_path(t_path)
            if norm_loc and norm_t.startswith(norm_loc + os.sep):
                matched_lnks.append(lnk)
            elif not norm_loc and clean_title and len(clean_title) >= 3:
                lnk_name = lnk.get("name", "").lower()
                if lnk_name == clean_title or lnk_name == name.lower() or (
                    clean_title in lnk_name and not UNINSTALLER_RE.search(t_path)
                ):
                    parent = os.path.dirname(t_path)
                    if is_safe_app_folder(parent):
                        install_loc = os.path.normpath(parent)
                        norm_loc = _norm_path(install_loc)
                        matched_lnks.append(lnk)

        # Pick primary executable
        main_exe = ""
        for lnk in matched_lnks:
            tp = lnk["target_path"]
            if os.path.isfile(tp) and not UNINSTALLER_RE.search(os.path.basename(tp)):
                main_exe = os.path.normpath(tp)
                break

        if not main_exe and icon_path and icon_path.lower().endswith(".exe") and os.path.isfile(icon_path):
            if norm_loc and _norm_path(icon_path).startswith(norm_loc + os.sep):
                if not UNINSTALLER_RE.search(os.path.basename(icon_path)):
                    main_exe = os.path.normpath(icon_path)

        if not main_exe and install_loc:
            exes = self._find_executables_shallow(install_loc)
            if exes:
                main_exe = self._rank_executables(exes, name)[0]

        return install_loc, main_exe, matched_lnks

    def _narrow_umbrella_folder(self, folder: str, app_name: str, icon_path: str) -> str:
        """If Registry InstallLocation points to a shared vendor umbrella (e.g. C:\\Program Files\\Adobe),
        narrow to the specific child application folder when present."""
        try:
            subdirs = [e for e in os.scandir(folder) if e.is_dir(follow_symlinks=False)]
        except OSError:
            return folder

        if not subdirs:
            return folder

        name_low = app_name.strip().lower()
        clean_low = re.sub(r"\s*\([^)]*\)$", "", name_low).strip()
        folder_base = os.path.basename(folder).lower()

        # Already narrowed to the app's own folder (e.g. "Adobe Photoshop 2025")
        if folder_base == name_low or (clean_low and folder_base == clean_low):
            return folder

        # 1. Exact child folder matching DisplayName (e.g. "Adobe Premiere Pro 2025")
        for entry in subdirs:
            en = entry.name.lower()
            if en == name_low or (clean_low and en == clean_low):
                return os.path.normpath(entry.path)

        # 2. Only if folder itself is a generic vendor umbrella (e.g. "Adobe"), narrow via DisplayIcon
        if folder_base in GENERIC_VENDOR_NAMES:
            if icon_path and os.path.isfile(icon_path):
                norm_icon = _norm_path(icon_path)
                for entry in subdirs:
                    norm_sub = _norm_path(entry.path)
                    if entry.name.lower() not in ("common", "common files", "shared", "uninstall"):
                        if norm_icon.startswith(norm_sub + os.sep):
                            return os.path.normpath(entry.path)

        return folder

    def _find_executables_shallow(self, folder: str, max_depth: int = 2) -> List[str]:
        exes: List[str] = []
        base_depth = folder.rstrip(os.sep).count(os.sep)
        try:
            for dirpath, dirnames, filenames in os.walk(folder):
                depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
                if depth >= max_depth:
                    dirnames[:] = []
                for fn in filenames:
                    if fn.lower().endswith(".exe") and not UNINSTALLER_RE.search(fn):
                        exes.append(os.path.join(dirpath, fn))
        except OSError:
            pass
        return exes

    def _rank_executables(self, exes: List[str], app_name: str) -> List[str]:
        tokens = [t for t in re.split(r"[^a-z0-9]+", app_name.lower()) if len(t) >= 2]
        compact = "".join(tokens)

        def score(p: str) -> Tuple[int, int, int]:
            stem = Path(p).stem.lower()
            s_clean = re.sub(r"[^a-z0-9]+", "", stem)
            exact = 0 if (s_clean == compact or (tokens and stem == tokens[0])) else 1
            partial = 0 if any(t in stem for t in tokens) else 1
            depth = p.count(os.sep)
            return (exact, partial, depth)

        return sorted(exes, key=score)

    def _assess_readiness(self, install_loc: str, main_exe: str) -> Tuple[str, str]:
        if not install_loc or not os.path.isdir(install_loc):
            return (
                "manual_folder",
                "Install folder was not listed in Windows Registry. Choose the app's folder manually to package it.",
            )
        norm_loc = _norm_path(install_loc)
        matched_svcs = [
            disp
            for svc_exe, disp in self._services
            if svc_exe.startswith(norm_loc + os.sep)
        ]
        if matched_svcs:
            svc_list = ", ".join(matched_svcs[:2])
            return (
                "service_warning",
                f"Registers Windows background service ({svc_list}). Folder & registry files will package cleanly, "
                "but kernel drivers or system services may require the vendor's original setup on another PC.",
            )
        return ("ready", "Standalone program directory ready for offline .exe packaging.")

    def _serialize_summary(self, r: InstalledAppRecord) -> Dict[str, Any]:
        return {
            "id": r.id,
            "name": r.name,
            "version": r.version,
            "publisher": r.publisher,
            "install_location": r.install_location,
            "main_exe": r.main_exe,
            "icon": get_icon_data_uri(r.icon_spec or r.main_exe, size=48),
            "estimated_bytes": r.estimated_bytes,
            "scope": r.scope,
            "readiness": r.readiness,
            "readiness_detail": r.readiness_detail,
        }

    def get_record(self, app_id: str) -> Optional[InstalledAppRecord]:
        return self._apps.get(app_id)

    def register_custom_folder(self, folder_path: str) -> Dict[str, Any]:
        """Create or update an InstalledAppRecord from a user-dropped or browsed directory."""
        clean_folder = os.path.normpath(folder_path.strip().strip('"'))
        if not os.path.isdir(clean_folder):
            raise ValueError(f"Directory does not exist: {clean_folder}")
        if not is_safe_app_folder(clean_folder):
            raise ValueError(
                "Selected folder is a protected Windows or shared root directory. Select a specific application folder."
            )

        folder_name = os.path.basename(clean_folder)
        exes = self._find_executables_shallow(clean_folder, max_depth=3)
        ranked = self._rank_executables(exes, folder_name) if exes else []
        main_exe = ranked[0] if ranked else ""

        app_id = "custom_" + hashlib.sha1(_norm_path(clean_folder).encode("utf-8")).hexdigest()[:10]
        readiness, detail = self._assess_readiness(clean_folder, main_exe)
        est_bytes = _quick_folder_estimate(clean_folder)

        rec = InstalledAppRecord(
            id=app_id,
            name=folder_name,
            version="1.0",
            publisher="Custom folder package",
            install_location=clean_folder,
            main_exe=main_exe,
            icon_spec=main_exe,
            estimated_bytes=est_bytes,
            scope="user",
            reg_hive_name="",
            reg_subkey_path="",
            reg_key_name="",
            readiness=readiness,
            readiness_detail=detail,
            shortcuts=[],
        )
        self._apps[app_id] = rec
        return self._serialize_summary(rec)

    def inspect_app_details(self, app_id: str, override_folder: Optional[str] = None) -> Dict[str, Any]:
        """Deep-inspect an installed app's folder, executables, shortcuts, AppData, and Registry keys."""
        rec = self._apps.get(app_id)
        if not rec:
            raise KeyError(f"Unknown app id: {app_id}")

        folder = override_folder or rec.install_location
        if override_folder:
            clean_override = os.path.normpath(override_folder.strip().strip('"'))
            if not is_safe_app_folder(clean_override):
                raise ValueError(
                    "Selected folder is a protected Windows or shared root directory. Choose a dedicated program folder."
                )
            rec.install_location = clean_override
            folder = clean_override
            rec.readiness, rec.readiness_detail = self._assess_readiness(folder, rec.main_exe)

        app_bytes = 0
        file_count = 0
        exe_candidates: List[str] = []
        has_sys_driver = False

        if folder and os.path.isdir(folder):
            for dirpath, dirnames, filenames in os.walk(folder):
                # Skip symlinked directories
                dirnames[:] = [
                    d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))
                ]
                for fn in filenames:
                    full = os.path.join(dirpath, fn)
                    if os.path.islink(full):
                        continue
                    try:
                        st = os.stat(full)
                        app_bytes += st.st_size
                        file_count += 1
                    except OSError:
                        continue
                    low = fn.lower()
                    if low.endswith(".exe") and not UNINSTALLER_RE.search(fn):
                        rel = os.path.relpath(full, folder)
                        exe_candidates.append(rel)
                    elif low.endswith(".sys"):
                        has_sys_driver = True

        ranked_full = (
            self._rank_executables([os.path.join(folder, r) for r in exe_candidates], rec.name)
            if folder and exe_candidates
            else []
        )
        ranked_rels = [os.path.relpath(p, folder) for p in ranked_full]

        selected_rel_exe = ""
        if rec.main_exe and folder and _norm_path(rec.main_exe).startswith(_norm_path(folder) + os.sep):
            selected_rel_exe = os.path.relpath(rec.main_exe, folder)
        elif ranked_rels:
            selected_rel_exe = ranked_rels[0]
            rec.main_exe = os.path.join(folder, selected_rel_exe)

        if has_sys_driver and rec.readiness == "ready":
            rec.readiness = "service_warning"
            rec.readiness_detail = (
                "Contains kernel driver (.sys) files. User-space program files will copy cleanly, "
                "but hardware/kernel drivers may need elevated driver registration on the target PC."
            )

        appdata_info = self.discover_appdata_folders(rec)
        reg_entries = self.capture_app_registry(rec)

        safe_slug = re.sub(r"[^A-Za-z0-9._-]+", "_", rec.name).strip("_") or "Software"
        ver_slug = re.sub(r"[^A-Za-z0-9._-]+", "_", rec.version).strip("_")
        default_exe_name = (
            f"{safe_slug}_{ver_slug}_Setup.exe" if ver_slug else f"{safe_slug}_Setup.exe"
        )

        return {
            "id": rec.id,
            "name": rec.name,
            "version": rec.version,
            "publisher": rec.publisher,
            "icon": get_icon_data_uri(rec.icon_spec or rec.main_exe, size=64),
            "install_location": folder,
            "readiness": rec.readiness,
            "readiness_detail": rec.readiness_detail,
            "app_bytes": app_bytes,
            "file_count": file_count,
            "exe_candidates": ranked_rels[:30],
            "selected_main_exe": selected_rel_exe,
            "shortcuts_count": len(rec.shortcuts),
            "shortcuts": [
                {"name": s["name"], "kind": s.get("location_kind", "start_menu")}
                for s in rec.shortcuts
            ],
            "appdata": appdata_info,
            "registry_key_count": len(reg_entries),
            "default_output_filename": default_exe_name,
        }

    def discover_appdata_folders(self, rec: InstalledAppRecord) -> Dict[str, Any]:
        """Locate matching %APPDATA% (Roaming) and %LOCALAPPDATA% folders and measure cache vs config."""
        roaming = os.environ.get("APPDATA", "")
        local = os.environ.get("LOCALAPPDATA", "")

        candidates = self._build_name_candidates(rec)
        matched_dirs: List[Dict[str, Any]] = []
        seen_norms: Set[str] = set()

        for scope_label, base_root in (("Roaming", roaming), ("Local", local)):
            if not base_root or not os.path.isdir(base_root):
                continue
            try:
                top_entries = {e.name.lower(): e.path for e in os.scandir(base_root) if e.is_dir(follow_symlinks=False)}
            except OSError:
                continue

            # 1. Direct match on app name / exe stem (never on generic vendor name alone)
            for cand in candidates["app_keys"]:
                if cand in top_entries:
                    p = top_entries[cand]
                    # Make sure we aren't matching the install_location itself (e.g. Local\Programs\App)
                    if rec.install_location and _norm_path(p) == _norm_path(rec.install_location):
                        continue
                    if rec.install_location and _norm_path(rec.install_location).startswith(_norm_path(p) + os.sep):
                        continue
                    norm_p = _norm_path(p)
                    if norm_p not in seen_norms and is_safe_app_folder(p):
                        seen_norms.add(norm_p)
                        matched_dirs.append(self._measure_appdata_dir(scope_label, base_root, p))

            # 2. Nested <Publisher>\<App> match
            for pub_cand in candidates["pub_keys"]:
                if pub_cand in top_entries:
                    pub_dir = top_entries[pub_cand]
                    try:
                        sub_entries = {
                            e.name.lower(): e.path
                            for e in os.scandir(pub_dir)
                            if e.is_dir(follow_symlinks=False)
                        }
                    except OSError:
                        continue
                    for app_cand in candidates["app_keys"]:
                        if app_cand in sub_entries:
                            p = sub_entries[app_cand]
                            if rec.install_location and _norm_path(p) == _norm_path(rec.install_location):
                                continue
                            norm_p = _norm_path(p)
                            if norm_p not in seen_norms and is_safe_app_folder(p):
                                seen_norms.add(norm_p)
                                matched_dirs.append(self._measure_appdata_dir(scope_label, base_root, p))

        clean_bytes = sum(d["clean_bytes"] for d in matched_dirs)
        cache_bytes = sum(d["cache_bytes"] for d in matched_dirs)
        return {
            "found": len(matched_dirs) > 0,
            "folders": matched_dirs,
            "clean_bytes": clean_bytes,
            "cache_bytes": cache_bytes,
            "total_bytes": clean_bytes + cache_bytes,
        }

    def _build_name_candidates(self, rec: InstalledAppRecord) -> Dict[str, List[str]]:
        clean_name = re.sub(r"\s*\([^)]*\)|\s+v?\d+(\.\d+)*.*$", "", rec.name, flags=re.I).strip()
        app_keys: List[str] = []
        for raw in (
            rec.name.strip(),
            clean_name,
            clean_name.replace(" ", ""),
            clean_name.replace(" ", "-"),
            Path(rec.main_exe).stem if rec.main_exe else "",
            Path(rec.install_location).name if rec.install_location else "",
        ):
            low = raw.lower().strip()
            if len(low) >= 3 and low not in GENERIC_VENDOR_NAMES and low not in app_keys:
                app_keys.append(low)

        pub_clean = re.sub(
            r"\b(inc\.?|llc|ltd\.?|corp\.?|corporation|gmbh|co\.?|s\.a\.?)\b",
            "",
            rec.publisher,
            flags=re.I,
        ).strip(" ,.")
        pub_keys = [p.lower() for p in (rec.publisher.strip(), pub_clean) if len(p.strip()) >= 2]
        return {"app_keys": app_keys, "pub_keys": list(dict.fromkeys(pub_keys))}

    def _measure_appdata_dir(self, scope_label: str, base_root: str, full_dir: str) -> Dict[str, Any]:
        clean_bytes = 0
        cache_bytes = 0
        rel_to_root = os.path.relpath(full_dir, base_root)

        for dirpath, dirnames, filenames in os.walk(full_dir):
            dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
            rel_parts = Path(os.path.relpath(dirpath, full_dir)).parts
            in_cache = any(part.lower() in CACHE_DIR_NAMES for part in rel_parts if part != ".")
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                if os.path.islink(fp):
                    continue
                try:
                    sz = os.stat(fp).st_size
                    if in_cache:
                        cache_bytes += sz
                    else:
                        clean_bytes += sz
                except OSError:
                    continue

        return {
            "scope": scope_label,  # "Roaming" or "Local"
            "rel_path": rel_to_root,
            "full_path": full_dir,
            "clean_bytes": clean_bytes,
            "cache_bytes": cache_bytes,
            "total_bytes": clean_bytes + cache_bytes,
        }

    def capture_app_registry(self, rec: InstalledAppRecord, max_keys: int = 250) -> List[Dict[str, Any]]:
        """Capture app-specific HKCU\\Software keys with tokenized paths ({{INSTALL_DIR}}, {{USER_PROFILE}})."""
        cands = self._build_name_candidates(rec)
        search_subpaths: List[str] = []
        for ak in cands["app_keys"]:
            search_subpaths.append(f"Software\\{ak}")
            for pk in cands["pub_keys"]:
                if pk not in GENERIC_VENDOR_NAMES:
                    search_subpaths.append(f"Software\\{pk}\\{ak}")

        entries: List[Dict[str, Any]] = []
        visited_norms: Set[str] = set()

        install_dir = rec.install_location or ""
        user_prof = os.environ.get("USERPROFILE", "")

        def _tokenize_str(s: str) -> str:
            out = s
            if install_dir:
                out = re.sub(re.escape(install_dir), "{{INSTALL_DIR}}", out, flags=re.IGNORECASE)
            if user_prof:
                out = re.sub(re.escape(user_prof), "{{USER_PROFILE}}", out, flags=re.IGNORECASE)
            return out

        for rel_sub in search_subpaths:
            if len(entries) >= max_keys:
                break
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rel_sub, 0, winreg.KEY_READ):
                    pass
            except OSError:
                continue

            norm_rel = rel_sub.lower()
            if norm_rel in visited_norms:
                continue
            visited_norms.add(norm_rel)
            self._walk_reg_tree(
                winreg.HKEY_CURRENT_USER,
                rel_sub,
                entries,
                max_keys,
                _tokenize_str,
            )

        return entries

    def _walk_reg_tree(
        self,
        hive: int,
        subpath: str,
        out: List[Dict[str, Any]],
        max_keys: int,
        tokenize_fn: Any,
    ) -> None:
        if len(out) >= max_keys:
            return
        try:
            with winreg.OpenKey(hive, subpath, 0, winreg.KEY_READ) as k:
                sub_count, val_count, _ = winreg.QueryInfoKey(k)
                vals: List[Dict[str, Any]] = []
                for idx in range(val_count):
                    try:
                        v_name, v_data, v_type = winreg.EnumValue(k, idx)
                        encoded = self._encode_reg_value(v_name, v_data, v_type, tokenize_fn)
                        if encoded is not None:
                            vals.append(encoded)
                    except OSError:
                        continue
                out.append({"subkey": subpath, "values": vals})

                for idx in range(sub_count):
                    if len(out) >= max_keys:
                        break
                    try:
                        child = winreg.EnumKey(k, idx)
                        self._walk_reg_tree(hive, f"{subpath}\\{child}", out, max_keys, tokenize_fn)
                    except OSError:
                        continue
        except OSError:
            pass

    def _encode_reg_value(
        self, name: str, data: Any, reg_type: int, tokenize_fn: Any
    ) -> Optional[Dict[str, Any]]:
        if reg_type == winreg.REG_SZ:
            return {"name": name, "kind": "String", "value": tokenize_fn(str(data))}
        if reg_type == winreg.REG_EXPAND_SZ:
            return {"name": name, "kind": "ExpandString", "value": tokenize_fn(str(data))}
        if reg_type == winreg.REG_DWORD:
            return {"name": name, "kind": "DWord", "value": int(data)}
        if reg_type == winreg.REG_QWORD:
            return {"name": name, "kind": "QWord", "value": int(data)}
        if reg_type == winreg.REG_MULTI_SZ and isinstance(data, list):
            return {"name": name, "kind": "MultiString", "value": [tokenize_fn(str(x)) for x in data]}
        if reg_type == winreg.REG_BINARY and isinstance(data, (bytes, bytearray)):
            if len(data) <= 32768:  # Avoid huge binary blobs
                return {"name": name, "kind": "Binary", "value": base64.b64encode(bytes(data)).decode("ascii")}
        return None
