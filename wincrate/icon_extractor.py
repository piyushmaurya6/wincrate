"""Win32 native icon extraction (.exe / .dll / .ico) to PNG data URIs and .ico files."""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import io
import os
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

_ICON_CACHE: dict[Tuple[str, int, int], Optional[str]] = {}

BI_RGB = 0
DIB_RGB_COLORS = 0
DI_NORMAL = 0x0003
SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HICON),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
shell32 = ctypes.windll.shell32

user32.PrivateExtractIconsW.argtypes = [
    wintypes.LPCWSTR,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(wintypes.HICON),
    ctypes.POINTER(wintypes.UINT),
    wintypes.UINT,
    wintypes.UINT,
]
user32.PrivateExtractIconsW.restype = wintypes.UINT

user32.DrawIconEx.argtypes = [
    wintypes.HDC,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HICON,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
    wintypes.HBRUSH,
    wintypes.UINT,
]
user32.DrawIconEx.restype = wintypes.BOOL
user32.DestroyIcon.argtypes = [wintypes.HICON]
user32.DestroyIcon.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL

shell32.SHGetFileInfoW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(SHFILEINFOW),
    wintypes.UINT,
    wintypes.UINT,
]
shell32.SHGetFileInfoW.restype = ctypes.c_size_t


def parse_icon_spec(raw: str) -> Tuple[str, int]:
    """Parse a Registry DisplayIcon string like '\"C:\\App\\app.exe\",0' into (path, index)."""
    if not raw:
        return "", 0
    s = os.path.expandvars(raw.strip())
    idx = 0
    if "," in s:
        left, right = s.rsplit(",", 1)
        try:
            idx = int(right.strip())
            s = left
        except ValueError:
            pass
    s = s.strip().strip('"').strip("'")
    # Strip trailing arguments if someone put "app.exe --foo"
    if not os.path.exists(s) and ".exe" in s.lower():
        pos = s.lower().find(".exe") + 4
        candidate = s[:pos].strip('"')
        if os.path.exists(candidate):
            s = candidate
    return s, idx


def _hicon_to_pil(hicon: wintypes.HICON, size: int) -> Optional[Image.Image]:
    hdc = gdi32.CreateCompatibleDC(None)
    if not hdc:
        return None
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = size
    bmi.bmiHeader.biHeight = -size  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB

    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(hdc, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
    if not hbmp or not bits.value:
        gdi32.DeleteDC(hdc)
        return None

    old = gdi32.SelectObject(hdc, hbmp)
    try:
        ctypes.memset(bits.value, 0, size * size * 4)
        ok = user32.DrawIconEx(hdc, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
        if not ok:
            return None
        raw_bytes = ctypes.string_at(bits.value, size * size * 4)
        img = Image.frombuffer("RGBA", (size, size), raw_bytes, "raw", "BGRA", 0, 1).copy()
        # If alpha channel came back all zero (legacy GDI icon), make non-black pixels opaque
        extrema = img.getchannel("A").getextrema()
        if extrema == (0, 0):
            rgb = img.convert("RGB")
            if rgb.getbbox() is None:
                return None
            # Build alpha from non-zero pixels
            r, g, b = rgb.split()
            alpha = Image.eval(r, lambda v: 255 if v > 0 else 0)
            for ch in (g, b):
                alpha = Image. composite(Image.new("L", (size, size), 255), alpha, ch.point(lambda v: 255 if v > 0 else 0))
            img.putalpha(alpha)
        return img
    finally:
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc)


def extract_pil_icon(raw_spec: str, size: int = 48) -> Optional[Image.Image]:
    """Return a PIL RGBA image for an .exe, .dll, .ico, or image path."""
    path_str, icon_index = parse_icon_spec(raw_spec)
    if not path_str or not os.path.isfile(path_str):
        return None

    ext = Path(path_str).suffix.lower()
    if ext in (".ico", ".png", ".bmp", ".jpg", ".jpeg"):
        try:
            with Image.open(path_str) as im:
                im_rgba = im.convert("RGBA")
                if im_rgba.size != (size, size):
                    im_rgba = im_rgba.resize((size, size), Image.Resampling.LANCZOS)
                return im_rgba
        except Exception:
            pass

    hicon = wintypes.HICON()
    icon_id = wintypes.UINT()
    count = user32.PrivateExtractIconsW(
        path_str,
        icon_index,
        size,
        size,
        ctypes.byref(hicon),
        ctypes.byref(icon_id),
        1,
        0,
    )
    if count and hicon.value:
        try:
            return _hicon_to_pil(hicon, size)
        finally:
            user32.DestroyIcon(hicon)

    # Fallback: SHGetFileInfoW shell icon
    shfi = SHFILEINFOW()
    res = shell32.SHGetFileInfoW(
        path_str,
        0,
        ctypes.byref(shfi),
        ctypes.sizeof(shfi),
        SHGFI_ICON | SHGFI_LARGEICON,
    )
    if res and shfi.hIcon:
        try:
            img = _hicon_to_pil(shfi.hIcon, 32)
            if img and size != 32:
                img = img.resize((size, size), Image.Resampling.LANCZOS)
            return img
        finally:
            user32.DestroyIcon(shfi.hIcon)

    return None


def get_icon_data_uri(raw_spec: str, size: int = 48) -> Optional[str]:
    """Extract icon and return a cached 'data:image/png;base64,...' string."""
    path_str, idx = parse_icon_spec(raw_spec)
    if not path_str:
        return None
    key = (path_str.lower(), idx, size)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    img = extract_pil_icon(raw_spec, size=size)
    if img is None:
        _ICON_CACHE[key] = None
        return None

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    _ICON_CACHE[key] = uri
    return uri


def save_ico_file(raw_spec: Optional[str], dest_ico_path: str) -> bool:
    """Save a multi-size Windows .ico file suitable for csc.exe /win32icon."""
    img = extract_pil_icon(raw_spec, size=64) if raw_spec else None
    if img is None:
        return False
    try:
        img.save(
            dest_ico_path,
            format="ICO",
            sizes=[(64, 64), (48, 48), (32, 32), (16, 16)],
        )
        return os.path.isfile(dest_ico_path) and os.path.getsize(dest_ico_path) > 0
    except Exception:
        return False
