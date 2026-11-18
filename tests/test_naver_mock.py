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
 <button data-name="image" class="se-image-toolbar-button" onclick="document.getElementById('file').click()">사진</button>
 <input type="file" id="file" style="display:none" onchange="addImage()">
 <button data-name="quotation" onclick="addQuote()">인용구</button>
 <button data-name="font-size" class="se-font-size-code-toolbar-button" onclick="document.getElementById('fs').style.display='block'">크기</button>
 <div id="fs" style="display:none">
  <button data-name="font-size" data-value="fs11" onclick="setFs(11)">11</button>
  <button data-name="font-size" data-value="fs30" onclick="setFs(30)">30</button>
  <button data-name="font-size" data-value="fs34" onclick="setFs(34)">34</button></div>
 <button data-name="align" class="se-align-left-toolbar-button" onclick="document.getElementById('al').style.display='block'">정렬</button>
 <div id="al" style="display:none"><button data-name="align" data-value="right" onclick="log.push('align:right');this.parentNode.style.display='none'">우</button></div>
 <button data-click-area="tpb.save" onclick="log.push('save')">저장</button>
</div>
<div class="se-documentTitle"><p class="se-text-paragraph" contenteditable="true" id="title"></p></div>
<div class="se-main-container" id="main"></div>
<script>
 var log=[], main=document.getElementById('main'), last=null;
 function textComp(){const d=document.createElement('div');d.className='se-component se-text';
   const p=document.createElement('p');p.className='se-text-paragraph';p.contentEditable='true';
   p.addEventListener('focus',()=>last=p);d.appendChild(p);return d;}
 main.appendChild(textComp());
 function after(comp){const t=textComp();comp.after(t);return t;}
 function curComp(){return (last||main.querySelector('.se-text-paragraph')).closest('.se-component');}
 function addQuote(){const q=document.createElement('div');q.className='se-component se-quotation';
   const p=document.createElement('p');p.className='se-text-paragraph';p.contentEditable='true';
   p.addEventListener('focus',()=>last=p);q.appendChild(p);curComp().after(q);after(q);p.focus();log.push('quote');}
 function addImage(){const i=document.createElement('div');i.className='se-component se-image';i.textContent='[IMG]';
   const c=curComp();c.after(i);after(i);log.push('image');}
 function setFs(n){log.push('fs:'+n);document.getElementById('fs').style.display='none';if(last)last.focus()}
 document.querySelectorAll('.toolbar button').forEach(b=>b.addEventListener('mousedown',e=>e.preventDefault()));
</script></body></html>"""


def test_write_flow_on_mock_editor(monkeypatch, tmp_path):
    monkeypatch.setenv("MYDAF_BROWSER_PATH", BROWSER)
    from mydaf import naver

    img = tmp_path / "img1.jpg"
    img.write_bytes(b"\xff\xd8" + b"0" * 6000)

    def route(r):
        url = r.request.url
        r.fulfill(status=200, content_type="text/html; charset=utf-8",
                  body=EDITOR if url.endswith("/editor") else OUTER)

    steps = []
    with naver.NaverBlog("me", headless=True) as nb:
        nb.ctx.route("https://blog.naver.com/**", route)
        blocks = [{"type": "para", "text": "도입 문단", "size": 30},
                  {"type": "heading", "text": "소제목 하나", "size": 34, "style": "quote"},
                  {"type": "image", "path": str(img)},
                  {"type": "para", "text": "본문 문단", "size": 30},
                  {"type": "citations", "lines": ["출처", "[1] A일보, 「기사」 https://a.co.kr"], "align": "right", "size": 11}]
        res = nb.write("테스트 제목", blocks, ["태그"], mode="draft",
                       on_progress=lambda f, m: steps.append(round(f, 2)))
        f = nb.page().frame(name="mainFrame")
        log = f.evaluate("log")
        title = f.inner_text("#title")
        quote = f.inner_text(".se-quotation")
        order = f.evaluate("[...document.querySelectorAll('#main > .se-component')].map(c => "
                           "c.classList.contains('se-quotation') ? 'Q:' + c.innerText : "
                           "c.classList.contains('se-image') ? 'IMG' : c.innerText.trim()).filter(Boolean)")

    assert res["status"] == "draft", res
    assert res["warnings"] == [], res["warnings"]
    assert title == "테스트 제목"
    assert quote.strip() == "소제목 하나"                       # 소제목은 인용구 안에
    # 순서: 도입 → 인용구 소제목 → 사진 → 본문 → 출처
    assert order[0].startswith("도입 문단") and order[1] == "Q:소제목 하나" and order[2] == "IMG"
    assert "본문 문단" in order[3] and "[1] A일보" in order[3]
    assert log[0] == "popup" and log[-1] == "save"
    assert "fs:30" in log and "fs:34" in log and "fs:11" in log
    assert log.index("align:right") < log.index("fs:11")
    assert steps[0] == 0 and steps[-1] == 1
