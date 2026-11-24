"""MYDAF 설치 프로그램 (MYDAF-Setup.exe).

PyInstaller onedir 로 만든 MYDAF 폴더를 %LOCALAPPDATA%\\Programs\\MYDAF\\app 에 풀고,
바탕화면 아이콘을 만든 뒤 MYDAF 를 켠다. 한 번만 풀어 두므로 이후에는 켤 때마다 압축을 풀지 않아 빠르다.
설정·로그·네이버 로그인(%APPDATA%\\MYDAF)은 건드리지 않는다.

예전 한 파일 버전(MYDAF.exe)이 남아 있으면 그걸 켰을 때 옛 버전으로 되돌아가므로,
찾은 것을 보여 주고 동의하면 지우지 않고 'old-versions' 폴더로 옮겨 둔다.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox

from mydaf import install
from mydaf.config import app_dir

ONEFILE_MIN_BYTES = 30_000_000      # 예전 한 파일 버전은 60MB 넘음 (폴더형 MYDAF.exe 는 수 MB)


def payload_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "payload"


def log(msg: str) -> None:
    try:
        d = app_dir() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "setup.log", "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def mydaf_running(port: int = 47613) -> bool:
    """MYDAF 가 켜져 있나: 새 버전은 포트로, 예전 버전은 프로세스 이름으로 확인."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        pass
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq MYDAF.exe", "/NH"], capture_output=True, text=True,
                             timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return "MYDAF.exe" in out
    except Exception:
        return False


def is_old_onefile(p: Path) -> bool:
    try:
        return (p.is_file() and p.name.lower() == "mydaf.exe" and p.stat().st_size >= ONEFILE_MIN_BYTES
                and not (p.parent / "_internal").exists())
    except OSError:
        return False


def find_old_copies() -> list[Path]:
    home = Path.home()
    places = [install.install_dir(), home / "Downloads", home / "Desktop", home / "OneDrive" / "Desktop",
              home / "OneDrive" / "바탕 화면", Path("C:/MYDAF")]
    found, seen = [], set()
    for d in places:
        p = d / "MYDAF.exe"
        try:
            key = str(p.resolve()).lower()
        except OSError:
            continue
        if key not in seen and is_old_onefile(p):
            seen.add(key)
            found.append(p)
    return found


def move_old(paths: list[Path]) -> list[str]:
    dest = install.install_dir() / "old-versions"
    dest.mkdir(parents=True, exist_ok=True)
    failed = []
    for i, p in enumerate(paths):
        target = dest / f"MYDAF-old-{time.strftime('%Y%m%d%H%M%S')}-{i}.exe"
        try:
            shutil.move(str(p), str(target))
            log(f"예전 버전 옮김: {p} → {target}")
        except OSError as e:
            failed.append(f"{p} ({e.__class__.__name__})")
            log(f"예전 버전 옮기기 실패: {p}: {e}")
    return failed


def copy_payload(src: Path, dest: Path) -> None:
    if not (src / "MYDAF.exe").exists():
        raise RuntimeError(f"설치 파일 안에 MYDAF 프로그램이 없어요: {src}")
    if dest.exists():
        shutil.rmtree(dest)                   # 예전 폴더형 설치만 지운다 (사용자 데이터는 다른 폴더)
    shutil.copytree(src, dest)
    install.strip_mark_of_web(dest / "MYDAF.exe")


def payload_version() -> str:
    try:
        from mydaf.gui import VERSION
        return VERSION
    except Exception:
        return ""


def main() -> None:
    root = tk.Tk()
    root.withdraw()
    ver = payload_version()
    log(f"설치 시작 {ver} ({sys.executable})")
    while mydaf_running():
        if not messagebox.askretrycancel(
                "MYDAF 설치",
                "MYDAF 가 지금 켜져 있어요.\n\n글을 쓰는 중이면 끝날 때까지 기다린 뒤 MYDAF 창을 닫고 '다시 시도'를 눌러 주세요.\n"
                "(작업 표시줄 오른쪽 아래 숨은 아이콘도 확인해 주세요.)"):
            log("취소: MYDAF 실행 중")
            return
    win = tk.Toplevel(root)
    win.title("MYDAF 설치")
    win.geometry("360x110")
    tk.Label(win, text=f"MYDAF {ver} 를 설치하고 있어요…\n잠시만 기다려 주세요.", font=("Malgun Gothic", 11), pady=24).pack()
    win.update()
    try:
        legacy = install.install_dir()          # 1.5.8 은 app 하위 폴더 없이 설치됐다
        if (legacy / "_internal").exists():
            shutil.rmtree(legacy / "_internal", ignore_errors=True)
            (legacy / "MYDAF.exe").unlink(missing_ok=True)
        dest = install.app_install_dir()
        copy_payload(payload_dir(), dest)
        exe = dest / "MYDAF.exe"
        shortcut = install.create_desktop_shortcut(exe)
        flag = app_dir() / "desktop_shortcut_done"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(shortcut, encoding="utf-8")
        log(f"설치 완료: {exe}, 아이콘 {shortcut}")
    except Exception as e:
        log("설치 실패\n" + traceback.format_exc())
        win.destroy()
        messagebox.showerror("MYDAF 설치", f"설치하지 못했어요.\n\n{e}\n\n자세한 내용: {app_dir() / 'logs' / 'setup.log'}")
        return
    win.destroy()

    old = find_old_copies()
    if old and messagebox.askyesno(
            "예전 버전 정리",
            "예전 MYDAF.exe 가 남아 있어요. 이걸 켜면 옛 버전이 다시 켜져요.\n\n" + "\n".join(map(str, old)) +
            "\n\n이 파일들을 치워 둘까요? (지우지 않고 MYDAF\\old-versions 폴더로 옮겨요)"):
        failed = move_old(old)
        if failed:
            messagebox.showwarning("예전 버전 정리", "옮기지 못한 파일이 있어요. 직접 지워 주세요:\n\n" + "\n".join(failed))

    subprocess.Popen([str(exe)], cwd=str(dest), creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    messagebox.showinfo("MYDAF 설치", f"MYDAF {ver} 설치가 끝났어요.\n이제 바탕화면의 MYDAF 아이콘으로 켜시면 됩니다.\n\n"
                                       "이 설치 파일(MYDAF-Setup.exe)은 지워도 돼요.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("예상 못 한 오류\n" + traceback.format_exc())
        raise
