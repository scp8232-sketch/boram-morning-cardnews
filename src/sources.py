"""뉴스/날씨/시세 수집: 검증된 기준일만 사용하고 수치의 근거는 메타데이터로 보존."""
from __future__ import annotations
from datetime import datetime, date, timedelta
from email.utils import parsedate_to_datetime
import html
import os
import re
from urllib.parse import quote
from zoneinfo import ZoneInfo
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

KST = ZoneInfo('Asia/Seoul')
TIMEOUT = 18
UA = {'User-Agent': 'Mozilla/5.0 (compatible; BoramMorningCards/2.0; editorial preview)'}

NEWS_QUERIES = {
    '정치': '국회 정부 정책 한국 when:3d',
    '경제': '한국 경제 기업 산업 금융 when:3d',
    '사회': '한국 사회 안전 교육 제도 when:3d',
    '국제': '국제 외교 세계 주요 뉴스 when:3d',
    '생활/문화': '문화 생활 공연 축제 한국 when:7d',
}
MEDICAL_QUERIES = {
    '건강보험': '건강보험 급여 국민건강보험 제도 변경 when:14d',
    '보험제도': '민영보험 제도 금융감독원 보험연구원 when:14d',
    '보건정책': '보건복지부 의료 정책 의사 환자 when:14d',
    '의료기술': '신약 허가 임상 의료기기 식약처 when:14d',
    '건강정보': '질병관리청 감염병 예방 발표 when:14d',
}
BANNED_NEWS_TITLES = (
    '민원인안내서', '민원인 안내서', '주요통계(기간별)', '주요통계 (기간별)',
    '메인페이지', '홈페이지 바로가기', 'HOME >', '고객센터', '공공데이터포털',
    '관련사이트', '이용약관', '보도자료 목록',
)


def today_kst() -> date:
    return datetime.now(KST).date()


def recent(iso_day: str, age: int = 4, *, reference: date | None = None) -> bool:
    try:
        d = date.fromisoformat(iso_day)
    except (ValueError, TypeError):
        return False
    now = reference or today_kst()
    return timedelta(days=0) <= now - d <= timedelta(days=age)


def news_search(query: str, limit: int = 7) -> list[dict]:
    url = f'https://news.google.com/rss/search?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko'
    try:
        response = requests.get(url, headers=UA, timeout=TIMEOUT)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except (requests.RequestException, ValueError, ET.ParseError):
        return []
    items = []
    for e in root.findall('./channel/item')[:max(limit * 5, 25)]:
        title = html.unescape(re.sub(r'<[^>]+>', '', e.findtext('title', ''))).strip()
        source = (e.findtext('source') or 'Google 뉴스 RSS').strip()
        if title.endswith(' - ' + source):
            title = title[:-(len(source) + 3)].rstrip()
        link = (e.findtext('link') or '').strip()
        if not title or not link or any(t.lower() in title.lower() for t in BANNED_NEWS_TITLES):
            continue
        try:
            dt = parsedate_to_datetime(e.findtext('pubDate', '')).astimezone(KST)
            day = dt.strftime('%Y-%m-%d')
        except (ValueError, TypeError, AttributeError):
            continue
        snippet = html.unescape(re.sub(r'<[^>]+>', ' ', e.findtext('description', '')))
        snippet = re.sub(r'\s+', ' ', snippet).strip()[:550]
        items.append({'title': title, 'date': day, 'source': source, 'url': link, 'snippet': snippet})
        if len(items) >= limit:
            break
    return items


def choose_articles(queries: dict, per_category: int = 1) -> list[dict]:
    result = []
    seen = set()
    for category, query in queries.items():
        age = 10 if category in MEDICAL_QUERIES else (7 if category == '생활/문화' else 4)
        for entry in news_search(query, 9):
            if not recent(entry['date'], age):
                continue
            key = re.sub(r'\W+', '', entry['title'])[:35]
            if len(key) < 12 or key in seen:
                continue
            seen.add(key)
            result.append({'category': category, **entry})
            break
    return result


CITIES = {
    '서울': (37.5665, 126.9780), '대전': (36.3504, 127.3845),
    '광주': (35.1595, 126.8526), '대구': (35.8714, 128.6014),
    '부산': (35.1796, 129.0756),
}


def condition_from_code(code: int | None) -> str:
    if code is None:
        return '기상 미확인'
    if code in (0, 1):
        return '맑음'
    if code == 2:
        return '구름 조금'
    if code == 3:
        return '흐림'
    if code in (45, 48):
        return '안개'
    if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99):
        return '비'
    if code in (71, 73, 75, 77, 85, 86):
        return '눈'
    return '구름 많음'


