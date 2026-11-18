import json
import os
import tempfile

os.environ.setdefault("MYDAF_HOME", tempfile.mkdtemp())

from mydaf import render, sources, verify  # noqa: E402
from mydaf.config import Config  # noqa: E402
from mydaf.sources import Source  # noqa: E402


def srcs():
    return [
        Source("news", "전기차 보조금 확대", "https://a.co.kr/1", "A일보", "2026-11-10",
               text="환경부는 2027년 전기차 보조금을 대당 최대 650만원으로 정했다고 밝혔다. 신청은 1월부터다.", id="S1"),
        Source("news", "보조금 650만원", "https://news.google.com/rss/articles/x", "B경제", "2026-11-11",
               text="정부가 내년 전기차 보조금을 대당 최대 650만원으로 정했다고 밝혔다.", id="S2",
               meta={"publisher_site": "https://www.b-econ.com"}),
        Source("kiss", "전기차 확산 요인 연구", "https://kiss.kstudy.com/Detail/Ar?key=1", "KISS", "2025",
               text="보조금 수준은 전기차 구매 의향에 유의한 영향을 미친다.", id="S3",
               meta={"citation_author": "홍길동", "citation_journal_title": "교통연구"}),
    ]


def test_quote_matching_ignores_spacing_and_quotes():
    assert verify.quote_in_text("대당  최대 “650만원”으로", "대당 최대 650만원으로 정했다")
    assert not verify.quote_in_text("대당 최대 700만원", "대당 최대 650만원으로 정했다")


def test_verify_counts_independent_outlets_and_rejects_fake_quotes():
    extracted = {"facts": [
        {"statement": "2027년 보조금 최대 650만원", "evidence": [
            {"source_id": "S1", "quote": "보조금을 대당 최대 650만원으로 정했다"},
            {"source_id": "S2", "quote": "보조금을 대당 최대 650만원으로 정했다"}]},
        {"statement": "신청은 1월부터", "evidence": [{"source_id": "S1", "quote": "신청은 1월부터다"}]},
        {"statement": "지어낸 사실", "evidence": [{"source_id": "S2", "quote": "보조금이 폐지된다고 밝혔다"},
                                               {"source_id": "S9", "quote": "아무거나 아무거나"}]},
    ], "conflicts": []}
    r = verify.verify_facts(extracted, srcs(), min_outlets=2, allow_single=False)
    assert [f["statement"] for f in r["verified"]] == ["2027년 보조금 최대 650만원"]
    assert r["verified"][0]["outlets"] == ["a.co.kr", "b-econ.com"]   # 구글뉴스 링크는 원 매체로
    assert len(r["single"]) == 1 and len(r["rejected"]) == 1
    assert [f["id"] for f in r["usable"]] == ["F1"]
    r2 = verify.verify_facts(extracted, srcs(), min_outlets=2, allow_single=True)
    assert len(r2["usable"]) == 2


def test_check_draft_drops_unsupported_and_unreasoned_paragraphs():
    usable = [{"id": "F1", "evidence": [{"source_id": "S1"}, {"source_id": "S2"}]}]
    post = {"title": "t", "intro": "i", "conclusion": "c", "tags": [], "sections": [
        {"heading": "h1", "paragraphs": [
            {"text": "사실", "fact_ids": ["F1"], "is_inference": False, "inference_reasoning": ""},
            {"text": "근거없음", "fact_ids": ["F7"], "is_inference": False, "inference_reasoning": ""},
            {"text": "추론", "fact_ids": ["F1"], "is_inference": True, "inference_reasoning": "F1에서 수요 증가 추정"},
            {"text": "근거 없는 추론", "fact_ids": [], "is_inference": True, "inference_reasoning": " "}]},
        {"heading": "빈 섹션", "paragraphs": [
            {"text": "x", "fact_ids": [], "is_inference": False, "inference_reasoning": ""}]}]}
    review = verify.check_draft(post, usable)
    assert [p["text"] for p in post["sections"][0]["paragraphs"]] == ["사실", "추론"]
    assert len(post["sections"]) == 1
    assert len(review["removed"]) == 3
    assert review["inferences"][0]["reasoning"] == "F1에서 수요 증가 추정"
    cited = verify.cited_sources(post, usable, srcs())
    assert [s.id for s in cited] == ["S1", "S2"]


def test_render_citations_small_and_aligned():
    post = {"intro": "도입", "conclusion": "끝", "sections": [{"heading": "소제목", "paragraphs": [{"text": "본문"}]}]}
    blocks = render.to_blocks(post, srcs(), align="right", font_size=11)
    cit = blocks[-1]
    assert cit["type"] == "citations" and cit["align"] == "right" and cit["size"] == 11
    assert cit["lines"][0] == "출처"
    assert "A일보" in cit["lines"][1] and "https://a.co.kr/1" in cit["lines"][1]
    assert "홍길동" in cit["lines"][3] and "KISS" in cit["lines"][3]
    html = render.preview_html("제목", blocks, ["a"])
    assert "text-align:right" in html and "font-size:11px" in html


