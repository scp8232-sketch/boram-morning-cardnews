"""공개 뉴스 RSS, 참고 시세, 날씨를 수집한다. 실패하면 수치를 절대 추정하지 않는다."""
from __future__ import annotations
import calendar
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import html
import re
from urllib.parse import quote
from zoneinfo import ZoneInfo

from xml.etree import ElementTree as ET
import requests

KST = ZoneInfo("Asia/Seoul")
UA = {"User-Agent": "BoramMorningCards/1.0 (personal daily briefing)"}
TIMEOUT = 18

NEWS_QUERIES = {
    "정치": "국회 정부 정책 한국 when:3d",
    "경제": "한국 경제 기업 산업 금융 when:3d",
    "사회": "한국 사회 안전 교육 제도 when:3d",
    "국제": "국제 외교 세계 주요 뉴스 when:3d",
    "생활/문화": "문화 생활 공연 축제 한국 when:7d",
}
MEDICAL_QUERIES = {
    "건강보험": "site:nhis.or.kr OR site:mohw.go.kr 건강보험 급여 when:14d",
    "보험제도": "보험 제도 보장 금융감독원 보험연구원 when:14d",
    "보건정책": "site:mohw.go.kr OR site:kdca.go.kr 보건 의료 정책 when:14d",
    "의료기술": "site:mfds.go.kr 의료기기 신약 허가 when:14d",
    "건강정보": "site:kdca.go.kr 질병 예방 감염병 when:14d",
}


def news_search(query: str, limit: int = 5) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except (requests.RequestException, ValueError, ET.ParseError):
        return []
    items = []
    for e in root.findall('./channel/item')[: max(limit * 4, 15)]:
        title = html.unescape(re.sub(r"<[^>]+>", "", e.findtext('title', ''))).strip()
        link = (e.findtext('link') or '').strip()
        if not title or not link:
            continue
        try:
            dt = parsedate_to_datetime(e.findtext('pubDate', ''))
            ds = dt.astimezone(KST).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            ds = "발행일 미확인"
        source = e.findtext('source') or 'Google 뉴스 RSS'
        if ' - ' in title and source == 'Google 뉴스 RSS':
            title, source = title.rsplit(' - ', 1)
        snippet = html.unescape(re.sub(r"<[^>]+>", " ", e.findtext('description', '')))
        snippet = re.sub(r"\s+", " ", snippet).strip()[:350]
        items.append({"title": title, "date": ds, "source": source, "url": link, "snippet": snippet})
        if len(items) >= limit:
            break
    return items


def choose_articles(queries: dict, per_category: int = 1) -> list[dict]:
    chosen = []
    seen = set()
    for category, query in queries.items():
        candidates = news_search(query, 6)
        for entry in candidates:
            tag = re.sub(r"\W+", "", entry["title"])[:20]
            if tag in seen:
                continue
            chosen.append({"category": category, **entry})
            seen.add(tag)
            break
    return chosen


CITIES = {
    "서울": (37.5665, 126.9780),
    "대전": (36.3504, 127.3845),
    "광주": (35.1595, 126.8526),
    "대구": (35.8714, 128.6014),
    "부산": (35.1796, 129.0756),
}


def weather_today() -> dict:
    result = {"source": "Open-Meteo (기상청 자료 아님)", "cities": {}, "checked": datetime.now(KST).strftime("%H:%M KST")}
    for name, (lat, lng) in CITIES.items():
        try:
            r = requests.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": lat, "longitude": lng, "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "Asia/Seoul", "forecast_days": 1,
            }, timeout=TIMEOUT, headers=UA)
            r.raise_for_status()
            d = r.json()["daily"]
            result["cities"][name] = {"lo": round(d["temperature_2m_min"][0]), "hi": round(d["temperature_2m_max"][0]),
                                      "rain": d["precipitation_probability_max"][0]}
        except (requests.RequestException, KeyError, ValueError, IndexError, TypeError):
            result["cities"][name] = None
    return result


def yahoo_last_two(symbol: str) -> dict | None:
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/" + quote(symbol, safe=""),
                         params={"interval": "1d", "range": "10d"}, headers={**UA, "User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT)
        r.raise_for_status()
        result = r.json()["chart"]["result"][0]
        quotes = result["indicators"]["quote"][0]["close"]
        times = result["timestamp"]
        vals = [(t, v) for t, v in zip(times, quotes) if v is not None]
        if len(vals) < 2:
            return None
        (p_time, prev), (t_time, last) = vals[-2:]
        dt = datetime.fromtimestamp(t_time, tz=KST).strftime("%m/%d")
        return {"value": float(last), "change": (last / prev - 1) * 100 if prev else 0,
                "date": dt, "source": "Yahoo Finance 참고시세"}
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError, ZeroDivisionError):
        return None


def market_data() -> dict:
    return {
        "KOSPI": yahoo_last_two("^KS11"),
        "KOSDAQ": yahoo_last_two("^KQ11"),
        "USD/KRW": yahoo_last_two("KRW=X"),
        "휘발유": None,  # 오피넷 공식 인증키 연동 전에는 추정 금지
        "경유": None,
        "순금 24K 1돈(살 때/팔 때)": None,
    }
