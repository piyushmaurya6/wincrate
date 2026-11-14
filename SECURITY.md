# Security Policy

## Scope & Safety Boundaries

WinCrate is an offline user-space software repackager designed to migrate personal or portable Windows desktop software between machines you own or administer.

- **Protected System Roots:** `wincrate/scanner.py` (`is_safe_app_folder`) explicitly blocks packaging `C:\Windows`, `Program Files` root directories, user profile roots, and drive roots.
- **No Privilege Escalation:** Generated installers extract by default into user-writable `%LOCALAPPDATA%\Programs\<App>` and write `HKCU` Registry keys without requiring Administrator elevation unless the user explicitly selects a protected destination directory.
- **Path Traversal Guard:** Both `stub_template.cs` and `portable_stub.cs` normalize every ZIP entry path against the canonical destination directory root before extraction.
- **Kernel Drivers & DRM:** WinCrate does not capture kernel-mode `.sys` drivers, Windows system services, or hardware-bound DRM licenses, and surfaces an explicit warning banner whenever an application registers background services.

## Reporting a Vulnerability

If you discover a path-traversal, Registry-injection, or command-injection issue in WinCrate, please open a private security advisory on GitHub (`Security` → `Report a vulnerability`) with minimal reproduction steps rather than posting exploit payloads in a public issue.
