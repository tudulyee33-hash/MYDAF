"""네이버 블로그 발행. 이 PC에 설치된 Edge/Chrome 을 자동 조작한다 (로그인은 사용자가 직접 1회).

로그인 정보는 저장하지 않고, 브라우저 프로필(쿠키)만 %APPDATA%\\MYDAF\\browser-profile 에 남는다.
스마트에디터 ONE 화면 구조가 바뀌면 SELECTORS 만 고치면 된다.
"""
from __future__ import annotations

import os
import random
import time
from pathlib import Path

from playwright.sync_api import BrowserContext, Frame, Page, TimeoutError as PWTimeout, sync_playwright

from .config import app_dir
from .logs import log

PROFILE = app_dir() / "browser-profile"
LOGIN_URL = "https://nid.naver.com/nidlogin.login?url=https%3A%2F%2Fblog.naver.com%2F"

SELECTORS = {
    "frame": "#mainFrame",
    "title": ".se-documentTitle .se-text-paragraph",
    "body": ".se-main-container .se-component.se-text .se-text-paragraph",
    "popup_cancel": ".se-popup-button-cancel",          # '작성 중인 글이 있습니다' → 취소(새로 쓰기)
    "help_close": ".se-help-panel-close-button",
    "popup_close": ".se-popup-close-button",
    "font_size_btn": "button[data-name='font-size'], .se-font-size-code-toolbar-button",
    "font_size_opt": "button[data-name='font-size'][data-value='fs{size}']",
    "align_btn": "button[data-name='align'], .se-align-left-toolbar-button, .se-align-center-toolbar-button",
    "align_opt": "button[data-name='align'][data-value='{align}'], .se-toolbar-option-align-{align}-button",
    "publish_open": "button[data-click-area='tpb.publish']",
    "publish_confirm": "[data-testid='seOnePublishBtn']",
    "save_draft": "button[data-click-area='tpb.save'], button.save_btn__bzc5B",
    "tag_input": "#tag-input",
    "category_btn": "[data-click-area='tpb*i.category']",
}


def human_pause(a=0.25, b=0.7):
    time.sleep(random.uniform(a, b))


