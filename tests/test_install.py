import sys
from pathlib import Path

import pytest

from mydaf import install


def test_shortcut_script_quotes_paths():
    s = install.shortcut_script(r"C:\Users\홍길동's PC\MYDAF.exe", r"C:\Users\홍길동's PC")
    assert "GetFolderPath('Desktop')" in s
    assert r"'C:\Users\홍길동''s PC\MYDAF.exe'" in s          # 작은따옴표 이스케이프
    assert r"'C:\Users\홍길동''s PC\MYDAF.exe,0'" in s        # 아이콘 = exe 내장 아이콘


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용")
def test_create_real_desktop_shortcut_on_windows():
    path = Path(install.create_desktop_shortcut(Path(sys.executable), "MYDAF-test.lnk"))
    try:
        assert path.exists() and path.suffix == ".lnk"
    finally:
        path.unlink(missing_ok=True)


def test_first_run_does_nothing_outside_frozen_windows(tmp_path):
    assert install.first_run_setup(tmp_path) is None
    assert not (tmp_path / "desktop_shortcut_done").exists()
