"""브라우저를 띄우지 않고 저장된 네이버 로그인 쿠키가 살아 있는지 확인 (켤 때 빠르게)."""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from .config import app_dir

# Chromium 쿠키 시각: 1601-01-01 기준 마이크로초
_EPOCH_DELTA = 11644473600


def profile_dir() -> Path:
    return app_dir() / "browser-profile"


def _cookie_db(profile: Path) -> Path | None:
    for p in (profile / "Default" / "Network" / "Cookies", profile / "Default" / "Cookies"):
        if p.exists():
            return p
    return None


def quick_login_state(profile: Path | None = None) -> bool | None:
    """True = 로그인 유지 쿠키 있음, False = 없음, None = 판단 불가(브라우저로 확인 필요)."""
    profile = profile or profile_dir()
    if not profile.exists():
        return False
    db = _cookie_db(profile)
    if db is None:
        return None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "c.db"
            shutil.copyfile(db, copy)            # 브라우저가 잡고 있어도 읽을 수 있게 복사본으로
            con = sqlite3.connect(str(copy))
            try:
                rows = con.execute(
                    "SELECT expires_utc, has_expires, is_persistent FROM cookies "
                    "WHERE name='NID_AUT' AND host_key LIKE '%naver.com'").fetchall()
            finally:
                con.close()
    except Exception:
        return None
    if not rows:
        return False
    now = (time.time() + _EPOCH_DELTA) * 1_000_000
    for expires, has_expires, persistent in rows:
        if persistent and (not has_expires or expires > now):
            return True
    return None      # 세션 쿠키뿐이면 브라우저로 한 번 확인
