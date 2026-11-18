"""MYDAF 설치 프로그램 (MYDAF-Setup.exe).

PyInstaller onedir 로 만든 MYDAF 폴더를 %LOCALAPPDATA%\\Programs\\MYDAF 에 풀고,
바탕화면 아이콘을 만든 뒤 MYDAF 를 켠다. 한 번만 풀어 두므로 이후에는 켤 때마다 압축을 풀지 않아 빠르다.
설정·로그·네이버 로그인(%APPDATA%\\MYDAF)은 건드리지 않는다.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from mydaf import install
from mydaf.config import app_dir


def payload_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "payload"


def mydaf_running(port: int = 47613) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def copy_payload(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    # 예전 버전 프로그램 파일만 지운다 (사용자 데이터는 다른 폴더에 있음)
    old_internal = dest / "_internal"
    if old_internal.exists():
        shutil.rmtree(old_internal, ignore_errors=True)
    old_exe = dest / "MYDAF.exe"
    if old_exe.exists():
        old_exe.unlink()
    shutil.copytree(src, dest, dirs_exist_ok=True)
    install.strip_mark_of_web(dest / "MYDAF.exe")


def main() -> None:
    root = tk.Tk()
    root.withdraw()
    while mydaf_running():
        if not messagebox.askretrycancel(
                "MYDAF 설치",
                "MYDAF 가 지금 켜져 있어요.\n\n글을 쓰는 중이면 끝날 때까지 기다린 뒤 MYDAF 창을 닫고 '다시 시도'를 눌러 주세요."):
            return
    win = tk.Toplevel(root)
    win.title("MYDAF 설치")
    win.geometry("360x110")
    tk.Label(win, text="MYDAF 를 설치하고 있어요…\n잠시만 기다려 주세요.", font=("Malgun Gothic", 11), pady=24).pack()
    win.update()
    try:
        dest = install.install_dir()
        copy_payload(payload_dir(), dest)
        exe = dest / "MYDAF.exe"
        shortcut = install.create_desktop_shortcut(exe)
        flag = app_dir() / "desktop_shortcut_done"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text(shortcut, encoding="utf-8")
    except Exception as e:
        win.destroy()
        messagebox.showerror("MYDAF 설치", f"설치하지 못했어요.\n\n{e}")
        return
    win.destroy()
    subprocess.Popen([str(exe)], cwd=str(dest), creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    messagebox.showinfo("MYDAF 설치", "설치가 끝났어요. 이제 바탕화면의 MYDAF 아이콘으로 켜시면 됩니다.\n\n"
                                       "이 설치 파일은 지워도 됩니다.")


if __name__ == "__main__":
    main()
