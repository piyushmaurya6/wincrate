"""Local ThreadingHTTPServer API & Native Windows Dialog Helpers for WinCrate."""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import threading
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .builder import BuildRequest, PackageBuilder, get_free_bytes
from .scanner import SoftwareScanner


def pick_folder_dialog(title: str = "Select folder", initial_dir: str = "") -> Optional[str]:
    """Open a native Windows FolderBrowserDialog via PowerShell STA (works with or without pywebview)."""
    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
        f"$f.Description = {json.dumps(title)}; "
        "$f.ShowNewFolderButton = $true; "
    )
    if initial_dir and os.path.isdir(initial_dir):
        ps_script += f"$f.SelectedPath = {json.dumps(initial_dir)}; "
    ps_script += (
        "if ($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "Write-Output $f.SelectedPath }"
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", ps_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            creationflags=creationflags,
            timeout=180,
        )
        chosen = res.stdout.strip()
        return chosen if chosen and os.path.isdir(chosen) else None
    except Exception:
        return None


def reveal_in_explorer(target_path: str) -> bool:
    """Highlight a file or open a directory in Windows File Explorer."""
    if not target_path:
        return False
    norm = os.path.normpath(target_path)
    try:
        if os.path.isfile(norm):
            subprocess.Popen(["explorer.exe", f"/select,{norm}"])
            return True
        if os.path.isdir(norm):
            os.startfile(norm)
            return True
    except Exception:
        pass
    return False


class WinCrateAppContext:
    def __init__(self, ui_dir: Path) -> None:
        self.ui_dir = ui_dir
        self.scanner = SoftwareScanner()
        self.builder = PackageBuilder(self.scanner)
        self.scan_lock = threading.Lock()
        self.cached_apps: Optional[list[Dict[str, Any]]] = None
        self.webview_folder_picker: Optional[Callable[[str, str], Optional[str]]] = None

    def get_apps(self, force_refresh: bool = False) -> list[Dict[str, Any]]:
        with self.scan_lock:
            if self.cached_apps is None or force_refresh:
                self.cached_apps = self.scanner.scan_installed_apps()
            return self.cached_apps

    def choose_folder(self, title: str, initial_dir: str = "") -> Optional[str]:
        if self.webview_folder_picker is not None:
            res = self.webview_folder_picker(title, initial_dir)
            if res:
                return res
            return None
        return pick_folder_dialog(title=title, initial_dir=initial_dir)


