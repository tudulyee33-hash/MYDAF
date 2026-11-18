"""스마트에디터 ONE 을 흉내 낸 가짜 페이지로 브라우저 조작 순서를 확인한다.
실제 네이버 화면과 100% 같지는 않으므로, 실제 계정 테스트는 임시저장 모드로 따로 해야 한다."""
import os
import shutil
import tempfile

import pytest

os.environ.setdefault("MYDAF_HOME", tempfile.mkdtemp())
BROWSER = os.environ.get("MYDAF_BROWSER_PATH") or shutil.which("chromium") or "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome"
pytestmark = pytest.mark.skipif(not os.path.exists(BROWSER), reason="테스트용 크로미움 없음")

OUTER = "<html><body><iframe id='mainFrame' name='mainFrame' src='https://blog.naver.com/editor' style='width:1300px;height:900px'></iframe></body></html>"
EDITOR = """<html><body>
<div class="se-popup-container"><button class="se-popup-button-cancel" onclick="this.parentNode.remove();log.push('popup')">취소</button></div>
<div class="toolbar">
 <button data-name="font-size" class="se-font-size-code-toolbar-button" onclick="document.getElementById('fs').style.display='block'">크기</button>
 <div id="fs" style="display:none">
  <button data-name="font-size" data-value="fs11" onclick="setFs(11)">11</button>
  <button data-name="font-size" data-value="fs15" onclick="setFs(15)">15</button>
  <button data-name="font-size" data-value="fs19" onclick="setFs(19)">19</button></div>
 <button data-name="align" class="se-align-left-toolbar-button" onclick="document.getElementById('al').style.display='block'">정렬</button>
 <div id="al" style="display:none"><button data-name="align" data-value="right" onclick="log.push('align:right');this.parentNode.style.display='none'">우</button></div>
 <button data-click-area="tpb.save" onclick="log.push('save')">저장</button>
</div>
<div class="se-documentTitle"><p class="se-text-paragraph" contenteditable="true" id="title"></p></div>
<div class="se-main-container"><div class="se-component se-text"><p class="se-text-paragraph" contenteditable="true" id="body"></p></div></div>
<script>
 var log=[];
 function setFs(n){log.push('fs:'+n);document.getElementById('fs').style.display='none';document.getElementById('body').focus()}
 // 버튼 클릭 후에도 커서를 본문에 유지 (실제 에디터와 비슷하게)
 document.querySelectorAll('.toolbar button').forEach(b=>b.addEventListener('mousedown',e=>e.preventDefault()));
</script></body></html>"""


def test_write_flow_on_mock_editor(monkeypatch):
    monkeypatch.setenv("MYDAF_BROWSER_PATH", BROWSER)
    from mydaf import naver

    def route(r):
        url = r.request.url
        r.fulfill(status=200, content_type="text/html; charset=utf-8",
                  body=EDITOR if url.endswith("/editor") else OUTER)

    with naver.NaverBlog("me", headless=True) as nb:
        nb.ctx.route("https://blog.naver.com/**", route)
        blocks = [{"type": "para", "text": "도입 문단"},
                  {"type": "heading", "text": "소제목"},
                  {"type": "para", "text": "본문 문단"},
                  {"type": "citations", "lines": ["출처", "[1] A일보, 「기사」 https://a.co.kr"], "align": "right", "size": 11}]
        res = nb.write("테스트 제목", blocks, ["태그"], mode="draft")
        f = nb.page().frame(name="mainFrame")
        log = f.evaluate("log")
        title = f.inner_text("#title")
        body = f.inner_text("#body")

    assert res["status"] == "draft", res
    assert title == "테스트 제목"
    assert "도입 문단" in body and "소제목" in body and "[1] A일보" in body
    assert log[0] == "popup" and log[-1] == "save"
    assert "align:right" in log and "fs:11" in log and "fs:19" in log
    assert log.index("align:right") < log.index("fs:11")
    assert res["warnings"] == []