def test_google_news_rss_parsing():
    xml = """<?xml version="1.0"?><rss><channel><item><title>보조금 확대 - B경제</title>
    <link>https://news.google.com/rss/articles/abc</link><pubDate>Tue, 11 Nov 2026 01:00:00 GMT</pubDate>
    <source url="https://www.b-econ.com">B경제</source><description>&lt;a&gt;요약&lt;/a&gt;</description></item></channel></rss>"""
    items = sources.parse_google_news_rss(xml, 5)
    assert items[0].title == "보조금 확대" and items[0].publisher == "B경제"
    assert items[0].published == "2026-11-11" and items[0].outlet == "b-econ.com"


def test_kiss_parsing():
    data = {"code": "200", "resultList": [
        {"AKEYN": 2688024, "TLKO": "초고층 건물 <!HS>구급대<!HE> 수직이송시간", "AUTH": "홍길동", "AYEAR": "2008",
         "VOL1": "12", "NUM1": "3", "PNMEK": "한국화재소방학회", "KAST": "초록 내용입니다. " * 20, "KEYW": "초고층"},
        {"AKEYN": "", "TLKO": "키 없음"}, {"AKEYN": 5, "TLKO": "초록 없음", "KAST": ""}]}
    items = sources.parse_kiss_data(data, 5)
    assert len(items) == 1 and items[0].url == "https://kiss.kstudy.com/Detail/Ar?key=2688024"
    assert items[0].title == "초고층 건물 구급대 수직이송시간"
    assert "초록 내용입니다." in items[0].text and "한국화재소방학회" in items[0].text
    assert items[0].published == "2008"


def test_article_text_extraction():
    page = "<html><nav>메뉴</nav><article><p>" + "본문 문장입니다. " * 30 + "</p></article><footer>저작권</footer></html>"
    t = sources.extract_article_text(page)
    assert "본문 문장" in t and "메뉴" not in t and "저작권" not in t


def test_config_roundtrip_and_unlimited_keywords():
    c = Config()
    long_kw = "가" * 500
    c.update({"keywords": "\n".join([long_kw] + [f"키워드{i}" for i in range(300)]),
              "daily_limit": "2", "use_kiss": "false", "unknown": 1})
    c.save()
    c2 = Config.load()
    assert c2.keywords[0] == long_kw and len(c2.keywords) == 301
    assert c2.daily_limit == 2 and c2.use_kiss is False
    assert json.loads(Config.path().read_text(encoding="utf-8"))["daily_limit"] == 2


def test_commons_parsing_keeps_only_free_licenses():
    from mydaf import images
    data = {"query": {"pages": {
        "1": {"index": 2, "imageinfo": [{"thumburl": "https://u/a.jpg", "width": 2000, "descriptionurl": "https://c/a",
                                         "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                                                         "Artist": {"value": "<a href='x'>Kim</a>"}}}]},
        "2": {"index": 1, "imageinfo": [{"thumburl": "https://u/b.jpg", "width": 2000,
                                         "extmetadata": {"LicenseShortName": {"value": "All rights reserved"}}}]},
        "3": {"index": 3, "imageinfo": [{"thumburl": "https://u/c.jpg", "width": 300,
                                         "extmetadata": {"LicenseShortName": {"value": "CC0"}}}]},
    }}}
    out = images.parse_commons(data)
    assert [o["url"] for o in out] == ["https://u/a.jpg"]
    assert out[0]["credit"] == "Kim, CC BY-SA 4.0, Wikimedia Commons"


def test_blocks_put_image_under_heading_and_credit_in_citations():
    from mydaf.images import Picture
    post = {"intro": "도입", "conclusion": "끝", "sections": [
        {"heading": "A", "paragraphs": [{"text": "a"}]}, {"heading": "B", "paragraphs": [{"text": "b"}]}]}
    pics = [Picture("/x/img1.jpg", "Kim, CC0, Wikimedia Commons", ""), None]
    blocks = render.to_blocks(post, [], images=pics, heading_size=34, body_size=30)
    kinds = [b["type"] for b in blocks]
    assert kinds == ["para", "heading", "image", "para", "heading", "para", "para", "citations"]
    assert blocks[1]["size"] == 34 and blocks[1]["style"] == "quote" and blocks[0]["size"] == 30
    assert blocks[-1]["lines"][-1] == "[사진] Kim, CC0, Wikimedia Commons"


def test_keywords_split_on_commas():
    from mydaf.config import Config, split_keywords
    assert split_keywords([",초고층외관특성,도시ai자동화, 경관,", "경관\n차폐율"]) == ["초고층외관특성", "도시ai자동화", "경관", "차폐율"]
    c = Config(keywords=["a, b", "c"])
    assert c.keywords == ["a", "b", "c"]