class NaverBlog:
    def __init__(self, blog_id: str, channel: str = "msedge", headless: bool = False):
        self.blog_id = blog_id
        self.channel = channel
        self.headless = headless
        self._pw = None
        self.ctx: BrowserContext | None = None

    # ------------------------------------------------------------ 브라우저
    def __enter__(self):
        self._pw = sync_playwright().start()
        PROFILE.mkdir(parents=True, exist_ok=True)
        exe = os.environ.get("MYDAF_BROWSER_PATH")   # 테스트/특수 환경용
        self.ctx = self._pw.chromium.launch_persistent_context(
            str(PROFILE), headless=self.headless,
            **({"executable_path": exe} if exe else {"channel": self.channel}),
            viewport={"width": 1400, "height": 950}, locale="ko-KR",
            args=["--disable-blink-features=AutomationControlled"],
        )
        return self

    def __exit__(self, *exc):
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self._pw:
                self._pw.stop()

    def page(self) -> Page:
        return self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

    def is_logged_in(self) -> bool:
        return any(c["name"] == "NID_AUT" for c in self.ctx.cookies("https://naver.com"))

    def login_interactive(self, wait_seconds: int = 300) -> bool:
        """로그인 창을 띄우고 사용자가 직접 로그인할 때까지 기다린다."""
        p = self.page()
        p.goto(LOGIN_URL)
        end = time.time() + wait_seconds
        while time.time() < end:
            if self.is_logged_in():
                return True
            time.sleep(2)
        return False

    # ------------------------------------------------------------ 에디터 도우미
    def _editor(self, p: Page) -> Frame:
        p.wait_for_selector(SELECTORS["frame"], timeout=30000)
        frame = p.frame(name="mainFrame") or p.frame_locator(SELECTORS["frame"]).owner.content_frame()
        frame.wait_for_selector(SELECTORS["title"], timeout=30000)
        return frame

    def _dismiss(self, f: Frame):
        for key in ("popup_cancel", "help_close", "popup_close"):
            loc = f.locator(SELECTORS[key])
            for i in range(loc.count()):
                try:
                    if loc.nth(i).is_visible():
                        loc.nth(i).click(timeout=2000)
                        human_pause()
                except Exception:
                    pass

    def _click_first_visible(self, f: Frame, selector: str) -> bool:
        loc = f.locator(selector)
        for i in range(loc.count()):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    el.click(timeout=3000)
                    return True
            except Exception:
                continue
        return False

    def _font_size(self, f: Frame, size: int) -> bool:
        if not self._click_first_visible(f, SELECTORS["font_size_btn"]):
            return False
        human_pause(0.15, 0.3)
        return self._click_first_visible(f, SELECTORS["font_size_opt"].format(size=size))

    def _align(self, f: Frame, align: str) -> bool:
        if self._click_first_visible(f, SELECTORS["align_opt"].format(align=align)):
            return True
        if not self._click_first_visible(f, SELECTORS["align_btn"]):
            return False
        human_pause(0.15, 0.3)
        return self._click_first_visible(f, SELECTORS["align_opt"].format(align=align))

    def _type(self, p: Page, text: str):
        p.keyboard.insert_text(text)
        human_pause(0.1, 0.3)

    # ------------------------------------------------------------ 글쓰기
    def write(self, title: str, blocks: list[dict], tags: list[str], mode: str = "draft",
              category: str = "", shot_dir: Path | None = None) -> dict:
        p = self.page()
        p.goto(f"https://blog.naver.com/{self.blog_id}?Redirect=Write")
        f = self._editor(p)
        time.sleep(1.5)
        self._dismiss(f)
        warnings: list[str] = []

        f.locator(SELECTORS["title"]).first.click()
        self._type(p, title)

        f.locator(SELECTORS["body"]).first.click()
        human_pause()
        self._font_size(f, 15) or warnings.append("본문 글자 크기 지정 실패")
        for b in blocks:
            if b["type"] == "heading":
                p.keyboard.press("Enter")
                self._font_size(f, 19) or warnings.append("소제목 크기 지정 실패")
                p.keyboard.press("Control+b")
                self._type(p, b["text"])
                p.keyboard.press("Control+b")
                p.keyboard.press("Enter")
                self._font_size(f, 15)
            elif b["type"] == "para":
                self._type(p, b["text"])
                p.keyboard.press("Enter")
                p.keyboard.press("Enter")
            elif b["type"] == "citations":
                p.keyboard.press("Enter")
                self._align(f, b["align"]) or warnings.append(f"출처 {b['align']} 정렬 실패")
                self._font_size(f, b["size"]) or warnings.append("출처 작은 글씨 지정 실패")
                for line in b["lines"]:
                    self._type(p, line)
                    p.keyboard.press("Enter")
        human_pause(1, 2)
        if shot_dir:
            p.screenshot(path=str(shot_dir / "editor.png"), full_page=True)

        if mode == "publish":
            url = self._publish(p, f, tags, category, warnings)
            status = "published" if url else "unknown"
        else:
            ok = self._click_first_visible(f, SELECTORS["save_draft"])
            if not ok:
                ok = self._click_text(f, "저장")
            time.sleep(2)
            url, status = "", ("draft" if ok else "draft_failed")
        if shot_dir:
            p.screenshot(path=str(shot_dir / "after.png"))
        return {"status": status, "url": url, "warnings": warnings}

    def _click_text(self, f: Frame, text: str) -> bool:
        try:
            f.get_by_role("button", name=text, exact=True).first.click(timeout=3000)
            return True
        except Exception:
            return False

    def _publish(self, p: Page, f: Frame, tags: list[str], category: str, warnings: list[str]) -> str:
        if not (self._click_first_visible(f, SELECTORS["publish_open"]) or self._click_text(f, "발행")):
            raise RuntimeError("발행 버튼을 찾지 못했습니다 (에디터 화면이 바뀌었을 수 있음)")
        time.sleep(1.2)
        if category:
            try:
                f.locator(SELECTORS["category_btn"]).first.click(timeout=3000)
                f.get_by_text(category, exact=True).first.click(timeout=3000)
            except Exception:
                warnings.append(f"카테고리 '{category}' 선택 실패 → 기본 카테고리")
        try:
            tag_box = f.locator(SELECTORS["tag_input"]).first
            tag_box.click(timeout=3000)
            for t in tags[:10]:
                self._type(p, t.replace("#", "").strip())
                p.keyboard.press("Enter")
        except Exception:
            warnings.append("태그 입력 실패")
        human_pause(0.8, 1.5)
        confirm = f.locator(SELECTORS["publish_confirm"])
        clicked = False
        for i in range(confirm.count()):
            if confirm.nth(i).is_visible() and confirm.nth(i).inner_text().strip() == "발행":
                confirm.nth(i).click()
                clicked = True
                break
        if not clicked:
            raise RuntimeError("발행 확인 버튼을 찾지 못했습니다")
        try:
            p.wait_for_url(lambda u: "Redirect=Write" not in u and ("logNo" in u or "PostView" in u
                                                                    or u.rstrip("/").split("/")[-1].isdigit()),
                           timeout=30000)
        except PWTimeout:
            warnings.append("발행 후 글 주소 확인 실패")
            return ""
        return p.url
