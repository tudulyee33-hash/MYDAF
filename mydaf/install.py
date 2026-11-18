"""바탕화면 아이콘(바로가기) 만들기 — Windows 전용.

처음 실행하면 MYDAF.exe 를 %LOCALAPPDATA%\\Programs\\MYDAF 에 복사하고(다운로드 폴더를 지워도 동작하도록),
그 복사본을 가리키는 바탕화면 바로가기를 만든다. 관리자 권한은 필요 없다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SHORTCUT_NAME = "MYDAF.lnk"


def is_frozen_windows() -> bool:
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def install_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Programs" / "MYDAF"


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def shortcut_script(target: str, workdir: str, name: str = SHORTCUT_NAME) -> str:
    """바탕화면 실제 위치(OneDrive·한글 경로 포함)를 Windows에 물어 바로가기를 만드는 PowerShell."""
    return (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d " + _ps_quote(name) + "));"
        f"$s.TargetPath={_ps_quote(target)};"
        f"$s.WorkingDirectory={_ps_quote(workdir)};"
        f"$s.IconLocation={_ps_quote(target + ',0')};"
        "$s.Description='MYDAF 네이버 블로그 자동 포스팅';"
        "$s.Save();"
        "Write-Output (Join-Path $d " + _ps_quote(name) + ")"
    )


def create_desktop_shortcut(target: Path, name: str = SHORTCUT_NAME) -> str:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
         shortcut_script(str(target), str(target.parent), name)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "바로가기 생성 실패")
    return out.stdout.strip()


def install_and_shortcut() -> str:
    """실행 중인 exe 를 고정 위치로 복사(필요 시)하고 바탕화면 바로가기를 만든다. 바로가기 경로 반환."""
    if not is_frozen_windows():
        raise RuntimeError("Windows용 MYDAF.exe 에서만 바탕화면 아이콘을 만들 수 있습니다.")
    me = Path(sys.executable).resolve()
    dest_dir = install_dir()
    dest = dest_dir / "MYDAF.exe"
    if not dest.exists() or me != dest.resolve():
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(me, dest)
        except PermissionError:
            # 설치된 MYDAF 가 실행 중이면 덮어쓸 수 없음 → 지금 exe 를 그대로 가리킨다
            dest = me
    return create_desktop_shortcut(dest)


def first_run_setup(flag_dir: Path) -> str | None:
    """처음 한 번만 자동으로 바탕화면 아이콘을 만든다. 만들었으면 경로, 아니면 None."""
    flag = flag_dir / "desktop_shortcut_done"
    if flag.exists() or not is_frozen_windows():
        return None
    try:
        path = install_and_shortcut()
    except Exception:
        return None
    flag.write_text(path, encoding="utf-8")
    return path
