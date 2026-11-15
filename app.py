"""WinCrate Desktop Entrypoint — Launches the native Windows WebView2 window."""

from __future__ import annotations

import argparse
import ctypes
import io
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any


def _ensure_gui_stdio() -> Path | None:
    """Under pythonw.exe, sys.stdout and sys.stderr are None, breaking logging/StreamHandler."""
    log_path: Path | None = None
    if sys.stdout is None or sys.stderr is None:
        try:
            local_app = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
            log_dir = Path(local_app) / "WinCrate"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "wincrate.log"
            stream = open(log_path, "a", encoding="utf-8", buffering=1, errors="replace")
        except Exception:
            stream = io.StringIO()
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream
    return log_path


_LOG_FILE = _ensure_gui_stdio()

# Ensure bundled/isolated Python (_pth) always resolves the local wincrate package
_APP_ROOT = Path(__file__).resolve().parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from wincrate.server import start_local_server  # noqa: E402


def _run_self_test(ui_dir: Path) -> int:
    """Verify standalone runtime integrity (clr/pythonnet, pywebview, Pillow, scanner, csc.exe)."""
    import clr  # noqa: F401
    import webview  # noqa: F401
    from PIL import Image
    from wincrate.builder import find_csc_compiler
    from wincrate.scanner import SoftwareScanner

    if not (ui_dir / "index.html").is_file():
        raise FileNotFoundError(f"Missing UI assets in {ui_dir}")

    csc = find_csc_compiler()
    img = Image.new("RGBA", (32, 32), (181, 62, 25, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img.save(io.BytesIO(), format="ICO", sizes=[(16, 16), (32, 32)])

    scanner = SoftwareScanner()
    apps = scanner.scan_installed_apps()
    print(f"WINCRATE_SELFTEST_OK apps={len(apps)} csc={csc} python={sys.executable}", flush=True)
    return 0


def _browser_fallback_session(url: str) -> None:
    """Fallback for older un-updated Windows 10 PCs without Edge WebView2 Runtime."""
    try:
        os.startfile(url)
    except Exception:
        import webbrowser
        webbrowser.open(url)

    msg = (
        f"Microsoft Edge WebView2 Runtime was not detected on this PC, so WinCrate opened in your default browser:\n\n"
        f"{url}\n\n"
        f"Keep this dialog open while using WinCrate, and click OK when you are finished to shut down the local engine."
    )
    ctypes.windll.user32.MessageBoxW(0, msg, "WinCrate — Running in Browser", 0x00000040)


def _resolve_webview_storage_dir() -> str | None:
    """Give WinCrate a dedicated WebView2 UserDataFolder so it never collides with other pywebview apps."""
    try:
        local_app = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        storage = Path(local_app) / "WinCrate" / "WebView2Data"
        storage.mkdir(parents=True, exist_ok=True)
        return str(storage)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="WinCrate — Offline Windows Software Packager")
    parser.add_argument(
        "--serve-only",
        action="store_true",
        help="Start the local HTTP API/UI server without opening a desktop GUI window.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run a headless self-check of all bundled runtime components and exit.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Optional port to bind on 127.0.0.1 (defaults to an ephemeral free port).",
    )
    args = parser.parse_args()

    ui_dir = _APP_ROOT / "ui"
    if args.self_test:
        return _run_self_test(ui_dir)

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("WinCrate.DesktopApp.1.0")
    except Exception:
        pass

    server, port, ctx = start_local_server(ui_dir=ui_dir, port=args.port)
    url = f"http://127.0.0.1:{port}/"

    if args.serve_only:
        print(f"WINCRATE_URL={url}", flush=True)
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            server.shutdown()
            return 0

    try:
        import webview
        from webview.dom import DOMEventHandler

        window = webview.create_window(
            title="WinCrate — Windows Software Packager",
            url=url,
            width=1220,
            height=780,
            min_size=(960, 620),
            background_color="#ECEAE4",
            text_select=False,
        )

        def _webview_pick_folder(title: str, initial_dir: str = "") -> str | None:
            try:
                kwargs: dict[str, Any] = {}
                if initial_dir and os.path.isdir(initial_dir):
                    kwargs["directory"] = initial_dir
                dialog_mode = getattr(getattr(webview, "FileDialog", None), "FOLDER", 20)
                res = window.create_file_dialog(dialog_mode, **kwargs)
                if res and len(res) > 0:
                    return str(res[0])
            except Exception:
                pass
            return None

        ctx.webview_folder_picker = _webview_pick_folder

        def _on_shown() -> None:
            # Apply custom wincrate.ico to WinForms window & bring cleanly to foreground
            try:
                ico_file = _APP_ROOT / "wincrate" / "wincrate.ico"
                from System import Action  # type: ignore
                from System.Drawing import Icon  # type: ignore
                from webview.platforms.winforms import BrowserView  # type: ignore

                form = BrowserView.instances.get(window.uid)
                if form is not None:
                    def _activate_form() -> None:
                        try:
                            if ico_file.is_file():
                                form.Icon = Icon(str(ico_file))
                            form.WindowState = 0  # FormWindowState.Normal
                            form.TopMost = True
                            form.Show()
                            form.Activate()
                            form.BringToFront()
                            form.TopMost = False
                        except Exception:
                            pass

                    form.Invoke(Action(_activate_form))
            except Exception:
                try:
                    window.restore()
                    window.on_top = True
                    threading.Timer(0.2, lambda: setattr(window, "on_top", False)).start()
                except Exception:
                    pass

        def _on_loaded() -> None:
            def _on_native_drop(e: dict[str, Any]) -> None:
                files = e.get("dataTransfer", {}).get("files", [])
                if not files:
                    return
                first = files[0]
                full_path = first.get("pywebviewFullPath") or ""
                if full_path:
                    escaped = json.dumps(full_path)
                    window.evaluate_js(
                        f"window.WinCrateHandleNativeDrop && window.WinCrateHandleNativeDrop({escaped});"
                    )

            try:
                window.dom.document.events.drop += DOMEventHandler(_on_native_drop, True, True)
            except Exception:
                pass

        window.events.shown += _on_shown
        window.events.loaded += _on_loaded

        storage_dir = _resolve_webview_storage_dir()
        start_kwargs: dict[str, Any] = {"debug": False}
        if storage_dir:
            start_kwargs["private_mode"] = False
            start_kwargs["storage_path"] = storage_dir

        try:
            webview.start(gui="edgechromium", **start_kwargs)
        except Exception:
            try:
                webview.start(**start_kwargs)
            except Exception:
                _browser_fallback_session(url)
    except Exception:
        _browser_fallback_session(url)
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:
        tb = traceback.format_exc()
        try:
            print(tb, file=sys.stderr, flush=True)
        except Exception:
            pass
        ctypes.windll.user32.MessageBoxW(
            0,
            f"WinCrate encountered a startup error:\n\n{exc}\n\nDetails logged to: {_LOG_FILE or 'wincrate.log'}",
            "WinCrate Startup Error",
            0x00000010,
        )
        sys.exit(1)