def make_handler(ctx: WinCrateAppContext):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            # Keep desktop stdout clean
            return

        def _send_json(self, payload: Any, status: int = 200) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _read_json_body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            body = self.rfile.read(length)
            return json.loads(body.decode("utf-8"))

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)

            try:
                if route == "/api/state":
                    self._send_json(
                        {
                            "output_dir": ctx.builder.output_dir,
                            "output_free_bytes": get_free_bytes(ctx.builder.output_dir),
                            "packages": ctx.builder.list_built_packages(),
                        }
                    )
                    return

                if route == "/api/apps":
                    refresh = qs.get("refresh", ["0"])[0] == "1"
                    apps = ctx.get_apps(force_refresh=refresh)
                    self._send_json(
                        {
                            "apps": apps,
                            "output_dir": ctx.builder.output_dir,
                            "output_free_bytes": get_free_bytes(ctx.builder.output_dir),
                            "packages": ctx.builder.list_built_packages(),
                        }
                    )
                    return

                if route == "/api/inspect":
                    app_id = qs.get("id", [""])[0]
                    override_folder = qs.get("folder", [None])[0]
                    if not app_id:
                        self._send_json({"error": "Missing app id."}, status=400)
                        return
                    details = ctx.scanner.inspect_app_details(app_id, override_folder=override_folder)
                    self._send_json(details)
                    return

                if route == "/api/build/status":
                    job_id = qs.get("job_id", [""])[0]
                    job = ctx.builder.get_job(job_id)
                    if not job:
                        self._send_json({"error": "Unknown build job."}, status=404)
                        return
                    data = job.to_dict()
                    if job.status == "done":
                        data["packages"] = ctx.builder.list_built_packages()
                    self._send_json(data)
                    return

                if route == "/api/packages":
                    self._send_json(
                        {
                            "output_dir": ctx.builder.output_dir,
                            "output_free_bytes": get_free_bytes(ctx.builder.output_dir),
                            "packages": ctx.builder.list_built_packages(),
                        }
                    )
                    return

                # Serve static UI files
                rel = "index.html" if route in ("/", "") else route.lstrip("/")
                target = (ctx.ui_dir / rel).resolve()
                if not str(target).startswith(str(ctx.ui_dir.resolve())) or not target.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND, "File not found")
                    return

                ctype, _ = mimetypes.guess_type(str(target))
                if not ctype:
                    ctype = "application/octet-stream"
                data = target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            except KeyError as exc:
                self._send_json({"error": str(exc)}, status=404)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json({"error": f"Server error: {exc}"}, status=500)

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path

            try:
                body = self._read_json_body()

                if route == "/api/pick-folder":
                    kind = body.get("kind", "app")
                    initial = body.get("initial_dir", "")
                    title = (
                        "Choose Output Folder for Standalone .exe Packages"
                        if kind == "output"
                        else "Choose Installed Application Folder"
                    )
                    chosen = ctx.choose_folder(title=title, initial_dir=initial)
                    if not chosen:
                        self._send_json({"cancelled": True})
                        return
                    if kind == "output":
                        ctx.builder.output_dir = os.path.normpath(chosen)
                        os.makedirs(ctx.builder.output_dir, exist_ok=True)
                        self._send_json(
                            {
                                "cancelled": False,
                                "path": ctx.builder.output_dir,
                                "output_free_bytes": get_free_bytes(ctx.builder.output_dir),
                                "packages": ctx.builder.list_built_packages(),
                            }
                        )
                        return
                    self._send_json({"cancelled": False, "path": os.path.normpath(chosen)})
                    return

                if route == "/api/custom-folder":
                    raw_path = str(body.get("path", "")).strip()
                    if not raw_path:
                        self._send_json({"error": "No folder or executable path provided."}, status=400)
                        return
                    # If user dropped an .exe file inside an app folder, resolve its parent folder
                    if os.path.isfile(raw_path):
                        if raw_path.lower().endswith(".exe"):
                            raw_path = os.path.dirname(raw_path)
                        else:
                            self._send_json(
                                {
                                    "error": "Drop an application folder or an application's .exe file (other file types cannot be packaged)."
                                },
                                status=400,
                            )
                            return

                    summary = ctx.scanner.register_custom_folder(raw_path)
                    # Add to cached_apps front if present
                    with ctx.scan_lock:
                        if ctx.cached_apps is not None:
                            ctx.cached_apps = [a for a in ctx.cached_apps if a["id"] != summary["id"]]
                            ctx.cached_apps.insert(0, summary)
                    details = ctx.scanner.inspect_app_details(summary["id"])
                    self._send_json({"summary": summary, "details": details})
                    return

                if route == "/api/build":
                    req = BuildRequest(
                        app_id=str(body.get("app_id", "")),
                        package_name=str(body.get("package_name", "")).strip() or "Application",
                        package_version=str(body.get("package_version", "1.0")).strip() or "1.0",
                        publisher=str(body.get("publisher", "")).strip(),
                        install_location=str(body.get("install_location", "")).strip(),
                        main_exe_rel=str(body.get("main_exe_rel", "")).strip(),
                        output_dir=str(body.get("output_dir", "")).strip() or ctx.builder.output_dir,
                        output_filename=str(body.get("output_filename", "")).strip() or "Setup.exe",
                        include_appdata=bool(body.get("include_appdata", False)),
                        exclude_appdata_cache=bool(body.get("exclude_appdata_cache", True)),
                        include_registry=bool(body.get("include_registry", True)),
                        desktop_shortcut=bool(body.get("desktop_shortcut", True)),
                        start_menu_shortcut=bool(body.get("start_menu_shortcut", True)),
                        register_uninstaller=bool(body.get("register_uninstaller", True)),
                    )
                    job = ctx.builder.start_build(req)
                    self._send_json(job.to_dict())
                    return

                if route == "/api/build/cancel":
                    job_id = str(body.get("job_id", ""))
                    ok = ctx.builder.cancel_job(job_id)
                    self._send_json({"cancelled": ok})
                    return

                if route == "/api/reveal":
                    path = str(body.get("path", "")).strip()
                    ok = reveal_in_explorer(path)
                    self._send_json({"ok": ok})
                    return

                self._send_json({"error": "Unknown API endpoint."}, status=404)

            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)
            except Exception as exc:
                self._send_json({"error": f"Server error: {exc}"}, status=500)

    return Handler


def start_local_server(ui_dir: Path, port: int = 0) -> tuple[ThreadingHTTPServer, int, WinCrateAppContext]:
    ctx = WinCrateAppContext(ui_dir=ui_dir)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(ctx))
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, actual_port, ctx
