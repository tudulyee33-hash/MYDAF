"""바탕화면 아이콘(바로가기) 만들기 — Windows 전용.

설치는 MYDAF-Setup.exe 가 %LOCALAPPDATA%\\Programs\\MYDAF 폴더에 풀어 두고(매번 압축을 풀지 않아 빠르게 켜짐),
여기서는 바로가기 만들기와 보안 표시 지우기만 한다. 관리자 권한은 필요 없다.
"""
from __future__ import annotations

import os
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


def app_install_dir() -> Path:
    """폴더형 MYDAF 가 들어가는 곳. 예전 한 파일 버전(…\\MYDAF\\MYDAF.exe)이 덮어쓰지 못하게 하위 폴더를 쓴다."""
    return install_dir() / "app"


def installed_exe() -> Path:
    return app_install_dir() / "MYDAF.exe"


def running_installed() -> bool:
    try:
        return Path(sys.executable).resolve() == installed_exe().resolve()
    except OSError:
        return False


def strip_mark_of_web(path: Path) -> bool:
    """인터넷에서 받은 파일 표시(Zone.Identifier)를 지운다.
    이 표시가 남아 있으면 켤 때마다 Windows가 '게시자를 확인할 수 없습니다' 같은 보안 확인을 띄운다."""
    if sys.platform != "win32":
        return False
    try:
        os.remove(f"{path}:Zone.Identifier")
        return True
    except OSError:
        return False


def install_and_shortcut() -> str:
    """지금 실행 중인 MYDAF 를 가리키는 바탕화면 바로가기를 만든다. 바로가기 경로 반환."""
    if not is_frozen_windows():
        raise RuntimeError("Windows용 MYDAF.exe 에서만 바탕화면 아이콘을 만들 수 있습니다.")
    return create_desktop_shortcut(Path(sys.executable).resolve())


def startup_check(flag_dir: Path) -> dict | None:
    """프로그램을 켤 때마다 호출. 보안 확인 표시를 지우고, 바탕화면 아이콘이 없으면 한 번 만든다.
    (설치·업데이트는 MYDAF-Setup.exe 가 맡는다.)"""
    if not is_frozen_windows():
        return None
    strip_mark_of_web(Path(sys.executable))
    flag = flag_dir / "desktop_shortcut_done"
    try:
        # 설치된 새 버전이면 켤 때마다 바탕화면 아이콘을 자기에게 다시 연결한다
        # (예전 MYDAF.exe 를 실수로 켜서 아이콘이 옛 버전을 가리키게 돼도 저절로 복구).
        if running_installed() or not flag.exists():
            flag.write_text(install_and_shortcut(), encoding="utf-8")
    except Exception:
        return None
    return None