def weather_sentence(cities: dict) -> str:
    valid = {name: obj for name, obj in cities.items() if obj}
    if not valid:
        return '주요 도시의 날씨 예보를 확인하지 못했습니다.'
    groups: dict[str, list[str]] = {}
    for city, data in valid.items():
        groups.setdefault(data['condition'], []).append(city)
    parts = []
    for condition, members in sorted(groups.items(), key=lambda t: -len(t[1]))[:2]:
        members_txt = '·'.join(members[:3]) + (' 등' if len(members) > 3 else '')
        ending = '예상됩니다' if condition in ('비', '눈', '안개') else '전망입니다'
        parts.append(f'{members_txt}은 {condition}이 {ending}')
    lo = min(int(v['lo']) for v in valid.values())
    hi = max(int(v['hi']) for v in valid.values())
    return f"주요 도시 전망은 {'; '.join(parts)}. 아침 최저는 {lo}℃ 안팎, 낮 최고는 {hi}℃까지 오르겠습니다."


def weather_today() -> dict:
    out = {'source': 'Open-Meteo 참고 예보', 'source_url': 'https://open-meteo.com/',
           'date': today_kst().isoformat(), 'checked': datetime.now(KST).strftime('%H:%M KST'),
           'cities': {}}
    for name, (lat, lng) in CITIES.items():
        try:
            r = requests.get('https://api.open-meteo.com/v1/forecast', params={
                'latitude': lat, 'longitude': lng,
                'daily': 'temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code',
                'timezone': 'Asia/Seoul', 'forecast_days': 1,
            }, headers=UA, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()['daily']
            code = int(data['weather_code'][0])
            out['cities'][name] = {
                'lo': round(data['temperature_2m_min'][0]), 'hi': round(data['temperature_2m_max'][0]),
                'rain': data['precipitation_probability_max'][0], 'condition': condition_from_code(code),
            }
        except (requests.RequestException, KeyError, ValueError, IndexError, TypeError):
            out['cities'][name] = None
    out['narrative'] = weather_sentence(out['cities'])
    return out


def yahoo_last_two(symbol: str) -> dict | None:
    try:
        r = requests.get('https://query1.finance.yahoo.com/v8/finance/chart/' + quote(symbol, safe=''),
            params={'interval': '1d', 'range': '10d'}, headers={**UA, 'User-Agent': 'Mozilla/5.0'}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()['chart']['result'][0]
        quotes = data['indicators']['quote'][0]['close']
        vals = [(t, v) for t, v in zip(data['timestamp'], quotes) if v is not None]
        if len(vals) < 2:
            return None
        (t_prev, prev), (t_last, last) = vals[-2:]
        day = datetime.fromtimestamp(t_last, KST).strftime('%Y-%m-%d')
        if not recent(day, age=7):
            return None
        return {'value': float(last), 'change': float((last / prev - 1) * 100) if prev else 0.,
                'date': day, 'source': 'Yahoo Finance 참고시세',
                'source_url': 'https://finance.yahoo.com/quote/' + quote(symbol, safe='')}
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError, ZeroDivisionError):
        return None


def opinet_api_prices(api_key: str) -> dict:
    """오피넷 무료 일반 API (별도 무료 키 필요)."""
    r = requests.get('https://www.opinet.co.kr/api/avgAllPrice.do', params={
        'out': 'json', 'certkey': api_key}, timeout=TIMEOUT, headers=UA)
    r.raise_for_status()
    root = r.json()
    objs = root.get('RESULT', {}).get('OIL', [])
    if isinstance(objs, dict):
        objs = [objs]
    out = {}
    for entry in objs:
        key = {'B027': '휘발유', 'D047': '경유'}.get(str(entry.get('PRODCD', '')).strip())
        if not key:
            continue
        day = str(entry['TRADE_DT']).replace('-', '')
        day = f'{day[:4]}-{day[4:6]}-{day[6:8]}'
        price = float(str(entry['PRICE']).replace(',', ''))
        if recent(day, age=4) and 300 < price < 4000:
            out[key] = {'value': price, 'date': day, 'unit': '원/L', 'source': '오피넷 전국 평균',
                        'source_url': 'https://www.opinet.co.kr/user/dopospdrg/dopOsPdrgSelect.do'}
    return out


def opinet_public_prices() -> dict:
    """공개 평균판매가격 표의 최근 날짜 행. 사이트 구조가 바뀌면 None 처리."""
    r = requests.get('https://www.opinet.co.kr/user/dopospdrg/dopOsPdrgSelect.do', timeout=TIMEOUT, headers=UA)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, 'html.parser')
    rows = []
    for tr in soup.select('tr'):
        tds = [td.get_text(' ', strip=True) for td in tr.select('td')]
        if len(tds) < 4:
            continue
        date_match = re.search(r'(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일', tds[0])
        if not date_match:
            continue
        day = f'{int(date_match[1]):04d}-{int(date_match[2]):02d}-{int(date_match[3]):02d}'
        try:
            petrol, diesel = float(tds[2].replace(',', '')), float(tds[3].replace(',', ''))
        except (ValueError, IndexError):
            continue
        if recent(day, age=4) and 300 < petrol < 4000 and 300 < diesel < 4000:
            rows.append((day, petrol, diesel))
    if not rows:
        text = soup.get_text(' ', strip=True)
        pattern = r'(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)'
        for m in re.finditer(pattern, text):
            day = f'{int(m[1]):04d}-{int(m[2]):02d}-{int(m[3]):02d}'
            petrol, diesel = float(m[5].replace(',', '')), float(m[6].replace(',', ''))
            if recent(day, age=4) and 300 < petrol < 4000 and 300 < diesel < 4000:
                rows.append((day, petrol, diesel))
    if not rows:
        return {}
    day, petrol, diesel = max(rows)
    common = {'date': day, 'unit': '원/L', 'source': '오피넷 전국 평균',
              'source_url': 'https://www.opinet.co.kr/user/dopospdrg/dopOsPdrgSelect.do'}
    return {'휘발유': {**common, 'value': petrol}, '경유': {**common, 'value': diesel}}


