"""글감 수집: 뉴스, 구글, RSS, KISS, 학회.

모든 수집기는 Source 목록을 돌려준다. 각 Source 에는 원문(가능하면 본문 전체)이 들어가며,
이후 검증 단계에서 '인용문이 실제 원문에 있는지'를 확인하는 데 쓰인다.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import quote, urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from .logs import log

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
TIMEOUT = 15
MAX_TEXT = 12000


@dataclass
class Source:
    kind: str                 # news | google | rss | kiss | society
    title: str
    url: str
    publisher: str = ""
    published: str = ""
    text: str = ""            # 검증에 쓰는 원문 텍스트
    id: str = ""              # S1, S2 ... (수집 후 부여)
    meta: dict = field(default_factory=dict)

    @property
    def domain(self) -> str:
        host = urlparse(self.url).netloc.lower()
        return host[4:] if host.startswith("www.") else host

    @property
    def outlet(self) -> str:
        """독립성 판단 기준(매체). 구글 뉴스는 링크가 news.google.com 이라 원 매체 주소를 쓴다."""
        site = self.meta.get("publisher_site", "")
        if site:
            host = urlparse(site).netloc.lower()
            return host[4:] if host.startswith("www.") else host
        if self.domain in ("news.google.com", "n.news.naver.com", "m.news.naver.com", "news.naver.com", "") \
                and self.publisher:
            return self.publisher.strip().lower()
        return self.domain


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6"})
    return s


HTTP = _session()


def clean(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _date(value: str) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return value[:10]


def extract_article_text(page_html: str) -> str:
    """기사/페이지 HTML에서 본문 텍스트만 추린다."""
    soup = BeautifulSoup(page_html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside", "form", "iframe"]):
        tag.decompose()
    candidates = soup.select("article, #articleBodyContents, #dic_area, #newsct_article, .article_body, "
                             ".news_body, #articeBody, .article-body, main")
    root = max(candidates, key=lambda n: len(n.get_text()), default=soup.body or soup)
    paras = [p.get_text(" ", strip=True) for p in root.find_all(["p", "li", "h2", "h3"])]
    text = " ".join(p for p in paras if len(p) > 20)
    if len(text) < 200:
        text = root.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)[:MAX_TEXT]


def fetch_text(url: str) -> str:
    try:
        r = HTTP.get(url, timeout=TIMEOUT)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
            return ""
        r.encoding = r.apparent_encoding if r.encoding in (None, "ISO-8859-1") else r.encoding
        return extract_article_text(r.text)
    except requests.RequestException as e:
        log.info("본문 가져오기 실패 %s: %s", url, e)
        return ""


# ---------------------------------------------------------------- 뉴스
NAVER_ARTICLE = re.compile(r"https?://n\.news\.naver\.com/(?:mnews/)?article/(\d+)/(\d+)")


def parse_naver_article(page_html: str, url: str) -> Source | None:
    """네이버 뉴스(n.news.naver.com) 기사 한 건: 제목·언론사·날짜·본문."""
    soup = BeautifulSoup(page_html, "html.parser")
    body = soup.select_one("#dic_area, #newsct_article, #articeBody")
    title_el = soup.select_one("#title_area, h2.media_end_head_headline, .media_end_head_headline")
    title = clean(title_el.get_text(" ")) if title_el else ""
    if not title:
        og = soup.find("meta", property="og:title")
        title = clean(og.get("content", "")) if og else ""
    if not (body and title):
        return None
    for tag in body.select("script, style, .img_desc, em.img_desc, .end_photo_org, .media_end_summary"):
        tag.decompose()
    press = ""
    logo = soup.select_one(".media_end_head_top_logo img, .media_end_head_top_logo_img")
    if logo is not None:
        press = clean(logo.get("alt") or logo.get("title") or "")
    if not press:
        m = soup.find("meta", attrs={"name": "twitter:creator"}) or soup.find("meta", property="og:article:author")
        press = clean(m.get("content", "")).split("|")[0].strip() if m else ""
    date_el = soup.select_one("[data-date-time]")
    published = (date_el.get("data-date-time") or "")[:10] if date_el else ""
    original = soup.select_one("a.media_end_head_origin_link")
    meta = {"original_url": original.get("href")} if original is not None and original.get("href") else {}
    return Source("news", title, url, publisher=press, published=published,
                  text=re.sub(r"\s+", " ", body.get_text(" ", strip=True))[:MAX_TEXT], meta=meta)


def naver_article_links(search_html: str, limit: int) -> list[str]:
    seen, out = set(), []
    for m in NAVER_ARTICLE.finditer(search_html.replace("\\/", "/")):
        url = f"https://n.news.naver.com/mnews/article/{m.group(1)}/{m.group(2)}"
        if url not in seen:
            seen.add(url)
            out.append(url)
        if len(out) >= limit:
            break
    return out


def naver_news_web(query: str, limit: int) -> list[Source]:
    """API 키가 없을 때: 네이버 뉴스 검색 화면에서 '네이버뉴스' 기사 링크를 찾아 본문까지 가져온다."""
    r = HTTP.get("https://search.naver.com/search.naver",
                 params={"where": "news", "query": query, "sort": "0"}, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for url in naver_article_links(r.text, limit * 2):
        try:
            a = HTTP.get(url, timeout=TIMEOUT)
            a.raise_for_status()
            src = parse_naver_article(a.text, url)
        except requests.RequestException:
            continue
        if src:
            out.append(src)
        if len(out) >= limit:
            break
    return out


def naver_news(query: str, client_id: str, client_secret: str, limit: int) -> list[Source]:
    """네이버 검색 API(뉴스, developers.naver.com 무료 발급). 키가 없으면 검색 화면에서 가져온다."""
    if not (client_id and client_secret):
        return naver_news_web(query, limit)
    r = HTTP.get("https://openapi.naver.com/v1/search/news.json",
                 params={"query": query, "display": min(limit * 2, 50), "sort": "sim"},
                 headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
                 timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for item in r.json().get("items", [])[:limit]:
        url = item.get("originallink") or item.get("link")
        out.append(Source("news", clean(item.get("title", "")), url,
                          publisher=urlparse(url).netloc, published=_date(item.get("pubDate", "")),
                          text=clean(item.get("description", ""))))
    return out


def parse_google_news_rss(xml: str, limit: int) -> list[Source]:
    feed = feedparser.parse(xml)
    out = []
    for e in feed.entries[:limit]:
        publisher = getattr(getattr(e, "source", None), "title", "") or ""
        title = clean(e.get("title", ""))
        if publisher and title.endswith(" - " + publisher):
            title = title[: -len(publisher) - 3]
        src_url = getattr(getattr(e, "source", None), "href", "") or ""
        out.append(Source("news", title, e.get("link", ""), publisher=publisher,
                          published=_date(e.get("published", "")), text=clean(e.get("summary", "")),
                          meta={"publisher_site": src_url}))
    return out


_GN_DECODE_OK = True     # 한 번 실패하면 이번 실행에서는 다시 시도하지 않음 (시간 절약)


def decode_google_news_url(url: str) -> str:
    """news.google.com/rss/articles/... 링크를 원래 기사 주소로 바꾼다. 실패하면 ''."""
    global _GN_DECODE_OK
    if not _GN_DECODE_OK:
        return ""
    m = re.search(r"/(?:rss/)?articles/([^/?#]+)", url)
    if "news.google.com" not in url or not m:
        return ""
    art_id = m.group(1)
    try:
        page = HTTP.get(f"https://news.google.com/rss/articles/{art_id}", timeout=TIMEOUT).text
        sig = re.search(r'data-n-a-sg="([^"]+)"', page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not (sig and ts):
            return ""
        aid = re.search(r'data-n-a-id="([^"]+)"', page)
        art = aid.group(1) if aid else art_id
        inner = ["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None,
                                 None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                 art, int(ts.group(1)), sig.group(1)]
        r = None
        for freq in (json.dumps([[["Fa2Xvd", json.dumps(inner)]]]),
                     json.dumps([[["Fa2Xvd", json.dumps(inner), None, "generic"]]])):
            r = HTTP.post("https://news.google.com/_/DotsSplashUi/data/batchexecute",
                          data={"f.req": freq}, timeout=TIMEOUT,
                          headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                                   "Referer": "https://news.google.com/"})
            if r.status_code == 200:
                break
        r.raise_for_status()
        payload = json.loads(r.text.split("\n\n", 1)[1])
        found = json.loads(payload[0][2])[1]
        return found if isinstance(found, str) and found.startswith("http") else ""
    except (requests.RequestException, ValueError, IndexError, TypeError, KeyError) as e:
        log.info("구글 뉴스 주소 풀기 실패: %s", e)
        _GN_DECODE_OK = False
        return ""


def google_news(query: str, limit: int) -> list[Source]:
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    r = HTTP.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    return parse_google_news_rss(r.text, limit)


# ---------------------------------------------------------------- 구글 검색
def google_search(query: str, api_key: str, cx: str, limit: int) -> list[Source]:
    """Google Programmable Search JSON API (키가 있을 때만)."""
    if not (api_key and cx):
        return []
    r = HTTP.get("https://www.googleapis.com/customsearch/v1",
                 params={"key": api_key, "cx": cx, "q": query, "num": min(limit, 10), "lr": "lang_ko"},
                 timeout=TIMEOUT)
    r.raise_for_status()
    return [Source("google", clean(i.get("title", "")), i.get("link", ""),
                   publisher=i.get("displayLink", ""), text=clean(i.get("snippet", "")))
            for i in r.json().get("items", [])[:limit]]


# ---------------------------------------------------------------- RSS / 학회
def rss(feed_url: str, query: str, limit: int, kind: str = "rss") -> list[Source]:
    feed = feedparser.parse(HTTP.get(feed_url, timeout=TIMEOUT).content)
    words = [w for w in re.split(r"\s+", query.lower()) if len(w) > 1]
    out = []
    for e in feed.entries:
        blob = (e.get("title", "") + " " + e.get("summary", "")).lower()
        if words and not any(w in blob for w in words):
            continue
        out.append(Source(kind, clean(e.get("title", "")), e.get("link", ""),
                          publisher=clean(feed.feed.get("title", "")) or urlparse(feed_url).netloc,
                          published=_date(e.get("published", "") or e.get("updated", "")),
                          text=clean(e.get("summary", ""))))
        if len(out) >= limit:
            break
    return out


def society(url: str, query: str, limit: int) -> list[Source]:
    """학회 사이트: RSS면 RSS로, 일반 페이지면 제목에 키워드가 들어간 링크를 찾는다."""
    r = HTTP.get(url, timeout=TIMEOUT)
    ctype = r.headers.get("content-type", "")
    if "xml" in ctype or r.text.lstrip().startswith("<?xml") or "<rss" in r.text[:500]:
        return rss(url, query, limit, kind="society")
    soup = BeautifulSoup(r.text, "html.parser")
    site = clean(soup.title.get_text()) if soup.title else urlparse(url).netloc
    words = [w for w in re.split(r"\s+", query) if len(w) > 1]
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        title = clean(a.get_text())
        if len(title) < 6 or not any(w in title for w in words):
            continue
        link = urljoin(url, a["href"])
        if link in seen:
            continue
        seen.add(link)
        out.append(Source("society", title, link, publisher=site))
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- KISS
KISS_DATA_URL = "https://kiss.kstudy.com/Search/Data"


def _kiss_clean(text) -> str:
    return clean(re.sub(r"<!H[SE]>", "", str(text or "")))


def parse_kiss_data(data: dict, limit: int) -> list[Source]:
    """KISS(한국학술정보) 검색 결과(JSON) 파싱. 논문 본문은 유료이므로 제목·저자·학회지·초록만 쓴다."""
    out = []
    for it in (data or {}).get("resultList") or []:
        key = str(it.get("AKEYN") or "").strip()
        title = _kiss_clean(it.get("TLKO") or it.get("TLTO"))
        if not key or not title:
            continue
        abstract = _kiss_clean(it.get("KAST") or it.get("EAST"))
        if len(abstract) < 100:      # 초록 없는 논문은 근거로 쓸 내용이 없어 뺀다
            continue
        year = str(it.get("AYEAR") or "").strip()
        info = " · ".join(x for x in (_kiss_clean(it.get("AUTH")), _kiss_clean(it.get("PNMEK")), year,
                                       f"{it.get('VOL1') or ''}권 {it.get('NUM1') or ''}호".strip()) if x)
        kw = _kiss_clean(it.get("KEYW"))
        text = "\n".join(x for x in (info, ("키워드: " + kw) if kw else "", abstract) if x)
        out.append(Source("kiss", title, f"https://kiss.kstudy.com/Detail/Ar?key={key}",
                          publisher=_kiss_clean(it.get("PNMEK")) or "KISS 한국학술정보", published=year[:4],
                          text=text[:MAX_TEXT], meta={"author": _kiss_clean(it.get("AUTH"))}))
        if len(out) >= limit:
            break
    return out


def kiss(query: str, limit: int) -> list[Source]:
    r = HTTP.post(KISS_DATA_URL, timeout=TIMEOUT,
                  json={"schList": f"all@$@total@$@{query}", "currentPage": 1,
                        "pageRowCount": max(limit * 2, 10), "searchType": "PAGE"},
                  headers={"Referer": "https://kiss.kstudy.com/Search/Result",
                           "X-Requested-With": "XMLHttpRequest"})
    r.raise_for_status()
    return parse_kiss_data(r.json(), limit)


# ---------------------------------------------------------------- 전체 수집
def collect(query: str, cfg, progress: Callable[[str], None] = lambda m: None) -> list[Source]:
    """주제 묶음('a, b, c')이면 검색어마다 따로 찾아 합친다."""
    terms = [t.strip() for t in re.split(r"[,;，、]+", query) if t.strip()]
    if len(terms) > 1:
        # 중심 주제로 넉넉히 찾아 같은 소식을 다룬 여러 매체를 확보하고(교차 검증용),
        # 나머지 검색어는 '중심 주제 + 검색어'로 붙여 찾아 엉뚱한 분야 기사가 섞이지 않게 한다.
        head, rest = terms[0], terms[1:]
        found: list[Source] = []
        progress(f"  [{head}]")
        found += _collect_raw(head, cfg, progress, max(cfg.max_items_per_source, 6))
        for t in rest:
            q = f"{head} {t}"
            progress(f"  [{q}]")
            found += _collect_raw(q, cfg, progress, max(3, cfg.max_items_per_source // 2))
        return _finish(found, progress)
    return _finish(_collect_raw(query, cfg, progress, cfg.max_items_per_source), progress)


def _collect_raw(query: str, cfg, progress, n: int) -> list[Source]:
    jobs: list[tuple[str, Callable[[], list[Source]]]] = [
        ("네이버 뉴스", lambda: naver_news(query, cfg.naver_client_id, cfg.naver_client_secret, n)),
        ("구글 뉴스", lambda: google_news(query, n)),
        ("구글 검색", lambda: google_search(query, cfg.google_api_key, cfg.google_cx, n)),
    ]
    jobs += [(f"RSS {u}", (lambda u=u: rss(u, query, n))) for u in cfg.rss_feeds]
    jobs += [(f"학회 {u}", (lambda u=u: society(u, query, n))) for u in cfg.society_sources]
    if cfg.use_kiss:
        jobs.append(("KISS", lambda: kiss(query, min(n, 4))))

    found: list[Source] = []
    for name, job in jobs:
        try:
            got = job()
            progress(f"  · {name}: {len(got)}건")
            found += got
        except Exception as e:  # 출처 하나가 실패해도 나머지는 계속
            progress(f"  · {name}: 실패 ({e.__class__.__name__})")
            log.warning("수집 실패 %s: %s", name, e)
    return found


def _finish(found: list[Source], progress) -> list[Source]:
    # 중복 제거 + 본문 보강
    unique, seen = [], set()
    for s in found:
        key = s.url.split("?")[0] if s.kind != "news" else s.title
        if not s.url or key in seen:
            continue
        seen.add(key)
        unique.append(s)
    for s in unique:
        if s.kind in ("news", "google", "rss", "society") and len(s.text) < 600:
            url = s.url
            if s.domain == "news.google.com":
                real = decode_google_news_url(s.url)
                if real:
                    s.meta["google_news_url"] = s.url
                    s.url = url = real          # 출처 표기도 원래 기사 주소로
            if NAVER_ARTICLE.match(url):
                try:
                    art = parse_naver_article(HTTP.get(url, timeout=TIMEOUT).text, url)
                except requests.RequestException:
                    art = None
                body = art.text if art else ""
            else:
                body = fetch_text(url) if "news.google.com" not in url else ""
            if len(body) > len(s.text):
                s.text = body
    thin = [s for s in unique if s.kind == "news" and len(s.text) < 200]
    if thin and len(unique) - len(thin) >= 4:
        # 제목뿐인 기사는 사실 확인에 쓸 수 없고 AI 시간만 늘려서 뺀다
        unique = [s for s in unique if s not in thin]
        progress(f"  · 제목만 있는 기사 {len(thin)}건은 뺐어요")
    for i, s in enumerate(unique, 1):
        s.id = f"S{i}"
        if not s.published:
            s.published = ""
    progress(f"  → 자료 {len(unique)}건 확보 ({datetime.now():%H:%M})")
    return unique
