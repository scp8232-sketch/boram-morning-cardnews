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
            if len(normalize(content))<260: continue
            info={**entry,'category':category,'content':content}
            info['candidate_id']=hashlib.sha256(entry['url'].encode()).hexdigest()[:12]
            enriched.append(info)
            if len(enriched)>=max_per_category+2:break
        enriched.sort(key=lambda x:candidate_score(x,today),reverse=True)
        out[category]=enriched[:max_per_category]
        seen_urls.update(x['url'] for x in out[category])
    return out


def _check_details(item:dict, evidence_source:str) -> tuple[bool,str]:
    headline=compact(item.get('headline',''))
    summary=compact(item.get('summary',''))
    if not (18<=len(headline)<=56): return False, '제목이 너무 짧거나 길음'
    if not (70<=len(summary)<=125): return False, '설명은 70~125자로, 확인된 사실을 2~3개 포함해야 함'
    if not re.search(r'[가-힣]',headline+summary): return False,'한글 뉴스 문장이 아님'
    if any(x in headline+summary for x in BANNED_FILLER): return False,'공허한 상투적 표현'
    if '…' in headline or '...' in headline: return False,'제목이 잘림'
    h,b=normalize(headline),normalize(summary)
    if b.startswith(h) or (h and b.startswith(h[:min(25,len(h))])):
        return False,'제목을 본문에 재진술'
    evid=item.get('evidence',[])
    if not isinstance(evid,list) or len(evid)<2:return False,'근거문장 2개 미제출'
    normalized=normalize(evidence_source)
    proofs=[]
    for e in evid[:4]:
        e=compact(e)
        en=normalize(e)
        if len(en)<14 or len(en)>190 or en not in normalized:
            continue
        if en not in proofs: proofs.append(en)
    if len(proofs)<2:return False,'원문과 정확히 일치하는 독립 근거가 2개 미만'
    # AI가 존재하지 않는 통계·날짜를 새로 만들어내는 기본적인 오류 방지.
    numbers=lambda s:set(re.findall(r'\d+(?:[,.]\d+)*',s))
    missing=numbers(headline+' '+summary)-numbers(evidence_source)
    if missing: return False, f'원문에 없는 숫자 {sorted(missing)[:3]}'
    if len(normalize(summary))<=len(normalize(headline))*1.3:
        return False,'본문이 제목을 충분히 넘어서는 새로운 사실을 제공하지 않음'
    return True,''


def validate_article(item:dict, source:dict) -> tuple[bool,str]:
    if item.get('candidate_id')!=source.get('candidate_id'):return False,'선택 후보와 근거 자료 불일치'
    return _check_details(item,source.get('content',''))


def _call_gemini(key:str, input_payload:list[dict], needed_categories:tuple[str,...]) -> dict:
    schemas=[{'category':a['category'],'candidate_id':a['candidate_id'],
            'title':a['title'],'published':a['date'],'body':a['content'][:4000]}
            for a in input_payload]
    instruction='''당신은 한국어 뉴스 편집자입니다. 고객에게 전달할 뉴스이므로 아래 원문에서 확인되는 사실만 사용하세요.
각 category별로 근거가 가장 충실하고 중요한 기사 1개를 선택하며, 적절한 기사가 없으면 그 category는 반환하지 마세요.
각 뉴스의 제목은 누가 무엇을 어떻게 했는지 드러나야 하며, summary는 제목을 반복하지 않고 새로운 사실 2~3개를 연결된 2문장(약 85~115자)으로 자세히 설명해야 합니다.
무조건 ‘누가/무엇을/언제/대상/구체적인 수치 또는 실행 조치’ 중 최소 3개 정보가 포함되어야 합니다.
예: 제목 ‘금융위, 자본시장 간담회 개최’; 본문 ‘금융위는 13일 한국거래소에서 간담회를 열고 저평가 상장사 문제와 M&A 주주 보호 대책을 다뤘습니다. 참석 전문가들이 제안한 대책은 확정·시행된 제도와 구별해야 합니다.’
‘논의가 이어집니다’, ‘추가 발표를 확인해야 합니다’, ‘중요합니다’, ‘관심이 높습니다’처럼 새 사실이 없는 문장은 절대 금지합니다.
출처명·신문사명·기사 날짜를 본문 아래에 쓰지 마세요. 헤드라인을 본문 첫머리에 다시 붙이지 마세요.
정치·의료 정책에서 제안/검토/발표/확정/시행을 혼동하지 마세요. 신약은 연구/비임상/임상/허가/급여를 구분하세요.
대상 기사 본문의 텍스트에서 **그대로 복사한 서로 다른 두 문장 조각**을 evidence 배열에 넣으세요. 각 조각은 최소 14자, 80자 이내로, 제목이 아닌 원문 본문에 존재해야 합니다.
반드시 {"items":[{"category":"...","candidate_id":"원문 후보 id","headline":"...","summary":"...","evidence":["원문 그대로 한 부분", "원문 그대로 다른 부분"]}]} JSON만 출력하세요.
요청 카테고리: ''' + ', '.join(needed_categories)
    url='https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent'
    response=requests.post(url,headers={'x-goog-api-key':key},json={
      'contents':[{'parts':[{'text':instruction+'\n자료(JSON): '+json.dumps(schemas,ensure_ascii=False)}]}],
      'generationConfig':{'responseMimeType':'application/json','temperature':0.05, 'maxOutputTokens':5000}
    },timeout=95)
    response.raise_for_status()
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
    try:res=_call_gemini(key,flat,intended)
    except (requests.RequestException,ValueError,KeyError,IndexError,TypeError) as exc:
        raise PublicationQualityError('AI 근거 기반 요약 실패: '+type(exc).__name__) from exc
    if not isinstance(res,dict) or not isinstance(res.get('items'),list):
        raise PublicationQualityError('AI가 검증 가능한 JSON 형식을 제공하지 않았습니다.')
    sources={a['candidate_id']:a for a in flat}
    approved={}
    rejected=[]
    for item in res['items']:
        if not isinstance(item,dict):continue
        cat=item.get('category')
        if cat not in intended or cat in approved:continue
        s=sources.get(str(item.get('candidate_id','')))
        if not s or s['category']!=cat:
            rejected.append((cat,'출처 후보 ID 오류'));continue
        ok,reason=validate_article(item,s)
        if not ok:
            rejected.append((cat,reason));continue
        approved[cat]={
           'category':cat,'title':s['title'],'headline':compact(item['headline']),
           'summary':compact(item['summary']),'date':s['date'],
           'source':s['source'],'url':s['url'],
           'fact_proofs': [{'quote':compact(quote)[:80]} for quote in item['evidence'][:2]],
           'fact_content_hash':hashlib.sha256(s['content'].encode()).hexdigest()[:16],
        }
    if not medical:
        missing=[cat for cat in intended if cat not in approved]
        if missing:
            raise PublicationQualityError('아침뉴스 검증 미통과: '+', '.join(missing)+'. '+repr(rejected))
    elif len(approved)<5:
        raise PublicationQualityError('보험·의료 브리핑 5건 모두 검증 필요: '+repr(rejected))
    result=[approved[cat] for cat in intended if cat in approved][:5]
    # 다른 카테고리에서 같은 사건을 중복 선별한 경우에도 발행하지 않는다.
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