def fuel_prices() -> dict:
    out = {}
    key = os.environ.get('OPINET_API_KEY', '').strip()
    if key:
        try:
            out.update(opinet_api_prices(key))
        except (requests.RequestException, ValueError, KeyError, TypeError):
            print('오피넷 API 조회 실패; 공개 페이지를 확인합니다.')
    if len(out) < 2:
        try:
            out.update({k: v for k, v in opinet_public_prices().items() if k not in out})
        except (requests.RequestException, ValueError, IndexError):
            print('오피넷 공개 페이지 조회 실패; 미확인 값을 표시하지 않습니다.')
    return out


def gold_prices() -> dict | None:
    """국내 금 현물 시세(소비자 살/팔 때), 날짜와 가격이 확인되는 기록에서만 조회."""
    year_month = today_kst().strftime('%Y-%m')
    url = f'https://goldpricekorea.com/history/pure/{year_month}'
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=UA)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        results = []
        for tr in soup.select('tr'):
            cells = [td.get_text(' ', strip=True) for td in tr.select('td')]
            if len(cells) < 3:
                continue
            dm = re.search(r'(?<!\d)(\d{1,2})\s*[.\-/]\s*(\d{1,2})(?!\d)', cells[0])
            if not dm:
                continue
            day = f'{today_kst().year}-{int(dm[1]):02d}-{int(dm[2]):02d}'
            if not recent(day, age=4):
                continue
            try:
                buy = int(re.search(r'([\d,]{5,})', cells[1]).group(1).replace(',', ''))
                sell = int(re.search(r'([\d,]{5,})', cells[2]).group(1).replace(',', ''))
            except (AttributeError, IndexError, ValueError):
                continue
            if 200_000 <= sell <= buy <= 2_000_000:
                results.append((day, buy, sell))
        if results:
            day, buy, sell = max(results)
            return {'buy': buy, 'sell': sell, 'date': day, 'unit': '원/1돈(3.75g)',
                    'source': '금 시세 코리아 고시 집계', 'source_url': url, 'vat': '살 때 부가세 포함 기준'}
    except requests.RequestException:
        pass
    # 공개 표가 없으면 실시간 시세 페이지의 기준일·소비자 가격을 읽는다.
    try:
        fallback_url = 'https://goldpricekorea.com/'
        response = requests.get(fallback_url, timeout=TIMEOUT, headers=UA)
        response.raise_for_status()
        text = BeautifulSoup(response.text, 'html.parser').get_text(' ', strip=True)
        dm = re.search(r'(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})', text)
        bm = re.search(r'순금\s*1돈\s*살\s*때\s*([\d,]+)\s*원', text)
        sm = re.search(r'내가\s*팔\s*때\s*([\d,]+)\s*원', text)
        if dm and bm and sm:
            day = f'{int(dm[1]):04d}-{int(dm[2]):02d}-{int(dm[3]):02d}'
            buy, sell = int(bm[1].replace(',', '')), int(sm[1].replace(',', ''))
            if recent(day, age=4) and 200_000 <= sell <= buy <= 2_000_000:
                return {'buy': buy, 'sell': sell, 'date': day, 'unit': '원/1돈(3.75g)',
                        'source': '금 시세 코리아 고시 집계', 'source_url': fallback_url,
                        'vat': '살 때 부가세 포함 기준'}
    except requests.RequestException:
        pass
    return None


def market_data() -> dict:
    market = {
        'KOSPI': yahoo_last_two('^KS11'),
        'KOSDAQ': yahoo_last_two('^KQ11'),
        'USD/KRW': yahoo_last_two('KRW=X'),
        '휘발유': None, '경유': None, '순금 24K 1돈(살 때/팔 때)': None,
    }
    fuels = fuel_prices()
    market.update(fuels)
    market['순금 24K 1돈(살 때/팔 때)'] = gold_prices()
    return market
