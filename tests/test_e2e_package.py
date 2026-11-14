"""End-to-end packaging & silent installation test for WinCrate."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wincrate.builder import BuildRequest, PackageBuilder
from wincrate.scanner import SoftwareScanner


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="wc_e2e_"))
    try:
        src_app = work / "SampleApp"
        src_app.mkdir()
        shutil.copy2(r"C:\Windows\System32\hostname.exe", src_app / "SampleApp.exe")
        (src_app / "config.json").write_text(json.dumps({"theme": "linen", "version": 1}), encoding="utf-8")

        out_dir = work / "out"
        out_dir.mkdir()

        scanner = SoftwareScanner()
        rec = scanner.register_custom_folder(str(src_app))
        builder = PackageBuilder(scanner)
        job = builder.start_build(
            BuildRequest(
                app_id=rec["id"],
                package_name="SampleApp",
                package_version="1.0.0",
                publisher="WinCrate CI",
                install_location=str(src_app),
                main_exe_rel="SampleApp.exe",
                output_dir=str(out_dir),
                output_filename="SampleApp_1.0.0_Setup.exe",
                include_appdata=False,
                include_registry=False,
            )
        )

        deadline = time.time() + 60.0
        while time.time() < deadline:
            st = builder.get_job(job.job_id)
            assert st is not None
            if st.status == "done":
                break
            if st.status in ("error", "cancelled"):
                raise RuntimeError(f"Package build failed: {st.error}")
            time.sleep(0.2)
        else:
            raise TimeoutError("Timed out waiting for SampleApp_1.0.0_Setup.exe")

        setup_exe = Path(st.output_path)
        assert setup_exe.is_file() and setup_exe.stat().st_size > 20000

        dest_dir = work / "installed"
        subprocess.run(
            [
                str(setup_exe),
                "--silent",
                f"--dir={dest_dir}",
                "--no-shortcuts",
                "--no-uninstaller",
            ],
            check=True,
        )

        assert (dest_dir / "SampleApp.exe").is_file()
        cfg = json.loads((dest_dir / "config.json").read_text(encoding="utf-8"))
        assert cfg["theme"] == "linen"
        print("E2E_PACKAGE_AND_SILENT_INSTALL_OK")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
