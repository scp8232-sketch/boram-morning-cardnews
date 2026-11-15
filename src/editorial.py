"""근거가 있는 기사를 선별하고 내용 없는 요약을 발행 전에 차단한다.

원칙: 기사 제목/RSS 한 줄만으로 본문을 만들지 않는다. 원문을 읽지 못하면 기사를 버린다.
비밀키 및 원문 전문은 공개 docs/ 폴더에 저장하지 않는다.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, date, timedelta
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
 '정치': ['https://www.newsis.com/RSS/politics.xml','https://www.yna.co.kr/rss/politics.xml'],
 '경제': ['https://www.newsis.com/RSS/economy.xml','https://www.yna.co.kr/rss/economy.xml'],
 '사회': ['https://www.mois.go.kr/gpms/view/jsp/rss/rss.jsp?ctxCd=1012','https://www.newsis.com/RSS/society.xml','https://www.yna.co.kr/rss/news.xml'],
 '국제': ['https://www.newsis.com/RSS/international.xml','https://www.yna.co.kr/rss/international.xml'],
 '생활/문화': ['https://www.newsis.com/RSS/culture.xml','https://www.yna.co.kr/rss/culture.xml'],
 '건강보험': ['https://www.yna.co.kr/rss/health.xml','https://www.newsis.com/RSS/health.xml'],
 '보험제도': ['https://www.newsis.com/RSS/bank.xml','https://www.yna.co.kr/rss/economy.xml'],
 '보건정책': ['https://www.newsis.com/RSS/health.xml','https://www.yna.co.kr/rss/health.xml'],
 '의료기술': ['https://www.newsis.com/RSS/health.xml','https://www.yna.co.kr/rss/health.xml'],
 '건강정보': ['https://www.yna.co.kr/rss/health.xml','https://www.newsis.com/RSS/health.xml'],
}
CATEGORY_TERMS = {
 '건강보험':('건강보험','보험급여','급여','수가','심평원','건보','국민건강보험','의료급여'),
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
 '생활/문화':'한국 문화축제 전시 공연 일정 when:5d',
 '건강보험':'건강보험 보험급여 국민건강보험심사평가원 when:10d',
 '보험제도':'보험금 청구 실손의료보험 금융감독원 when:10d',
 '보건정책':'보건복지부 의료정책 의료시설 when:7d',
 '의료기술':'신약 임상 식약처 의료기기 when:10d',
 '건강정보':'질병관리청 감염병 예방 질병 when:7d',
}

# 키워드만 있는 목록 페이지, 제목 복사, 의견 기사, 검색 결과를 실뉴스로 오인하는 것을 방지.
BAD_TITLES = ('민원인안내서', '주요통계(기간별)', '홈페이지', '메인페이지', '바로가기',
              '보도자료 목록', '이용약관', '기사 목록', '사진자료실', 'RSS 서비스', '[사설]',
              '[칼럼]', '[기고]', '독자투고', '광고', '오피니언', '초대합니다')
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
        try:
            dt=parsedate_to_datetime(raw_date)
            if dt.tzinfo is None: dt=dt.replace(tzinfo=KST)
            day=dt.astimezone(KST).date().isoformat()
        except (TypeError,ValueError,IndexError,AttributeError):
            try: day=date.fromisoformat(raw_date[:10]).isoformat()
            except (TypeError,ValueError): continue
        desc=compact(field('description','{http://www.w3.org/2005/Atom}summary',
                '{http://purl.org/rss/1.0/modules/content/}encoded'))
        source=compact(field('source')) or (urlsplit(url).hostname or '').replace('www.','')
        if title.endswith(' - '+source): title=title[:-(len(source)+3)]
        result.append({'title':title,'url':url,'date':day,'source':source,'snippet':desc[:700]})
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
    for tag in soup.select('script, style, nav, footer, header, aside, iframe, form, noscript, .ad, .advertisement, .copyright'):
        tag.decompose()
    # 기사 본문 전용 요소 우선, 뉴스/정부 사이트에 흔한 선택자 포함
    selectors=['#articleBodyContents','#articleBody','#article_body','.article_body',
        '.article-view-content','.article_view','.news_view','.newsview', '.article_txt',
        '.news-contents','.viewCont','.view_content','.articleContent','article','main']
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
        # Long editorial paragraphs can contain several facts. Split at a word
        # boundary; each piece remains an unmodified substring of the article.
        while len(sentence) > 210:
            i = sentence.rfind(' ', 105, 190)
            if i < 105: i = 180
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
    if 70 <= len(summary) <= 125:
        out['summary']=summary
        return out
    if len(summary)>125:
        sentences=re.split(r'(?<=[.!?。])\s+',summary)
        for count in range(len(sentences)-1,0,-1):
            fragment=' '.join(sentences[:count]).strip()
            if 70 <= len(fragment) <= 125 and fragment.endswith(('.', '!', '?', '。')):
                out['summary']=fragment
                return out
    out['summary']=summary
    return out

def candidate_score(a: dict, today:date) -> float:
    delta=max(0,(today-date.fromisoformat(a['date'])).days)
    contents=a.get('content','')
    # 회의일시·시행일·금액 등 객관적 사실이 있는 기사를 우선한다.
    numeric=min(8,len(re.findall(r'\d',contents)))
    return 40-delta*3 + min(20,len(contents)//240)+numeric*2


def collect_candidates(categories: tuple[str,...], *, today: date | None=None,
                       max_per_category: int=3) -> dict[str,list[dict]]:
    today=today or datetime.now(KST).date()
    out={}
    seen_urls=set()
    for category in categories:
        rows=[]
        for rss in FEEDS[category]:
            rows += feed_articles(rss)
        # 공식 보도자료 검색 보완. 구글 뉴스 링크는 원문으로 직접 연결될 때만 채택.
        query=NEWS_QUERIES[category]
        from urllib.parse import quote
        rows+=feed_articles('https://news.google.com/rss/search?q='+quote(query)+ '&hl=ko&gl=KR&ceid=KR:ko')
        plausible=[]
        for item in rows:
            if category in CATEGORY_TERMS and not any(term.lower() in item['title'].lower() for term in CATEGORY_TERMS[category]):
                continue
            max_days=7 if category in MEDICAL_CATEGORIES or category=='생활/문화' else 4
            if not is_recent(item['date'],max_days=max_days,now=today):continue
            if item['url'] in seen_urls or any(s.lower() in item['title'].lower() for s in BAD_TITLES):continue
            if len(normalize(item['title']))<15:continue
            plausible.append(item)
        # 최신 기사부터, 전체 기사 URL 읽기 시도 건수를 제한한다.
        plausible.sort(key=lambda a:a['date'],reverse=True)
        enriched=[]
        for entry in plausible[:12]:
            content=fetch_fulltext(entry['url'])
            # 본문을 읽을 수 없는 글은 배포하지 않는다.
            if len(normalize(content))<260 or len(evidence_catalog(content))<2: continue
            info={**entry,'category':category,'content':content}
            info['candidate_id']=hashlib.sha256(entry['url'].encode()).hexdigest()[:12]
            enriched.append(info)
            if len(enriched)>=max_per_category+2:break
        enriched.sort(key=lambda x:candidate_score(x,today),reverse=True)
        out[category]=enriched[:max_per_category]
        seen_urls.update(x['url'] for x in out[category])
    return out


def _check_details(item:dict, evidence_source:str, *, number_source:str | None=None) -> tuple[bool,str]:
    headline=compact(item.get('headline',''))
    summary=compact(item.get('summary',''))
    if not (18<=len(headline)<=56): return False, '제목이 너무 짧거나 길음'
    if not (70<=len(summary)<=125): return False, f'설명 길이 {len(summary)}자(필요: 70~125자), 확인된 사실을 2~3개 포함해야 함'
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
    return _check_details(item, source.get('content',''), number_source=' '.join(
        str(source.get(part, '') or '') for part in ('title', 'date', 'content')))


def _call_gemini(key:str, input_payload:list[dict], needed_categories:tuple[str,...],
                 repair_notes:dict[str,str] | None=None) -> dict:
    """근거 기사 인용·길이 조건이 있는 구조화된 JSON을 요청한다."""
    schemas=[{'category':a['category'],'candidate_id':a['candidate_id'],
            'title':a['title'],'published':a['date'],
            'body':a['content'][:4000],
            'evidence_catalog':evidence_catalog(a['content'])}
            for a in input_payload]
    instruction='''당신은 한국어 뉴스 편집자입니다. 고객에게 전달할 뉴스이므로 아래 원문에서 확인되는 사실만 사용하세요.
각 category별로 근거가 가장 충실하고 중요한 기사 1개를 선택하며, 적절한 기사가 없으면 그 category는 반환하지 마세요.
headline은 18~56자이며, 누가 무엇을 했는지 구체적으로 드러나야 합니다.
summary는 공백과 문장부호를 포함해 **반드시 70~125자**로 작성합니다. 목표는 90~105자입니다.
요약은 제목을 반복하지 말고 실제 원문에 나온 사실 2~3개를 자연스러운 2문장으로 연결합니다.
사실이 부족할 때는 분량을 채우려고 관용구를 붙이지 말고, 같은 카테고리의 다른 후보를 사용하세요.
‘논의가 이어집니다’, ‘추가 발표를 확인해야 합니다’, ‘중요합니다’, ‘관심이 높습니다’처럼 새 사실이 없는 문장은 절대 금지합니다.
출처명·신문사명·기사 날짜를 본문 아래에 쓰지 마세요. 헤드라인을 본문 첫머리에 다시 붙이지 마세요.
정치·의료 정책에서 제안/검토/발표/확정/시행을 혼동하지 마세요. 신약은 연구/비임상/임상/허가/급여를 구분하세요.
수치를 쓰려면 원문의 숫자 표기를 그대로 쓰고 새로운 수치·기간·일정을 만들어내지 마세요.
원문에는 사전에 추출한 evidence_catalog가 있습니다. evidence_ids 배열에는 **선택한 후보의 evidence_catalog에서 서로 다른 문장 ID 두 개**(예: ["E03","E07"])만 골라 넣으세요.
인용문을 직접 재작성하거나 창작하지 마세요. 두 ID의 근거 문장이 summary의 핵심 사실을 실제로 뒷받침해야 합니다.
독립적인 사실 2개가 확인되지 않는 후보는 선택하지 마세요.
응답 전 headline 길이와 summary 길이를 스스로 세고, summary가 70~125자가 아니면 고쳐서 제출하세요.
반드시 {"items":[{"category":"...","candidate_id":"원문 후보 id","headline":"...","summary":"...","evidence_ids":["E01", "E02"]}]} JSON만 출력하세요.
요청 카테고리: ''' + ', '.join(needed_categories)
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


def write_verified_news(candidates:dict[str,list[dict]], *, medical:bool=False) -> list[dict]:
    key=os.environ.get('GEMINI_API_KEY','').strip()
    if not key:raise PublicationQualityError('GEMINI_API_KEY 없음: 기사 본문을 자동 제작하지 않습니다.')
    intended=tuple(MEDICAL_CATEGORIES if medical else GENERAL_CATEGORIES)
    flat=[]
    for cat in intended:flat.extend(candidates.get(cat,[]))
    if len(flat)<(3 if medical else 5):
        raise PublicationQualityError('원문 전문을 읽을 수 있는 기사 후보가 부족합니다.')
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

    # First request checks all categories. Recheck *only missing categories* in
    # grouped batches, rather than 5 rapid individual calls that can hit free
    # API request rate limits. Previously approved facts are never rewritten.
    handled_errors = (requests.RequestException, GeminiApiRequestError,
                      ValueError, KeyError, IndexError, TypeError)
    def error_name(exc):
        return str(exc) if isinstance(exc,GeminiApiRequestError) else type(exc).__name__

    try:
        accept_result(_call_gemini(key,flat,intended), intended)
    except handled_errors as exc:
        print('[일괄 편집 실패] '+error_name(exc)+' — 묶음 재시도로 전환')
        if isinstance(exc,GeminiApiRequestError) and not exc.retryable:
            raise PublicationQualityError('Gemini API 호출 실패: '+error_name(exc)) from None

    for attempt in range(2):
        pending=tuple(cat for cat in intended if cat not in approved and candidates.get(cat))
        if not pending:
            break
        subset=[a for cat in pending for a in candidates[cat][:3]]
        repair_notes={cat:reasons.get(cat,'분야 누락 또는 검증 불충분: 다른 후보 또는 원문 근거로 재작성')
                      for cat in pending}
        try:
            accept_result(_call_gemini(key,subset,pending,repair_notes=repair_notes),pending)
        except handled_errors as exc:
            print('[묶음 재시도 오류] '+error_name(exc)+' — 남은 분야: '+', '.join(pending))
            if isinstance(exc,GeminiApiRequestError) and not exc.retryable:
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


def has_duplicate_topics(articles: list[dict]) -> bool:
    stop={'한국','정부','발표','진행','대책','지원','보도','관련','국민','강화','이날',
          '논의','추진','개최','새로운','확대','예정','정책','주요','오늘','사실'}
    titles=[]
    for item in articles:
        words=set(re.findall(r'[가-힣A-Za-z]{2,}', item.get('headline','')+' '+item.get('title','')))
        titles.append({x for x in words if x not in stop})
    for a in range(len(titles)):
        for b in range(a+1,len(titles)):
            left,right=titles[a],titles[b]
            if left and right and len(left & right) >= 3 and len(left & right)/min(len(left),len(right)) >= .7:
                return True
    return False


def build_news() -> tuple[list[dict],list[dict]]:
    general=write_verified_news(collect_candidates(GENERAL_CATEGORIES),medical=False)
    med=write_verified_news(collect_candidates(MEDICAL_CATEGORIES),medical=True)
    return general, med
