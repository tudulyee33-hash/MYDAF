"""화면이 오류 없이 뜨고 각 페이지로 이동되는지 (디스플레이가 있을 때만)."""
import os
import tempfile

import pytest

os.environ.setdefault("MYDAF_HOME", tempfile.mkdtemp())
tk = pytest.importorskip("tkinter")


def _display_ok():
    try:
        r = tk.Tk()
        r.destroy()
        return True
    except tk.TclError:
        return False


@pytest.mark.skipif(not _display_ok(), reason="디스플레이 없음")
def test_all_pages_render(monkeypatch):
    from mydaf import gui, install
    monkeypatch.setattr(install, "startup_check", lambda d: None)
    app = gui.App()
    try:
        assert app.current == "setup"              # 처음 실행 → 설정 마법사
        app.setup_key.set("gm-test")
        app.finish_setup()
        assert app.current == "home" and app.cfg.setup_done
        assert app.cfg.ai_provider == "gemini" and app.cfg.gemini_api_key == "gm-test"
        for key in ("history", "keywords", "sources", "quality", "publish", "remote", "home"):
            app.show(key)
            app.root.update()
        assert "자동 등록 시작" in app.big_btn.cget("text")
    finally:
        app.root.destroy()
