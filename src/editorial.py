"""근거가 있는 기사를 선별하고 내용 없는 요약을 발행 전에 차단한다.

원칙: 기사 제목/RSS 한 줄만으로 본문을 만들지 않는다. 원문을 읽지 못하면 기사를 버린다.
비밀키 및 원문 전문은 공개 docs/ 폴더에 저장하지 않는다.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta, time as dt_time
from email.utils import parsedate_to_datetime
from html import unescape
import hashlib
import json
import os
import re
import time
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

KST = ZoneInfo('Asia/Seoul')
TIMEOUT = 15
HEADERS = {'User-Agent':'Mozilla/5.0 (compatible; BoramMorningEditorial/3.0)', 'Accept-Language':'ko-KR,ko;q=0.9,en;q=0.5'}

GENERAL_CATEGORIES = ('정치','경제','사회','국제','생활/문화')
MEDICAL_CATEGORIES = ('건강보험','보험제도','보건정책','의료기술','건강정보')

# RSS 피드 링크는 매체가 공개한 경로만 사용. 피드 실패 시 Google 뉴스 RSS로 보완.
FEEDS = {
 '정치': ['https://www.newsis.com/RSS/politics.xml','https://www.yna.co.kr/rss/politics.xml','https://www.khan.co.kr/rss/rssdata/politic_news.xml'],
 '경제': ['https://www.newsis.com/RSS/economy.xml','https://www.yna.co.kr/rss/economy.xml'],
 '사회': ['https://www.mois.go.kr/gpms/view/jsp/rss/rss.jsp?ctxCd=1012','https://www.newsis.com/RSS/society.xml','https://www.yna.co.kr/rss/news.xml'],
 '국제': ['https://www.newsis.com/RSS/international.xml','https://www.yna.co.kr/rss/international.xml'],
 '생활/문화': ['https://www.newsis.com/RSS/culture.xml','https://www.yna.co.kr/rss/culture.xml','https://www.khan.co.kr/rss/rssdata/culture_news.xml',
               'https://www.newsis.com/RSS/society.xml','https://www.newsis.com/RSS/economy.xml'],
 '건강보험': ['https://www.newsis.com/RSS/society.xml','https://www.yna.co.kr/rss/news.xml','https://www.newsis.com/RSS/bank.xml','https://www.newsis.com/RSS/health.xml'],
 '보험제도': ['https://www.newsis.com/RSS/bank.xml','https://www.newsis.com/RSS/economy.xml','https://www.yna.co.kr/rss/economy.xml','https://www.newsis.com/RSS/society.xml'],
 '보건정책': ['https://www.newsis.com/RSS/health.xml','https://www.yna.co.kr/rss/health.xml'],
 '의료기술': ['https://www.newsis.com/RSS/health.xml','https://www.yna.co.kr/rss/health.xml'],
 '건강정보': ['https://www.yna.co.kr/rss/health.xml','https://www.newsis.com/RSS/health.xml'],
}
CATEGORY_TERMS = {
 '건강보험':('건강보험','보험급여','수가','심평원','건보','국민건강보험','본인부담금','의료급여','보험료 환급'),
 '보험제도':('보험','실손','보험금','피보험자','보험약관','GA','손해보험','생명보험'),
 '보건정책':('보건','복지부','의료기관','공공의료','병원','진료','지역의료'),
 '의료기술':('신약','임상','의료기기','바이오','치료제','의약품','진단','식약처','연구'),
 '건강정보':('감염병','건강','질병','예방','독감','백신','감염','질환'),
}
NEWS_QUERIES = {
 '정치':'국회 대통령 정부정책 site:president.go.kr OR site:yna.co.kr when:3d',
 '경제':'금융위원회 경제 산업 기업 시장 when:3d',
 '사회':'사회 교육 안전 재난 제도 when:3d',
 '국제':'국제 정상회의 외교 무역 주요국 when:3d',
 '생활/문화':'생활 소비자 피해 교통 주거 교육 지원 환급 건강 안전 문화 when:5d',
 '건강보험':'건보공단 건강보험 환급금 본인부담금 보험급여 when:21d',
 '보험제도':'금융위원회 실손보험 보험금 청구 보험제도 when:21d',
 '보건정책':'보건복지부 의료정책 의료시설 when:7d',
 '의료기술':'신약 임상 식약처 의료기기 when:10d',
 '건강정보':'질병관리청 감염병 예방 질병 when:7d',
}

# 키워드만 있는 목록 페이지, 제목 복사, 의견 기사, 검색 결과를 실뉴스로 오인하는 것을 방지.
BAD_TITLES = ('민원인안내서', '주요통계(기간별)', '홈페이지', '메인페이지', '바로가기',
              '보도자료 목록', '이용약관', '기사 목록', '사진자료실', 'RSS 서비스', '[사설]',
              '[칼럼]', '[기고]', '독자투고', '광고', '오피니언', '초대합니다')
# 편집 원칙: 일반 독자의 생활과 실제 변화 중심. 점수는 자료를 조작하지 않고
# 신뢰 가능한 원문 후보의 순서만 조절한다. 사진기사·의례적 인사는 후순위.
PHOTO_MARKERS = ('[뉴시스pic]', '[포토]', '[사진]', '[현장포토]', '[포토뉴스]', '[영상]', '[화보]')
LOW_INFORMATION = ('기념촬영', '악수', '포즈를 취', '인사를 나눴', '언론공개회')
ECON_KOREA = ('코스피', '코스닥', '한국은행', '금통위', '원/달러', '원달러', '국내 증시',
              '국내 주식', '한국 증시', '가계대출', '대출금리', '기준금리', '물가',
              '소비자물가', '주택가격', '전세', '한국 경제', '국내 경제', '고용')
ECON_US = ('미국 증시', '뉴욕 증시', '뉴욕증시', '나스닥', 's&p', '연준', 'fomc',
           '미국 금리', '미국 물가', '다우지수', '엔비디아', '미 반도체')
ECON_OTHER_MARKETS = ('대만 증시', '대만 주식', '타이베이 증시', '자취안',
                      '일본 증시', '닛케이', '중국 증시', '상하이 증시', '유럽 증시')
LIFE_USEFUL = ('교통', '지하철', '버스', '요금', '환급', '지원금', '소비자', '피해',
               '주거', '전세', '월세', '주택', '교육', '학교', '안전', '화재',
               '식품', '식중독', '예방접종', '신청', '생활비', '난방비', '통신비')
LIFE_EVENTS = ('전시', '공연', '축제', '미술관', '음악회', '언론공개회', '개막', '포럼', '세미나', '심포지엄')
TOPIC_STOPWORDS = {'오늘','어제','내일','정부','한국','국내','사회','경제','정치','국제',
                   '관련','분야','소식','종합','속보','논란','발표','추진','문제',
                   '기자','뉴시스','연합뉴스','공개','확인','완료','새로운','내용',
                   '대해','위해','가운데','이날','오는','대한','있다','했다'}


def headline_topic_terms(title: str) -> list[str]:
    """원문 제목의 식별 가능한 주요 단어. 비교만 하며 사실을 생성하지 않는다."""
    terms=re.findall(r'[가-힣A-Za-z0-9]{2,}', compact(title).lower())
    return [t for t in terms if t not in TOPIC_STOPWORDS and len(t)>=2]


def topic_matches_title(source_title: str, written: str) -> bool:
    """다른 기사의 문단이 끼어들었는지 탐지하는 보수적 안전장치."""
    terms=[t for t in headline_topic_terms(source_title) if len(t)>=3]
    if len(terms)<2:
        return True   # 정보가 적은 제목은 이 규칙만으로 오류라고 확정하지 않음
    target=normalize(written)
    # 한국어 조사나 활용을 고려해 정규화된 부분 일치를 사용한다.
    return any(normalize(t) in target for t in terms)


def editorial_priority(a: dict) -> float:
    """생활밀착도·중요도 우선 순위(기사 합격/불합격 기준과 분리)."""
    title=compact(a.get('title','')).lower()
    category=a.get('category','')
    value=0.0
    if any(x in title for x in PHOTO_MARKERS): value-=100
    if any(x in title for x in LOW_INFORMATION): value-=22
    if category=='경제':
        if any(x in title for x in ECON_KOREA): value+=70
        elif any(x in title for x in ECON_US): value+=46
        elif any(x in title for x in ECON_OTHER_MARKETS): value-=35
        else: value+=9
    elif category=='생활/문화':
        if any(x in title for x in LIFE_USEFUL): value+=60
        if any(x in title for x in LIFE_EVENTS): value-=55
    elif category=='정치':
        if any(x in title for x in ('합의','의결','통과','시행','국회','법안','안보','협력','대책','후속')):
            value+=19
    elif category=='사회':
        if any(x in title for x in ('안전','범죄','학교','교육','교통','사고','복지','대응','피해')):
            value+=16
    elif category=='국제':
        if any(x in title for x in ('전쟁','휴전','협상','제재','외교','무역','안보','국제유가')):
            value+=14
    return value


BANNED_FILLER = ('주요 정책의 추진', '향후 논의 방향', '관련 논의가 이어',
    '정부 발표 이후', '공식 발표를 통해 구분', '시행 여부는 공식', '세부 일정과 시행 여부',
    '주요 현안 관련', '대내외 불확실성이 남아', '신중한 판단이 필요',
    '다양한 행사와 프로그램', '정책 적용 대상과 예산', '상황에 따라 달라질 수',
    '추가 발표를 통해 확인', '향후 추이를 지켜', '관련 사항을 살펴볼 필요',
    '정독할 원문을 확인', '확인하는 것이 중요', '다양한 논의가', '구체적인 내용은 추후',
    '전문가들은 관심을', '관련 논의가 진행', '새로운 소식에 주목')

class PublicationQualityError(RuntimeError):
    """검증 불충분 — 고객 발송까지 진행하지 않는다."""


class GeminiApiRequestError(RuntimeError):
    """Sanitized API failure: excludes credentials and complete request/response."""
    def __init__(self, status: int, code: str, *, retryable: bool = False):
        self.status, self.code, self.retryable = status, code, retryable
        super().__init__(f'Gemini API HTTP {status} ({code})' if status else f'Gemini API {code}')


def _api_error_details(response):
    status = int(getattr(response, 'status_code', 0) or 0)
    code = 'UNKNOWN'
    try:
        obj = response.json().get('error', {})
        if isinstance(obj, dict):
            code = str(obj.get('status') or obj.get('code') or code)
    except (ValueError, AttributeError, TypeError):
        pass
    code = re.sub(r'[^A-Za-z0-9_\-]', '', code)[:48] or 'UNKNOWN'
    return status, code


def compact(s: str) -> str:
    return re.sub(r'\s+', ' ', unescape(re.sub('<[^>]*>', ' ', str(s or '')))).strip()


def normalize(s: str) -> str:
    return re.sub(r'[^0-9A-Za-z가-힣]+', '', s or '').lower()


def is_recent(day: str, *, max_days: int = 5, now: date | None = None) -> bool:
    try: when = date.fromisoformat(day)
    except (TypeError, ValueError): return False
    today = now or datetime.now(KST).date()
    return timedelta() <= today - when <= timedelta(days=max_days)


def valid_link(url: str) -> bool:
    """RSS에서 가져온 악성 로컬 URL로 접근하지 않게 제한."""
    try:
        u = urlsplit(url)
        host = (u.hostname or '').lower()
        return (u.scheme == 'https' and host and not host.endswith('.local')
                and host not in ('localhost','127.0.0.1','0.0.0.0')
                and not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', host)
                and not host.startswith('169.254.') and not host.startswith('10.')
                and not host.startswith('192.168.'))
    except (ValueError, TypeError): return False


def parse_feed(xml_bytes: bytes, *, limit: int = 55) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    result=[]
    # RSS 및 Atom 둘 다 사용 가능
    items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
    for item in items[:limit]:
        def field(*names):
            for name in names:
                val=item.findtext(name)
                if val: return val
            return ''
        title=compact(field('title', '{http://www.w3.org/2005/Atom}title'))
        url=field('link')
        if not url:
            el=item.find('{http://www.w3.org/2005/Atom}link')
            url=el.get('href','') if el is not None else ''
        url=compact(url)
        if not title or not valid_link(url) or any(s.lower() in title.lower() for s in BAD_TITLES):
            continue
        raw_date=field('pubDate','{http://www.w3.org/2005/Atom}published','{http://www.w3.org/2005/Atom}updated')
        dt=None
        try:
            dt=parsedate_to_datetime(raw_date)
            if dt.tzinfo is None: dt=dt.replace(tzinfo=KST)
            day=dt.astimezone(KST).date().isoformat()
        except (TypeError,ValueError,IndexError,AttributeError):
            try:
                dt=datetime.fromisoformat(raw_date.replace('Z','+00:00'))
                if dt.tzinfo is None: dt=dt.replace(tzinfo=KST)
                day=dt.astimezone(KST).date().isoformat()
            except (TypeError,ValueError,AttributeError):
                dt=None
                try: day=date.fromisoformat(raw_date[:10]).isoformat()
                except (TypeError,ValueError): continue
        published_at = dt.astimezone(KST).isoformat() if isinstance(dt,datetime) else ''
        desc=compact(field('description','{http://www.w3.org/2005/Atom}summary',
                '{http://purl.org/rss/1.0/modules/content/}encoded'))
        source=compact(field('source')) or (urlsplit(url).hostname or '').replace('www.','')
        if title.endswith(' - '+source): title=title[:-(len(source)+3)]
        result.append({'title':title,'url':url,'date':day,'source':source,'snippet':desc[:700],'published_at':published_at})
    return result


def feed_articles(url: str) -> list[dict]:
    try:
        res=requests.get(url,headers=HEADERS,timeout=TIMEOUT)
        res.raise_for_status()
        return parse_feed(res.content)
    except (requests.RequestException,ET.ParseError,ValueError):
        return []


def fetch_fulltext(url: str) -> str:
    """원문 전체는 메모리에서만 사용하고 공개 결과물에 포함하지 않음."""
    if not valid_link(url): return ''
    try:
        r=requests.get(url,headers=HEADERS,timeout=TIMEOUT)
        r.raise_for_status()
        if not valid_link(r.url): return ''
        if (urlsplit(r.url).hostname or '').lower().endswith('news.google.com'): return ''
        if 'text/html' not in r.headers.get('Content-Type','text/html'): return ''
    except requests.RequestException:
        return ''
    soup=BeautifulSoup(r.text,'html.parser')
    ld_json = [node.string or node.get_text() for node in soup.find_all('script', attrs={'type': 'application/ld+json'})]
    for tag in soup.select('script, style, nav, footer, header, aside, iframe, form, noscript, .ad, .advertisement, .copyright'):
        tag.decompose()
    # 기사 본문 전용 요소 우선, 뉴스/정부 사이트에 흔한 선택자 포함
    selectors=['#articleBodyContents','#articleBody','#article_body','.article_body',
        '.article-view-content','.article_view','.news_view','.newsview', '.article_txt',
        '.news-contents','.viewCont','.view_content','.articleContent',
        '#newsEndContents','#dic_area','#newsct_article','#article',
        '[itemprop="articleBody"]','.article-contents','.article-body',
        '.news_body','article','main']
    candidates=[]
    for css in selectors:
        for node in soup.select(css)[:3]:
            pars=[compact(x.get_text(' ',strip=True)) for x in node.select('p, li')]
            pars=[p for p in pars if len(normalize(p))>=35]
            text=' '.join(pars) if pars else compact(node.get_text(' ',strip=True))
            if len(normalize(text))>=260: candidates.append(text)
        if candidates: break
    if not candidates:
        pars=[compact(x.get_text(' ',strip=True)) for x in soup.select('p')]
        pars=[p for p in pars if len(normalize(p))>=45]
        if len(pars)>=3: candidates.append(' '.join(pars[:25]))
    if not candidates:
        # Some publishers expose the article text via schema.org JSON-LD,
        # not paragraphs. This is still the actual published articleBody.
        for raw_ld in ld_json:
            try:
                data = json.loads(raw_ld or '{}')
            except (ValueError, TypeError):
                continue
            queue = [data]
            for _ in range(24):
                if not queue:
                    break
                entry = queue.pop(0)
                if isinstance(entry, list):
                    queue.extend(entry[:20])
                elif isinstance(entry, dict):
                    body = entry.get('articleBody')
                    if isinstance(body, str) and len(normalize(body)) >= 260:
                        candidates.append(compact(body))
                        break
                    queue.extend(v for k,v in entry.items() if k in ('@graph', 'mainEntity', 'itemListElement'))
            if candidates:
                break
    if not candidates: return ''
    # 많은 페이지에 긴 쿠키/사이드 메뉴가 있으므로 5200자로 제한
    text=max(candidates,key=lambda x:len(x))[:5200]
    if len(normalize(text))<260:return ''
    if len(normalize(text))<380:
        meta=soup.find('meta',attrs={'name':'description'}) or soup.find('meta',attrs={'property':'og:description'})
        if meta:
            m=compact(meta.get('content',''))
            if len(m)>=45 and normalize(m) not in normalize(text): text=m+' '+text
    return compact(text)[:5200]



def evidence_catalog(fulltext: str, *, max_passages: int = 32) -> dict[str, str]:
    """Build immutable, source-anchored evidence passages *before* asking AI.

    The model is asked to choose passage IDs, not to copy quotations exactly.
    IDs are regenerated from the source body at validation time, so fabricated
    references and paraphrased evidence cannot pass.
    """
    text = compact(fulltext)
    if not text:
        return {}
    sentences = re.split(r'(?<=[.!?。])\s+', text)
    pieces = []
    for sentence in sentences:
        sentence = sentence.strip()
        if len(normalize(sentence)) < 22:
            continue
        # Preserve complete, long Korean news sentences for grounded AI repairs.
        # Splitting a 250-500 character factual sentence at an arbitrary space
        # produces fragments that cannot pass the complete-sentence fallback.
        # Only exceptionally long passages need splitting, and split pieces
        # remain literal substrings of the original article.
        while len(sentence) > 500:
            i = sentence.rfind(' ', 240, 450)
            if i < 240: i = 420
            segment = sentence[:i].strip()
            if len(normalize(segment)) >= 22:
                pieces.append(segment)
            sentence = sentence[i:].strip()
        if len(normalize(sentence)) >= 22:
            pieces.append(sentence)
    if len(pieces) < 2:
        # Fail closed for articles with no meaningful fact passages.
        return {}
    unique=[]
    used=set()
    for p in pieces:
        tag=normalize(p)
        if tag in used or len(tag) < 22:
            continue
        used.add(tag)
        unique.append(p)
        if len(unique) >= max_passages:
            break
    return {f'E{i:02d}': passage for i, passage in enumerate(unique,1)}


def _verified_evidence(item: dict, body: str) -> tuple[list[str], str]:
    """Resolve selected evidence IDs against the *actual* downloaded article.

    Backward-compatible exact quote support exists for local regression tests,
    but the live model is instructed to use evidence_ids only.
    """
    ids = item.get('evidence_ids')
    if ids is not None:
        if not isinstance(ids, list) or len(ids) < 2:
            return [], '근거 문장 번호 2개 미제출'
        catalog = evidence_catalog(body)
        if len(catalog) < 2:
            return [], '원문에서 독립 근거 2개를 추출하지 못함'
        if len(set(ids)) < 2:
            return [], '서로 다른 근거 문장 번호 2개가 필요함'
        if not all(isinstance(x,str) and x in catalog for x in ids[:4]):
            return [], '원문에 없는 근거 문장 번호'
        proofs=[]
        for idx in ids[:4]:
            quote=catalog[idx]
            if normalize(quote) not in [normalize(p) for p in proofs]:
                proofs.append(quote)
        return (proofs[:2], '') if len(proofs)>=2 else ([], '독립 근거 문장 2개 미만')
    # Old exact-quote interface: no fuzzy matching, so invented quotes still fail.
    evid=item.get('evidence',[])
    if not isinstance(evid,list) or len(evid)<2:
        return [], '근거문장 2개 미제출'
    normalized=normalize(body)
    proofs=[]
    for e in evid[:4]:
        e=compact(e)
        en=normalize(e)
        if 14 <= len(en) <= 190 and en in normalized and en not in [normalize(p) for p in proofs]:
            proofs.append(e)
    return (proofs[:2], '') if len(proofs)>=2 else ([], '원문과 정확히 일치하는 독립 근거가 2개 미만')


def _compact_long_summary(item: dict) -> dict:
    """Drop only a complete trailing sentence, never chop mid-sentence or add facts.

    Long model outputs are normally retried; this safe fallback is useful when
    the first complete sentence already carries enough information for the card.
    """
    out=dict(item)
    summary=compact(out.get('summary',''))
    if 55 <= len(summary) <= 180:
        out['summary']=summary
        return out
    if len(summary)>180:
        sentences=re.split(r'(?<=[.!?。])\s+',summary)
        for count in range(len(sentences)-1,0,-1):
            fragment=' '.join(sentences[:count]).strip()
            if 70 <= len(fragment) <= 180 and fragment.endswith(('.', '!', '?', '。')):
                out['summary']=fragment
                return out
    out['summary']=summary
    return out

def candidate_score(a: dict, today:date) -> float:
    delta=max(0,(today-date.fromisoformat(a['date'])).days)
    contents=a.get('content','')
    # 새 편집 우선순위 > 단순 분량·숫자 개수. 보도사진은 후순위.
    numeric=min(6,len(re.findall(r'\d',contents)))
    return editorial_priority(a) + 40 - delta*3 + min(15,len(contents)//300) + numeric


def _is_google_news_url(url: str) -> bool:
    try:
        return (urlsplit(url).hostname or '').lower() == 'news.google.com'
    except ValueError:
        return False


def _decode_google_rows(rows: list[dict], *, limit: int = 14) -> list[dict]:
    """Resolve optional Google News RSS wrappers to publisher URLs.

    If Google's undocumented redirect mechanism changes, simply return an
    empty list. A Google landing page is NEVER treated as a publisher article.
    """
    selected = rows[:limit]
    if not selected:
        return []
    try:
        from gnews_decoder import decode_many
    except ImportError:
        print('[원문 수집] Google 뉴스 원문 링크 변환기 미설치 — 직접 언론사 RSS만 사용', flush=True)
        return []
    try:
        mappings = decode_many([r['url'] for r in selected])
    except Exception as exc:
        print('[원문 수집] Google 뉴스 원문 링크 변환 불가: '+type(exc).__name__, flush=True)
        return []
    if not isinstance(mappings, dict):
        return []
    resolved = []
    for entry in selected:
        publisher = mappings.get(entry['url'])
        if (isinstance(publisher, str) and valid_link(publisher)
                and not _is_google_news_url(publisher)):
            resolved.append({**entry, 'url': publisher})
    return resolved


def _fetch_verified_entries(items: list[dict], category: str, seen_urls: set[str],
                            *, trials: int = 22) -> list[dict]:
    """Try independent publisher articles in parallel, never RSS snippets.

    Publisher article extraction is network-bound; running requests
    concurrently prevents 15-second timeout pages from blocking the morning
    job for many minutes. Content is checked exactly as before.
    """
    unique = []
    used = set(seen_urls)
    for entry in items:
        url = entry['url']
        if url in used or _is_google_news_url(url):
            continue
        used.add(url)
        unique.append(entry)
        if len(unique) >= trials:
            break
    if not unique:
        return []
    results = []
    with ThreadPoolExecutor(max_workers=min(6,len(unique))) as executor:
        futures = {executor.submit(fetch_fulltext, entry['url']): entry for entry in unique}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                content = future.result()
            except (ValueError, TypeError, requests.RequestException):
                continue
            if len(normalize(content)) < 260 or len(evidence_catalog(content)) < 2:
                continue
            info = {**entry, 'category': category, 'content':content}
            info['candidate_id'] = hashlib.sha256(entry['url'].encode()).hexdigest()[:12]
            results.append(info)
    return results


def collect_candidates(categories: tuple[str,...], *, today: date | None=None,
                       max_per_category: int=5, as_of: datetime | None=None) -> dict[str,list[dict]]:
    as_of = as_of or (datetime.combine(today, dt_time.max, KST) if today else datetime.now(KST))
    if as_of.tzinfo is None: raise ValueError('as_of must include timezone')
    today = today or as_of.astimezone(KST).date()
    out = {}
    seen_urls: set[str] = set()
    for category in categories:
        rows = []
        for rss in FEEDS[category]:
            rows += feed_articles(rss)
        # Google News provides relevant headline discovery but most RSS URLs
        # are *not* direct publisher URLs; they need explicit decoding.
        from urllib.parse import quote
        rows += feed_articles('https://news.google.com/rss/search?q='+quote(NEWS_QUERIES[category])
                              + '&hl=ko&gl=KR&ceid=KR:ko')
        plausible = []
        used = set()
        for item in rows:
            terms = CATEGORY_TERMS.get(category)
            if terms and not any(term.lower() in item['title'].lower() for term in terms):
                continue
            # Medical insurance changes less often than general daily news.
            # Use a clearly dated recent release, not an invented same-day item.
            max_days = (16 if category in ('건강보험','보험제도')
                        else 10 if category in MEDICAL_CATEGORIES or category=='생활/문화'
                        else 4)
            if not is_recent(item['date'],max_days=max_days,now=today):
                continue
            stamp=item.get('published_at')
            # 당일 발행 자료인데 시각이 누락되면 발송 이후 기사일 수 있다.
            # 운영 중에는 사용하지 않는다(과거 날짜의 오프라인 테스트는 예외).
            if (not stamp and item['date']==today.isoformat()
                    and as_of.astimezone(KST).time()!=dt_time.max):
                continue
            if stamp:
                try:
                    if datetime.fromisoformat(stamp).astimezone(KST)>as_of.astimezone(KST):
                        continue  # 발송 시점 이후 공개된 기사는 사용 금지
                except (TypeError, ValueError):
                    continue
            if item['url'] in seen_urls or item['url'] in used or any(
                s.lower() in item['title'].lower() for s in BAD_TITLES):
                continue
            if len(normalize(item['title'])) < 15:
                continue
            plausible.append(item)
            used.add(item['url'])
        # 제목 기준 1차 순위 뒤에 원문을 수집해 높은 가치의 기사에 검증 예산을 사용한다.
        # 최신 보도사진이 먼저 22개를 차지하는 현상을 방지한다.
        publishers = sorted([a for a in plausible if not _is_google_news_url(a['url'])],
                            key=lambda a:(editorial_priority({**a,'category':category}),a['date']), reverse=True)
        enriched = _fetch_verified_entries(publishers,category,seen_urls,trials=22)
        googles = sorted([a for a in plausible if _is_google_news_url(a['url'])],
                         key=lambda a:(editorial_priority({**a,'category':category}),a['date']), reverse=True)
        decoded_count = 0
        if len(enriched) < max_per_category and googles:
            decoded = _decode_google_rows(googles,limit=14)
            decoded_count = len(decoded)
            enriched += _fetch_verified_entries(decoded,category,
                    seen_urls | {x['url'] for x in enriched},trials=14)
        # Keep source diversity: score clear real facts, then publication date.
        enriched.sort(key=lambda x: candidate_score(x,today), reverse=True)
        out[category] = enriched[:max_per_category]
        print(f'[원문 수집] {category}: RSS/검색 {len(rows)}건, 날짜·제목 필터 {len(plausible)}건, '
              f'언론사 직접 링크 {len(publishers)}건, Google 링크 복원 {decoded_count}건, '
              f'본문 검증 후보 {len(out[category])}건',flush=True)
        seen_urls.update(x['url'] for x in out[category])
    return out


def _check_details(item:dict, evidence_source:str, *, number_source:str | None=None) -> tuple[bool,str]:
    headline=compact(item.get('headline',''))
    summary=compact(item.get('summary',''))
    if not (18<=len(headline)<=56): return False, '제목이 너무 짧거나 길음'
    minimum = 55 if item.get('category') in GENERAL_CATEGORIES else 70
    if not (minimum<=len(summary)<=180): return False, f'설명 길이 {len(summary)}자(필요: {minimum}~180자), 확인된 사실을 포함해야 함'
    if not re.search(r'[가-힣]',headline+summary): return False,'한글 뉴스 문장이 아님'
    if any(x in headline+summary for x in BANNED_FILLER): return False,'공허한 상투적 표현'
    if '…' in headline or '...' in headline: return False,'제목이 잘림'
    h,b=normalize(headline),normalize(summary)
    if b.startswith(h) or (h and b.startswith(h[:min(25,len(h))])):
        return False,'제목을 본문에 재진술'
    proofs, evidence_error = _verified_evidence(item, evidence_source)
    if evidence_error: return False, evidence_error
    # AI가 존재하지 않는 통계·날짜를 새로 만들어내는 기본적인 오류 방지.
    numbers=lambda s:set(re.findall(r'\d+(?:[,.]\d+)*',s))
    # Publication date and the article headline are verified source metadata.
    # They may contain dates (e.g., "19일") that the downloaded body omits.
    # Preserve the fail-closed policy for any number absent from all three.
    scope = evidence_source if number_source is None else number_source
    missing=numbers(headline+' '+summary)-numbers(scope)
    if missing: return False, f'원문에 없는 숫자 {sorted(missing)[:3]}'
    if len(normalize(summary))<=len(normalize(headline))*1.3:
        return False,'본문이 제목을 충분히 넘어서는 새로운 사실을 제공하지 않음'
    return True,''


def validate_article(item:dict, source:dict) -> tuple[bool,str]:
    if item.get('candidate_id')!=source.get('candidate_id'):return False,'선택 후보와 근거 자료 불일치'
    if (source.get('category') in GENERAL_CATEGORIES and
        not topic_matches_title(source.get('title',''),
                                compact(item.get('headline',''))+' '+compact(item.get('summary','')))):
        return False,'원문 기사 제목과 작성 원고의 주제가 다름'
    return _check_details(item, source.get('content',''), number_source=' '.join(
        str(source.get(part, '') or '') for part in ('title', 'date', 'content')))


def _evidence_digest(article: dict, *, max_passages: int = 9) -> dict[str, str]:
    """Select a short, relevant subset of real source-anchored passage IDs.

    Supplying 4000 chars of prose AND up to 32 passage excerpts often causes
    needless conditional omissions. The chosen IDs remain in the complete
    catalog; downstream verification still uses the full downloaded article.
    """
    catalog=evidence_catalog(article.get('content',''))
    if len(catalog)<=max_passages: return catalog
    tokens={normalize(t) for t in re.findall(r'[가-힣A-Za-z]{2,}',article.get('title',''))
            if len(normalize(t))>=2}
    boilerplate=('무단전재','재배포금지','구독신청','로그인','기사제보',
                 '개인정보처리','저작권','다른 기사','페이지 이동')
    verbs=('발표','시행','개최','공개','의결','확대','지원','신청','예정',
           '추진','조사','검토','도입','확정','발급','개편','설명')
    scored=[]
    for rank,(eid,passage) in enumerate(catalog.items()):
        if any(x in passage for x in boilerplate): continue
        norm=normalize(passage)
        score=(min(15,sum(1 for t in tokens if t in norm)*3)
               +min(5,sum(1 for v in verbs if v in passage))
               +min(5,len(re.findall(r'\d+(?:[,.]\d+)*',passage)))
               + (2 if 35<=len(passage)<=200 else 0)
               - rank*.12)
        scored.append((score,rank,eid,passage))
    selected=sorted(sorted(scored,reverse=True)[:max_passages],key=lambda x:x[1])
    if len(selected)<2: return dict(list(catalog.items())[:max_passages])
    return {eid:p for _,_,eid,p in selected}


def _call_gemini(key:str, input_payload:list[dict], needed_categories:tuple[str,...],
                 repair_notes:dict[str,str] | None=None) -> dict:
    """근거 기사 인용·길이 조건이 있는 구조화된 JSON을 요청한다."""
    # Send only relevant, immutable passage IDs, not the full article twice.
    # The model's output is still validated against the complete source text.
    schemas=[{'category':a['category'],'candidate_id':a['candidate_id'],
            'title':a['title'],'published':a['date'],
            'evidence_catalog':_evidence_digest(a)}
            for a in input_payload]
    instruction='''당신은 한국어 뉴스 편집자입니다. 고객에게 전달할 뉴스이므로 아래 원문에서 확인되는 사실만 사용하세요.
각 category에서 원문 근거가 확인되는 중요한 기사 1건을 선택합니다. 제공된 근거 문장이 두 개 이상 있으면 먼저 그 문장들을 바탕으로 완성하세요.
자료에 없는 사실을 추가하지 마세요. 사진 촬영·악수·행사 개최 자체보다 결정·변경·조치·영향을 우선하세요. 독립 근거가 2개 미만이면 해당 category를 생략하세요.
headline은 18~56자이며, 누가 무엇을 했는지 구체적으로 드러나야 합니다.
summary는 공백과 문장부호를 포함해 기본 130~170자로 작성하되, 일반 아침뉴스는 내용이 충분하면 120~180자를 목표로 합니다. 의료 뉴스도 120~180자를 목표로 합니다. 근거가 부족하면 확인된 사실만 쓰며 55자(의료 70자) 미만이면 다른 기사를 고르세요. 불필요한 사실로 글자 수를 채우지 마세요.
헤드라인에서 핵심 결과를 전달하고 요약은 제목에 없는 배경·조치·수치·영향 등 새로운 사실을 전달합니다. 이미 제목에 담긴 사건 설명을 되풀이하지 마세요. 내용이 충분하면 자연스러운 1~2문장으로 편집하세요.
사실이 부족할 때는 분량을 채우려고 관용구를 붙이지 말고, 같은 카테고리의 다른 후보를 사용하세요.
‘논의가 이어집니다’, ‘추가 발표를 확인해야 합니다’, ‘중요합니다’, ‘관심이 높습니다’처럼 새 사실이 없는 문장은 절대 금지합니다.
맞춤법, 조사, 문장 호응을 검토하고 동일 명사의 불필요한 반복을 줄이세요. 고유명사·전시명·정책명은 원문 표기를 보존하고 작품·전시 제목에는 따옴표를 사용하세요. 본문의 서술 문장은 '~습니다'체로 마무리하세요. 제목은 자연스러운 명사형을 권장합니다. 기사 제목과 본문이 같은 뜻을 반복하는 경우 새로운 사실로 교체하세요. 전시·포럼 안내는 국민 생활에 직접적인 효용이 없으면 생활/문화 분야의 다른 기사를 우선하세요. 출처명·신문사명·기사 날짜를 본문 아래에 쓰지 마세요. 헤드라인을 본문 첫머리에 다시 붙이지 마세요.
정치·의료 정책에서 제안/검토/발표/확정/시행을 혼동하지 마세요. 신약은 연구/비임상/임상/허가/급여를 구분하세요.
수치를 쓰려면 원문의 숫자 표기를 그대로 쓰고 새로운 수치·기간·일정을 만들어내지 마세요.
원문 전체를 그대로 붙여 넣지 않고 관련 근거 문장만 압축해 evidence_catalog에 제시했습니다. 이 자료는 기사 원문에서 그대로 추출한 사실입니다.
각 ID의 문장을 그대로 복사하는 대신 사실을 정확하게 요약하세요. 원문에는 사전에 추출한 evidence_catalog가 있습니다. evidence_ids 배열에는 **선택한 후보의 evidence_catalog에서 서로 다른 문장 ID 두 개**(예: ["E03","E07"])만 골라 넣으세요.
인용문을 직접 재작성하거나 창작하지 마세요. 두 ID의 근거 문장이 summary의 핵심 사실을 실제로 뒷받침해야 합니다.
독립적인 사실 2개가 확인되지 않는 후보는 선택하지 마세요.
응답 전 headline 및 summary 길이를 확인하세요. 일반 아침뉴스는 55~180자, 보험·의료 뉴스는 70~180자이며, 120~180자의 충실한 설명을 우선하고 원문에서 확인되지 않는 사실을 추가하지 마세요.
반드시 {"items":[{"category":"...","candidate_id":"원문 후보 id","headline":"...","summary":"...","evidence_ids":["E01", "E02"]}]} JSON만 출력하세요.
요청 카테고리: ''' + ', '.join(needed_categories)
    if len(needed_categories)==1 and len(input_payload)==1:
        instruction += ('\n이번 요청은 단 하나의 분야, 단 하나의 확인된 기사입니다. '
                        '근거 ID가 서로 다른 두 사실을 뒷받침하면 반드시 items에 기사 1개를 반환하세요. '
                        '단순히 기사 작성이 어렵다는 이유로 빈 목록을 반환하지 마세요. '
                        '근거가 실제로 부족한 경우에만 빈 배열을 반환하세요.')
    if repair_notes:
        instruction += ('\n이 요청은 1차 출력에서 검증되지 않은 분야의 **재작성**입니다. '
                        '다음 사유를 반드시 해소하세요. 검증 기준을 줄이거나 원문에 없는 사실을 넣어서는 안 됩니다. '
                        + json.dumps(repair_notes,ensure_ascii=False))
    item_schema={
      'type':'OBJECT',
      'properties':{
       'category':{'type':'STRING','enum':list(needed_categories)},
       'candidate_id':{'type':'STRING'},
       'headline':{'type':'STRING'},
       'summary':{'type':'STRING'},
       'evidence_ids':{'type':'ARRAY','items':{'type':'STRING'}}
      },
      'required':['category','candidate_id','headline','summary','evidence_ids']
    }
    output_schema={'type':'OBJECT', 'properties':{'items':{'type':'ARRAY','items':item_schema}},
                   'required':['items']}
    url='https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent'
    payload={
      'contents':[{'parts':[{'text':instruction+'\n자료(JSON): '+json.dumps(schemas,ensure_ascii=False)}]}],
      'generationConfig':{'responseMimeType':'application/json','responseSchema':output_schema,
                          'temperature':0.05, 'maxOutputTokens':5000}
    }
    # One normal attempt + two bounded retries for transient errors only.
    # Logs contain HTTP status and API error *class*, never secret keys or text.
    for attempt in range(3):
        try:
            response=requests.post(url,headers={'x-goog-api-key':key},json=payload,timeout=95)
            response.raise_for_status()
            break
        except requests.HTTPError as exc:
            reply=getattr(exc, 'response', None) or response
            status,code=_api_error_details(reply)
            retriable = status in (408,429,500,502,503,504)
            # A daily quota failure is not resolved by immediate retries.
            quota_type=''
            try:
                details=reply.json().get('error',{}).get('message','')
                quota_type=details.lower() if isinstance(details,str) else ''
            except (ValueError,AttributeError,TypeError):
                pass
            if status==429 and ('per day' in quota_type or 'daily' in quota_type):
                retriable=False
            if retriable and attempt<2:
                time.sleep(2 ** attempt)
                continue
            raise GeminiApiRequestError(status,code,retryable=retriable) from None
        except (requests.Timeout,requests.ConnectionError) as exc:
            if attempt<2:
                time.sleep(2 ** attempt)
                continue
            raise GeminiApiRequestError(0,type(exc).__name__,retryable=True) from None
    data=response.json()
    raw=data['candidates'][0]['content']['parts'][0]['text']
    return json.loads(raw)




def _fallback_sentence_candidates(article: dict) -> list[tuple[float, str, str]]:
    """Select source-verbatim, self-contained statements with grounded actions.

    Previous versions excluded most genuine reporting by demanding 27–95
    characters, a tiny fixed list of verbs and title-keyword overlap.  Real
    Korean wire-service sentences often exceed 95 characters or use passive
    verbs.  We still reject incomplete fragments, advertorial boilerplate,
    ungrounded statements, and sentences without factual content.
    """
    body = compact(article.get('content', ''))
    title = compact(article.get('title', ''))
    if not valid_link(article.get('url','')) or len(normalize(body)) < 260:
        return []
    if any(x.lower() in title.lower() for x in BAD_TITLES + BANNED_FILLER):
        return []
    catalog = evidence_catalog(body)
    title_terms = {normalize(x) for x in re.findall(r'[가-힣A-Za-z]{2,}', title)
                   if len(normalize(x)) >= 2 and x not in (
                       '관련','대한','추진','오늘','내일','한국','정부','발표','이날')}
    boilerplate = ('무단전재','재배포','제보','기사제공','구독','ⓒ',
                   '사진=','기자=','Copyright','All Rights Reserved',
                   '기자]','이미지 크게 보기','개인정보','저작권','관련기사')
    # Frequent real Korean news verbs; a rigid specific list is not a quality
    # test. Combine factual predicates with article title/actor/date anchors.
    report_verbs = ('밝혔','밝혔다','발표','설명','확인','공개','의결','통과','시행',
                    '진행','운영','제공','선정','검토','예정','추진','지원','확대',
                    '개최','조사','대응','참여','개정','마련','도입','접수','시작',
                    '증가','감소','열렸','개설','조성','진행됐','발급','출범',
                    '실시','결정','변경','개발','논의','기록','발견','집계',
                    '진출','공연','전시','공연했','열린','진행된','연구')
    chosen = []
    seen = set()
    for index, (eid, passage) in enumerate(catalog.items()):
        sentence = compact(passage)
        identifier = normalize(sentence)
        if identifier in seen or not (24 <= len(sentence) <= 180):
            continue
        if not sentence.endswith(('.', '!', '?', '。')) or not re.search(r'[가-힣]', sentence):
            continue
        if any(b.lower() in sentence.lower() for b in boilerplate + BANNED_FILLER):
            continue
        # Require a complete news-style assertion; title only or an orphaned
        # noun phrase cannot serve as evidence.
        if not (any(term in sentence for term in report_verbs) or
                re.search(r'(?:했다|된다|됐다|있다|없다|나섰다|열었다|늘었다|줄었다|이다|었다|으로 보인다|다고 전했다)[.!?。]$', sentence)):
            continue
        overlap = sum(1 for t in title_terms if t in identifier)
        has_number = bool(re.search(r'\d+(?:[,.]\d+)*(?:년|월|일|명|곳|개|원|%|건|차례|억|조)', sentence))
        has_actor = bool(re.search(r'(?:(?:청|부|처|원|공사|공단|위원회|협회|재단|지자체|시|군|구|법원|국회|경찰|기업|대학|병원)은|는|에서)', sentence))
        if not (overlap >= 1 or has_actor or has_number):
            continue
        score = (min(8, overlap * 2) + (3 if has_number else 0) +
                 (2 if has_actor else 0) + (1 if 35 <= len(sentence) <= 83 else 0)
                 - index * .08)
        chosen.append((score, eid, sentence))
        seen.add(identifier)
    return chosen


def _formalize_source_sentence(sentence: str) -> str:
    """Only convert common past/statement endings to polite news style.

    This never changes dates, actors, events, negation or modal language; all
    factual statements still come from original source passages.
    """
    replacements = (
        ('밝혔다.', '밝혔습니다.'), ('말했다.', '말했습니다.'),
        ('알렸다.', '알렸습니다.'), ('열었다.', '열었습니다.'),
        ('논의했다.', '논의했습니다.'), ('설명했다.', '설명했습니다.'),
        ('제시했다.', '제시했습니다.'), ('진행했다.', '진행했습니다.'),
        ('검토했다.', '검토했습니다.'), ('운영했다.', '운영했습니다.'),
        ('출범했다.', '출범했습니다.'), ('시행했다.', '시행했습니다.'),
        ('확대했다.', '확대했습니다.'), ('발표했다.', '발표했습니다.'),
        ('개최했다.', '개최했습니다.'), ('결정했다.', '결정했습니다.'),
        ('확정했다.', '확정했습니다.'), ('통과했다.', '통과했습니다.'),
        ('공개했다.', '공개했습니다.'), ('완료했다.', '완료했습니다.'),
        ('조사했다.', '조사했습니다.'), ('변경했다.', '변경했습니다.'),
        ('연구했다.', '연구했습니다.'), ('참여했다.', '참여했습니다.'),
        ('계획했다.', '계획했습니다.'), ('선정했다.', '선정했습니다.'),
        ('확인했다.', '확인했습니다.'), ('지원했다.', '지원했습니다.'),
        ('나왔다.', '나왔습니다.'), ('시작했다.', '시작했습니다.'),
        ('도입했다.', '도입했습니다.'), ('예정이다.', '예정입니다.'),
        ('예정이라고 했다.', '예정이라고 했습니다.'),
        ('했다.', '했습니다.'), ('됐다.', '됐습니다.'),
        ('되었다.', '되었습니다.'), ('있다.', '있습니다.'),
        ('없다.', '없습니다.'), ('한다.', '합니다.'), ('된다.', '됩니다.'),
    )
    for old, new in replacements:
        if sentence.endswith(old):
            return sentence[:-len(old)] + new
    return sentence




def _best_full_fact_pair(article: dict) -> tuple[str, str, str, str] | None:
    """Choose two independently grounded COMPLETE source facts for a narrow repair.

    Unlike the extractive path, the selected complete sentences may be long:
    the model is asked to paraphrase only these two, then all final facts are
    checked against the same real article.  Never promote source fragments.
    """
    body = compact(article.get('content', ''))
    if len(normalize(body)) < 260 or not valid_link(article.get('url', '')):
        return None
    catalog = evidence_catalog(body)
    if len(catalog) < 2:
        return None
    title_terms = {normalize(x) for x in re.findall(r'[가-힣A-Za-z]{2,}',article.get('title',''))
                   if len(normalize(x)) >= 3}
    facts = []
    junk = ('무단전재','재배포','Copyright','무단 복제','기자 구독','제보','다른기사',
            '기사제공','저작권','이용약관') + BANNED_FILLER
    for i,(eid,text) in enumerate(catalog.items()):
        t=compact(text)
        if not (27 <= len(t) <= 500) or not t.endswith(('.', '!', '?', '。')):
            continue
        if any(b.lower() in t.lower() for b in junk):
            continue
        norm=normalize(t)
        overlap=sum(1 for x in title_terms if x in norm)
        grounded=bool(re.search(r'\d+(?:[,.]\d+)*(?:년|월|일|명|명|곳|개|원|%|건)',t))
        event=any(w in t for w in ('발표','밝혔','시행','진행','개최','예정','공개',
                                  '마련','개정','선정','제공','참석','확대','운영',
                                  '지원','접수','열었','논의','검토','추진',
                                  '전시','공연','개막','폐막','기획','참여',
                                  '지난','확인','증가','감소','열렸'))
        # A complete, attributed sentence can report a real political fact
        # without using a verb from the small keyword list.
        attributed = bool(re.search(r'(?:했다|됐다|이다|있다|없다|한다|된다|밝혔다|전했다|설명했다)[.!?。]$', t))
        if not (event or grounded or overlap >= 2 or (overlap >= 1 and attributed)):
            continue
        facts.append((4*overlap+3*grounded+2*event-i*.08,eid,t))
    if len(facts) < 2:
        return None
    # Minimize repeated sentences: require each statement to contain some
    # independent informational material (different 3+ syllable words).
    pairs=[]
    for j,(a,e1,t1) in enumerate(facts):
        for b,e2,t2 in facts[j+1:]:
            words1=set(re.findall(r'[가-힣A-Za-z]{3,}',t1))
            words2=set(re.findall(r'[가-힣A-Za-z]{3,}',t2))
            if words1 and words2 and len(words1 & words2)/min(len(words1),len(words2)) >= .86:
                continue
            pairs.append((a+b,e1,t1,e2,t2))
    if not pairs: return None
    _,e1,t1,e2,t2=max(pairs,key=lambda p:p[0])
    return e1,t1,e2,t2


def _narrow_ai_repair(key: str, candidate: dict) -> dict | None:
    """Single grounded rewrite; cannot select new sources or invent evidence IDs.

    This is a last resort after normal writing and full-sentence extractive
    fallback have both failed.  It only summarizes two preselected complete
    verbatim facts, never a self-chosen article.
    """
    pair = _best_full_fact_pair(candidate)
    if not pair: return None
    eid1,source1,eid2,source2=pair
    raw_title=compact(candidate.get('title',''))
    instruction=('다음 한국어 뉴스 기사에서 실제로 추출한 완결된 사실 문장 두 개만 이용해 '
       '고객에게 보여줄 요약을 작성해 주세요. 문장에 없는 일시·숫자·기관·제도·시행 여부를 만들어서는 안 됩니다. '
       '확정/제안/검토/시행을 구분하고 자극적인 해석이나 상투적인 말은 제외하세요. '
       'headline은 18~56자, summary는 공백 포함 55~180자(보험·의료는 70~180자)이며 실제 사실 2개를 담은 자연스러운 1~2문장입니다. '
       '제목을 그대로 본문 앞에 반복하지 마세요. 단 한 건에 대해 headline과 summary 두 문자열을 반드시 반환하세요. '
       '요약에 나타나는 모든 숫자는 제공된 출처 제목 또는 아래 사실 문장에 나오는 숫자여야 합니다. 원문에서 확인되지 않는 새로운 효과나 향후 일정은 추가하지 마세요. 같은 의미를 반복해서 분량을 채우지 마세요. '
       '원문 제목: '+raw_title+'\n근거1: '+source1+'\n근거2: '+source2)
    schema={'type':'OBJECT','properties':{'headline':{'type':'STRING'},'summary':{'type':'STRING'}},
            'required':['headline','summary']}
    model=os.environ.get('GEMINI_EDITOR_MODEL','gemini-3.5-flash-lite').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{2,90}', model):
        raise PublicationQualityError('잘못된 Gemini 모델명 설정')
    url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
    payload={'contents':[{'parts':[{'text':instruction}]}],
             'generationConfig':{'responseMimeType':'application/json','responseSchema':schema,
                                 'temperature':0.1,'maxOutputTokens':1500}}
    try:
        response=requests.post(url,headers={'x-goog-api-key':key},json=payload,timeout=65)
        response.raise_for_status()
        parsed=response.json()
        raw=parsed['candidates'][0]['content']['parts'][0]['text']
        obj=json.loads(raw)
    except (requests.RequestException,KeyError,IndexError,TypeError,ValueError,json.JSONDecodeError) as exc:
        # No key or response body in logs.
        print('[근거 2문장 좁힌 재작성] API/응답 오류: '+type(exc).__name__,flush=True)
        return None
    if not isinstance(obj,dict):return None
    # Evidence IDs and candidate identity are determined by trusted code.
    draft={'category':candidate['category'],'candidate_id':candidate['candidate_id'],
           'headline':compact(obj.get('headline','')),'summary':compact(obj.get('summary','')),
           'evidence_ids':[eid1,eid2]}
    draft=_compact_long_summary(draft)
    ok,why=validate_article(draft,candidate)
    if not ok:
        print('[근거 2문장 좁힌 재작성] 검증 탈락: '+why,flush=True)
        return None
    return draft


def _safe_extractive_fallback(article: dict) -> dict | None:
    """Return a short exact-source fallback only with two independent facts.

    Do not break clauses mid-sentence or pad with unsupported editorial text.
    The candidate headline is its actual RSS title, and the body consists of
    two short *complete* source statements, with only polite ending changes. A failed check means no fallback.
    """
    sentences = _fallback_sentence_candidates(article)
    if len(sentences) < 2:
        return None
    # Original article order is preferred over sensational or scattered facts.
    ranked=[]
    for i, (score_a, eid_a, text_a) in enumerate(sentences):
        for score_b, eid_b, text_b in sentences[i+1:]:
            # The same fact repeated with small changes is not two facts.
            tokens_a = {x for x in re.findall(r'[가-힣A-Za-z]{3,}', text_a)
                        if x not in ('정부는','이날은','관계자는','이번에는')}
            tokens_b = {x for x in re.findall(r'[가-힣A-Za-z]{3,}', text_b)
                        if x not in ('정부는','이날은','관계자는','이번에는')}
            if tokens_a and tokens_b and len(tokens_a & tokens_b) / min(len(tokens_a), len(tokens_b)) > .82:
                continue
            summary = _formalize_source_sentence(text_a) + ' ' + _formalize_source_sentence(text_b)
            minimum = 55 if article.get('category') in GENERAL_CATEGORIES else 70
            if not (minimum <= len(summary) <= 180):
                continue
            # Conservative copyright guard: never use more than 25 whitespace
            # separated words verbatim from a single private news source.
            if len(summary.split()) > 25:
                continue
            fallback = {'category':article.get('category'),
                        'candidate_id':article.get('candidate_id'),
                        'headline':compact(article.get('title','')),
                        'summary':summary, 'evidence_ids':[eid_a,eid_b]}
            ok, _ = validate_article(fallback, article)
            if not ok:
                continue
            ranked.append((score_a + score_b, -i, fallback))
    if not ranked:
        return None
    return max(ranked, key=lambda x:(x[0], x[1]))[2]


def write_verified_news(candidates:dict[str,list[dict]], *, medical:bool=False) -> list[dict]:
    key=os.environ.get('GEMINI_API_KEY','').strip()
    if not key:raise PublicationQualityError('GEMINI_API_KEY 없음: 기사 본문을 자동 제작하지 않습니다.')
    intended=tuple(MEDICAL_CATEGORIES if medical else GENERAL_CATEGORIES)
    flat=[]
    for cat in intended:flat.extend(candidates.get(cat,[]))
    if not flat:
        raise PublicationQualityError('원문 전문을 읽을 수 있는 기사 후보가 없습니다.')
    sources={a['candidate_id']:a for a in flat}
    approved:dict[str,dict]={}
    rejected:list[tuple[str,str]]=[]
    reasons:dict[str,str]={}

    def accept_result(res:dict,requested:tuple[str,...]):
        if not isinstance(res,dict) or not isinstance(res.get('items'),list):
            raise ValueError('AI가 검증 가능한 items JSON 배열을 제공하지 않았습니다.')
        arrived=set()
        for item in res['items']:
            if not isinstance(item,dict):continue
            item=_compact_long_summary(item)
            cat=item.get('category')
            if cat not in requested or cat in approved:continue
            arrived.add(cat)
            source=sources.get(str(item.get('candidate_id','')))
            if not source or source['category']!=cat:
                reason='선택 후보 ID가 입력 원문과 일치하지 않음'
            else:
                ok,reason=validate_article(item,source)
                if ok and not medical and any(same_news_event(
                        {'title':source['title'],'headline':item.get('headline',''),'url':source['url']},
                        selected) for selected in approved.values()):
                    ok,reason=False,'이미 다른 분야에 선정된 동일 사건: 다른 기사 필요'
                if ok:
                    approved[cat]={
                      'category':cat,'title':source['title'],
                      'headline':compact(item['headline']),
                      'summary':compact(item['summary']),'date':source['date'],
                      'source':source['source'],'url':source['url'],
                      'fact_proofs':[{'quote':compact(quote)[:180]} for quote in _verified_evidence(item,source['content'])[0]],
                      'fact_content_hash':hashlib.sha256(source['content'].encode()).hexdigest()[:16],
                    }
                    reasons.pop(cat,None)
                    print(f'[기사 검증 통과] {cat}: 제목과 원문 근거 확인')
                    continue
            reasons[cat]=reason
            rejected.append((cat,reason))
            print(f'[기사 검증 탈락] {cat}: {reason}')
        for cat in requested:
            if cat not in approved and cat not in arrived:
                reason='AI가 해당 분야의 검증 가능한 기사를 반환하지 않음'
                reasons[cat]=reason
                rejected.append((cat,reason))

    handled_errors = (requests.RequestException, GeminiApiRequestError,
                      ValueError, KeyError, IndexError, TypeError)
    def error_name(exc):
        return str(exc) if isinstance(exc,GeminiApiRequestError) else type(exc).__name__

    # Initial pass: one complete article per category is easier to follow than
    # an enormous 15-article prompt. Keep other candidates for later repairs.
    print('[AI 검증] 1차 분야별 원문 후보: '+', '.join(f'{cat}={len(candidates.get(cat,[]))}' for cat in intended),flush=True)
    initial=[candidates[cat][0] for cat in intended if candidates.get(cat)]
    initial_categories=tuple(cat for cat in intended if candidates.get(cat))
    if initial:
        try:
            accept_result(_call_gemini(key,initial,initial_categories),initial_categories)
        except handled_errors as exc:
            print('[일괄 편집 실패] '+error_name(exc)+' — 분야별 재작성 진행',flush=True)
            if isinstance(exc,GeminiApiRequestError) and not exc.retryable:
                raise PublicationQualityError('Gemini API 호출 실패: '+error_name(exc)) from None

    # If the model omits one category in a batch, reissuing the SAME batch
    # does not solve anything. Retry only the missing category with an explicit
    # single-category request and alternate *real* article candidates.
    # Never generate an unsourced replacement or weaken quality checks.
    for cat in intended:
        if cat in approved: continue
        options=candidates.get(cat,[])
        if not options:
            reasons[cat]='원문 전문과 사실 근거가 확인된 기사 후보가 없음'
            print(f'[분야별 재시도 불가] {cat}: 검증 가능한 원문 후보 0건',flush=True)
            continue
        for attempt, candidate in enumerate(options[:5],1):
            if cat in approved:break
            note=reasons.get(cat,'일괄 요청에서 분야 누락')
            # Give the model all and only the facts of this one article;
            # explicit output is still verified with actual downloaded text.
            request_note={cat:(f'{note}. 반드시 {cat} 분야 1건을 검토하여 '
                '원문 근거 2개가 있으면 정확히 1건만 반환하세요. '
                '근거가 없으면 빈 목록을 반환하세요. 다른 분야 기사는 선택하지 마세요.')}
            print(f'[분야별 단독 재검증] {cat}: 후보 {attempt}/{min(5,len(options))}',flush=True)
            try:
                accept_result(_call_gemini(key,[candidate],(cat,),repair_notes=request_note),(cat,))
            except handled_errors as exc:
                print(f'[분야별 재시도 오류] {cat}: '+error_name(exc),flush=True)
                if isinstance(exc,GeminiApiRequestError) and not exc.retryable:
                    raise PublicationQualityError('Gemini API 호출 실패: '+error_name(exc)) from None
        if cat not in approved and cat not in reasons:
            reasons[cat]='확인된 원문 후보가 있지만 AI가 근거를 검증하지 못함'

    # Last resort: two *complete* facts copied from the same verified source.
    # If AI omits a field, do not hallucinate, weaken checks, or fill with
    # policy boilerplate. This only succeeds for a sufficiently rich article.
    for cat in intended:
        if cat in approved:
            continue
        for candidate in candidates.get(cat, [])[:5]:
            if not medical and any(same_news_event(candidate, other) for other in approved.values()):
                continue
            fallback = _safe_extractive_fallback(candidate)
            if fallback is None:
                continue
            if not medical and any(same_news_event(
                    {'title':candidate['title'],'headline':fallback['headline'],'url':candidate['url']},
                    other) for other in approved.values()):
                continue
            evidence, _ = _verified_evidence(fallback, candidate['content'])
            approved[cat] = {
                'category':cat, 'title':candidate['title'],
                'headline':fallback['headline'], 'summary':fallback['summary'],
                'date':candidate['date'], 'source':candidate['source'],
                'url':candidate['url'],
                'fact_proofs':[{'quote':compact(e)[:180]} for e in evidence],
                'fact_content_hash':hashlib.sha256(candidate['content'].encode()).hexdigest()[:16],
                'selection_mode':'extractive_fallback',
            }
            reasons.pop(cat, None)
            print(f'[검증된 원문 기반 대체] {cat}: 독립 근거 2개, 70~180자 요약 확인', flush=True)
            break
        if cat not in approved:
            reasons[cat] = (reasons.get(cat, '검증 가능한 AI 기사 없음')
                            + ' / 원문 기반 대체도 사실 문장 2개·길이 기준 미충족')
            print(f'[원문 기반 대체 불가] {cat}: 완전한 사실 문장 두 개 및 길이 기준 미충족', flush=True)

    # The same full-length prompts often return an empty items[] even when
    # the source contains two excellent factual statements. For remaining
    # categories allow ONE narrow rewrite with *preselected* passage IDs.
    # Output still passes the normal source/number/title checks.
    for cat in intended:
        if cat in approved: continue
        for candidate in candidates.get(cat,[])[:5]:
            if not medical and any(same_news_event(candidate,other) for other in approved.values()):
                continue
            try:
                fixed=_narrow_ai_repair(key,candidate)
            except PublicationQualityError:
                raise
            if fixed is None:
                print(f'[근거 2문장 재작성 불가] {cat}: 후보의 완결 사실 근거 부족 또는 재작성 검증 탈락', flush=True)
                continue
            if not medical and any(same_news_event(
                    {'title':candidate['title'],'headline':fixed['headline'],'url':candidate['url']},
                    other) for other in approved.values()):
                continue
            proofs,_=_verified_evidence(fixed,candidate['content'])
            approved[cat]={
                'category':cat, 'title':candidate['title'],
                'headline':fixed['headline'],'summary':fixed['summary'],
                'date':candidate['date'],'source':candidate['source'],
                'url':candidate['url'],'fact_proofs':[{'quote':compact(e)[:180]} for e in proofs],
                'fact_content_hash':hashlib.sha256(candidate['content'].encode()).hexdigest()[:16],
                'selection_mode':'grounded_two_fact_rewrite',
            }
            reasons.pop(cat,None)
            print(f'[근거 2문장으로 재작성 통과] {cat}',flush=True)
            break

    missing=[cat for cat in intended if cat not in approved]
    if missing:
        report=[(cat,reasons.get(cat,'원문 검증 또는 AI 재시도 실패')) for cat in missing]
        label='보험·의료 브리핑' if medical else '아침뉴스'
        raise PublicationQualityError(label+' 검증 미통과(재시도 후): '+repr(report))
    result=[approved[cat] for cat in intended]
    if has_duplicate_topics(result):
        raise PublicationQualityError('다른 분야에 사실상 동일한 사건이 중복됐습니다. 기사 재선정 필요')
    return result


def _topic_family(item: dict) -> str:
    """High-confidence same-event families; avoid mere overlap in generic news words.

    Titles are publisher headlines and model headlines (not unrelated body/sidebar
    text). If the evidence is ambiguous, the ordinary overlap check applies.
    """
    title=normalize(str(item.get('title',''))+' '+str(item.get('headline','')))
    if '수능' in title and any(x in title for x in ('부정행위','ai','인공지능','스마트안경')):
        return '수능-ai-부정행위'
    if '전세사기' in title:
        return '전세사기'
    if '의대정원' in title or ('의과대학' in title and '정원' in title):
        return '의대정원'
    if '한일정상회담' in title or ('한일' in title and '정상회담' in title):
        return '한일정상회담'
    return ''


def same_news_event(a: dict, b: dict) -> bool:
    """Prevent the same story taking two slots without conflating whole beats."""
    if a.get('url') and b.get('url') and a['url']==b['url']:
        return True
    family_a, family_b=_topic_family(a),_topic_family(b)
    if family_a and family_a==family_b:
        return True
    stop={'한국','정부','발표','진행','대책','지원','보도','관련','국민','강화','이날',
          '논의','추진','개최','새로운','확대','예정','정책','주요','오늘','사실',
          '분야','행정','조치','안내','담당','기관','기자','지적','설명','확인'}
    def terms(item):
        # Use source article titles, not shared boilerplate in AI-written headlines.
        text=str(item.get('title') or item.get('headline') or '')
        return {x.lower() for x in re.findall(r'[가-힣A-Za-z]{3,}',text)
                if x.lower() not in stop}
    left,right=terms(a),terms(b)
    return bool(left and right and len(left & right)>=3
                and len(left & right)/min(len(left),len(right))>=.75)


def has_duplicate_topics(articles: list[dict]) -> bool:
    return any(same_news_event(a,b) for i,a in enumerate(articles)
               for b in articles[i+1:])


def build_news() -> tuple[list[dict],list[dict]]:
    general=write_verified_news(collect_candidates(GENERAL_CATEGORIES),medical=False)
    med=write_verified_news(collect_candidates(MEDICAL_CATEGORIES),medical=True)
    return general, med

