# Contributing to WinCrate

Thank you for your interest in improving WinCrate. This document covers local setup, architectural constraints, and verification gates.

## Local Setup

WinCrate runs natively on Windows 10 and Windows 11.

```powershell
git clone https://github.com/piyushmaurya6/wincrate.git
cd wincrate
python -m pip install -r requirements.txt
python app.py
```

## Architectural Guardrails

1. **Zero Target-PC Runtime Dependencies (`wincrate/*.cs`):**
   - Every generated `<App>_Setup.exe`, `Uninstall.exe`, and `WinCrate_Portable.exe` stub is compiled using Windows' built-in `.NET Framework 4.x` C# compiler (`C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`).
   - Keep all `.cs` files strictly **C# 5 compatible** (do not use `$"..."` string interpolation, `?.` null-conditional operators, or `nameof()`).
2. **Bounded Streaming (`WCRATE01` PE Overlay):**
   - Never load an application archive into `MemoryStream`. Payloads are written as `0`-based ZIP streams followed by a 16-byte footer (`[int64 payload_offset]["WCRATE01"]`) and read through `SubStream` in 64 KB chunks so multi-GB applications extract in `< 32 MB` of RAM.
3. **Design System Synchronization (`DESIGN.md` & `ui/tokens.css`):**
   - All colors, spacing, typography, and motion curves are defined in `DESIGN.md` and `ui/tokens.css`. Never introduce ad-hoc hex colors or undocumented spacing values in `ui/styles.css`.

## Verification Before Submitting a PR

Run the headless runtime self-test and build a standalone executable to confirm nothing is broken:

```powershell
python app.py --self-test
python build_standalone.py
```
