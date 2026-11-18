import sqlite3
import time

from mydaf import logincheck


def _db(profile, rows):
    d = profile / "Default" / "Network"
    d.mkdir(parents=True)
    con = sqlite3.connect(str(d / "Cookies"))
    con.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, expires_utc INTEGER, has_expires INTEGER, is_persistent INTEGER)")
    con.executemany("INSERT INTO cookies VALUES (?,?,?,?,?)", rows)
    con.commit()
    con.close()


def _future():
    return int((time.time() + 11644473600 + 86400) * 1_000_000)


def test_quick_login_logged_in(tmp_path):
    _db(tmp_path, [(".naver.com", "NID_AUT", _future(), 1, 1)])
    assert logincheck.quick_login_state(tmp_path) is True


def test_quick_login_missing_or_expired(tmp_path):
    _db(tmp_path, [(".naver.com", "NID_SES", _future(), 1, 1)])
    assert logincheck.quick_login_state(tmp_path) is False
    assert logincheck.quick_login_state(tmp_path / "nope") is False


def test_quick_login_session_cookie_unsure(tmp_path):
    _db(tmp_path, [(".naver.com", "NID_AUT", 0, 0, 0)])
    assert logincheck.quick_login_state(tmp_path) is None


def test_gui_import_skips_heavy_modules():
    import subprocess, sys
    code = "import sys, mydaf.gui; print(','.join(m for m in ('anthropic','bs4','feedparser','playwright') if m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""


def test_setup_copy_payload(tmp_path):
    import setup_mydaf
    src = tmp_path / "src"; (src / "_internal").mkdir(parents=True)
    (src / "MYDAF.exe").write_text("new"); (src / "_internal" / "a.dll").write_text("x")
    dest = tmp_path / "dest"; (dest / "_internal").mkdir(parents=True)
    (dest / "_internal" / "old.dll").write_text("o"); (dest / "MYDAF.exe").write_text("old")
    setup_mydaf.copy_payload(src, dest)
    assert (dest / "MYDAF.exe").read_text() == "new"
    assert not (dest / "_internal" / "old.dll").exists()
    assert (dest / "_internal" / "a.dll").exists()
