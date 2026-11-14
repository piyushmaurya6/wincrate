"""WinCrate Desktop Entrypoint — Launches the native Windows WebView2 window."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Ensure bundled/isolated Python (_pth) always resolves the local wincrate package
_APP_ROOT = Path(__file__).resolve().parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from wincrate.server import start_local_server


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
    import io
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
                res = window.create_file_dialog(webview.FOLDER_DIALOG, **kwargs)
                if res and len(res) > 0:
                    return str(res[0])
            except Exception:
                pass
            return None

        ctx.webview_folder_picker = _webview_pick_folder

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

        window.events.loaded += _on_loaded
        try:
            webview.start(gui="edgechromium", debug=False)
        except Exception:
            try:
                webview.start(debug=False)
            except Exception:
                _browser_fallback_session(url)
    except Exception:
        _browser_fallback_session(url)
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
