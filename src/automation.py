"""확정 원고 한 벌 → 동일 원고 PNG 카드 2장 → 출처 포함 공개 웹페이지."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import html
import json
import os
import argparse
import re
from zoneinfo import ZoneInfo

import requests

from .sources import weather_today, market_data
from .editorial import build_news, PublicationQualityError
from .render import render_morning, render_medical
from .edition import load as load_edition, seal, verify as verify_edition

KST = ZoneInfo('Asia/Seoul')
ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'


def _clean_editorial(headline: str, summary: str, source: str = '') -> tuple[str, str]:
    """게시 전 반복 문장/매체명 제거. 사실을 새로 창작하지 않는다."""
    import re
    from difflib import SequenceMatcher
    headline = re.sub(r'\s+', ' ', str(headline or '')).strip()
    summary = re.sub(r'\s+', ' ', str(summary or '')).strip()
    if source:
        suffix = r'\s*(?:-|·|\|)\s*' + re.escape(source) + r'\s*$'
        headline = re.sub(suffix, '', headline).strip()
        summary = re.sub(suffix, '', summary).strip()
    # 타이틀을 요약문 시작에 그대로 다시 적는 경우 제거
    if summary.startswith(headline) and headline:
        summary = summary[len(headline):].lstrip(' :.,-–·')
    # 내용이 사실상 같은 문장뿐이면 빈 본문으로 처리. 허구의 설명은 추가하지 않는다.
    normalize = lambda txt: re.sub(r'[^가-힣A-Za-z0-9]', '', txt).lower()
    h, b = normalize(headline), normalize(summary)
    if h and b:
        ratio = SequenceMatcher(None, h, b).ratio()
        if ratio > 0.74 and len(b) < len(h) * 1.55:
            summary = ''
    return headline, summary


def summarise(articles: list[dict]) -> list[dict]:
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key or os.environ.get('RUN_DEMO') == '1':
        for article in articles:
            title, summ = _clean_editorial(article['title'], article.get('snippet') or '', article.get('source') or '')
            article['headline'], article['summary'] = title, summ
        return articles
    data = [{'idx': i, 'category': a['category'], 'title': a['title'], 'date': a['date'],
             'source': a['source'], 'snippet': a['snippet']}
            for i, a in enumerate(articles)]
    prompt = (
        '당신은 실제 고객에게 전달하는 한국어 아침 카드뉴스 편집자입니다. '
        '제공한 RSS 제목/스니펫만 근거로 삼고 그 밖의 사실·수치·사건·정책 변경을 절대 만들지 마세요. '
        'headline은 35~50자 이내로 핵심 사실을 담고, summary는 headline을 다른 말로 반복하지 말고 '
        '제공된 추가 사실만 사용해 1~2개의 자연스러운 완결 문장으로 작성하세요. '
        '스니펫에 추가 사실이 없다면 summary를 빈 문자열로 두세요. '
        'summary에 언론사명, 출처, 기사 제목 또는 기사 날짜를 나열하지 마세요. '
        '보험·의료의 경우 법안/검토/확정/시행과 연구/임상/허가/급여를 구분하고 '
        '시행일이 확인되지 않았다면 임의로 기입하지 마세요. '
        '카드뉴스의 감성은 차분하고 신뢰감 있는 뉴스체이며 너무 짧은 문장 나열을 피하세요. '
        '반드시 {"items":[{"idx":0,"headline":"...","summary":"..."}]} 구조의 JSON 객체만 반환하세요.\n'
        + json.dumps(data, ensure_ascii=False)
    )
    url = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent'
    try:
        res = requests.post(url, headers={'x-goog-api-key': key}, json={
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {'responseMimeType': 'application/json', 'temperature': 0.05}
        }, timeout=55)
        res.raise_for_status()
        raw = res.json()['candidates'][0]['content']['parts'][0]['text']
        output = json.loads(raw)['items']
        summaries = {int(a['idx']): a for a in output if isinstance(a, dict) and 'idx' in a}
        for i, article in enumerate(articles):
            result = summaries.get(i, {})
            title, summ = _clean_editorial(
                str(result.get('headline') or article['title']),
                str(result.get('summary') or ''), article.get('source') or '')
            article['headline'], article['summary'] = title, summ
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
        print('AI 요약 실패: 추가 사실이 확인되지 않으면 문장을 반복하지 않습니다. (' + type(exc).__name__ + ')')
        for article in articles:
            title, summ = _clean_editorial(article['title'], article.get('snippet') or '', article.get('source') or '')
            article['headline'], article['summary'] = title, summ
    return articles


def demo_input():
    """실제 발표자료의 날짜가 명시된 편집 시연. 데모 배지는 제거하지 않는다."""
    general = [
        ('정치','대통령, 16~19일 아세안·APEC 정상회의 참석',
         '청와대는 대통령이 16일 필리핀에서 한·아세안 정상회의에 참석하고, 이어 중국 선전에서 APEC 정상회의 일정을 소화한다고 발표했습니다. 핵심광물 공급망과 초국가 범죄 대응 협력이 의제로 제시됐습니다.'),
        ('경제','금융위, 기업가치·소액주주 보호 방안 논의',
         '금융위는 13일 한국거래소에서 자본시장 정책 간담회를 개최했습니다. 전문가들은 저평가 기업의 주주 보호와 M&A 가격 산정 개선, 의무공개매수 도입 등을 제안했으며 확정된 정책과는 구별해야 합니다.'),
        ('사회','겨울 대설·한파 대책기간 15일 시작',
         '행정안전부는 11월 15일부터 내년 3월 15일까지 겨울철 자연재난 대책기간을 운영합니다. 관계기관은 노후주택·비닐하우스 등 적설 취약시설과 제설 사각지대를 점검하고 수능 대비책도 마련합니다.'),
        ('국제','EU 정상들, 더블린에서 AI 경쟁력 논의',
         '유럽연합 정상들이 13일 더블린에서 첫 AI 전용 정상회의를 열어 투자 재원과 규제, 안전 문제를 논의합니다. 반도체 생산 확대 목표와 AI 대형 인프라 투자 지연도 주요 과제로 거론됩니다.'),
        ('생활/문화','서울·대전 등에서 13~15일 가을 행사',
         '13일부터 15일까지 서울 aT센터에서는 우리술 대축제, 대전에서는 누들대전축제가 열립니다. 주말 방문객은 행사별 정확한 장소와 운영시간, 입장 조건을 확인해 이용할 수 있습니다.'),
    ]
    med = [
        ('건강보험','정부24에서 잠복결핵 확인서 발급',
         '질병관리청과 행정안전부는 11월 12일부터 정부24에서 잠복결핵감염 검진확인서 발급과 감염병 신고 내역 조회를 제공한다고 밝혔습니다. 일부 질병 관련 서류를 받기 위해 보건소를 직접 찾는 불편을 줄이는 조치입니다.'),
        ('보험제도','보험대리점 초년도 수수료 상한 확대',
         '금융위원회가 발표한 보험 판매수수료 개편안에 따라 7월부터 대리점(GA)에도 초년도 수수료 1,200% 한도가 적용됐습니다. 대형 GA는 상품 비교설명 과정에서 수수료 등급과 순위를 안내하도록 규정이 강화됐습니다.'),
        ('보건정책','겨울철 감염병 대응, 부처 간 공동 연구 추진',
         '질병관리청 국립보건연구원과 복지부·과기정통부는 13일 감염병 치료제 연구 성과교류회를 엽니다. AI 약물탐색과 mRNA 항체치료 연구, 병합치료제 등 4개 주제를 공유하지만 이는 연구 성과이며 임상 허가를 뜻하지 않습니다.'),
        ('건강정보','질병청, 국가 독감 예방접종 정상 진행 설명',
         '질병관리청은 11월 11일 국가 인플루엔자 예방접종이 정상적으로 진행되고 있다고 설명했습니다. 일부 민간 의료기관에서 백신 구매에 어려움을 겪는 사례가 있지만, 이를 국가예방접종 전체의 공급 차질로 보기는 어렵다고 밝혔습니다.'),
    ]
    mk=lambda row:{'category':row[0],'headline':row[1],'title':row[1], 'summary':row[2],
                   'source':'사실기반 시연','date':'2026-11-13','url':''}
    return list(map(mk,general)),list(map(mk,med))


def page(date: str, articles: list[dict], med: list[dict], weather: dict, market: dict, checked: str):
    """카드 2장의 원본 링크 + 접을 수 있는 근거자료. 매체명은 카드 이미지에 넣지 않는다."""
    def items(arr):
        return '\n'.join(f'<li><a target="_blank" rel="noopener noreferrer" href="{html.escape(a["url"], quote=True)}">'
                         f'{html.escape(a.get("category", ""))} · {html.escape(a.get("title", ""))}</a> '
                         f'({html.escape(a.get("source", ""))}, {html.escape(a.get("date", ""))})</li>'
                         for a in arr if a.get('url'))
    met = []
    for key, entry in market.items():
        if isinstance(entry, dict) and entry.get('source_url'):
            met.append(f'<li>{html.escape(key)} ({html.escape(entry.get("date", ""))}) · '
                       f'<a href="{html.escape(entry["source_url"], quote=True)}" target="_blank">기준 자료</a></li>')
    css = '<style>body{background:#eef2f4;color:#193047;font-family:sans-serif;max-width:920px;margin:auto;padding:20px}img{display:block;width:100%;max-width:640px;margin:12px auto;border-radius:20px}a{color:#215c8a;word-break:break-all}li{margin:9px 0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:20px}.cards img{max-width:100%}details{background:white;border-radius:14px;padding:18px;margin:15px 0}small{color:#64768c}</style>'
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>이보람의 카드뉴스 {date}</title>{css}</head><body>'
            f'<h1>이보람의 아침 카드뉴스 · {date}</h1><small>자료 확인 {checked} (KST) · 공유용 카드</small>'
            '<div class="cards"><a href="morning.png"><img src="morning.png" alt="아침뉴스 원본"></a>'
            '<a href="medical.png"><img src="medical.png" alt="보험·의료 브리핑 원본"></a></div>'
            '<details><summary>기사 원문과 수치 기준 확인하기</summary>'
            f'<h2>아침뉴스</h2><ul>{items(articles)}</ul><h2>보험·의료 브리핑</h2><ul>{items(med)}</ul>'
            f'<h2>시세 기준</h2><ul>{"".join(met)}</ul>'
            f'<p>날씨 참고 예보: <a href="{html.escape(weather.get("source_url", "https://open-meteo.com/"), quote=True)}">확인 자료</a> (기상청 공식 예보 아님). '
            '수치는 기준일과 제공처에 따라 다를 수 있으며 실제 금 거래 견적과는 차이가 있습니다.</p></details>'
            '</body></html>')


def main(*, edition_date: str | None = None):
    now = datetime.now(KST)
    date = now.strftime('%Y-%m-%d')
    if edition_date is not None:
        if os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch':
            raise RuntimeError('날짜 지정 제작은 수동 테스트 실행에서만 허용합니다.')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', edition_date):
            raise RuntimeError('테스트 원고 날짜 형식이 잘못됐습니다.')
        if datetime.strptime(edition_date, '%Y-%m-%d').date() > now.date():
            raise RuntimeError('미래 날짜의 원고를 테스트할 수 없습니다.')
        date = edition_date
        load_edition(ROOT, date)  # explicit dated tests never generate substitute stories
    checked = now.strftime('%H:%M')
    demo = os.environ.get('RUN_DEMO') == '1'
    if demo:
        # 데모에서 2026-11-13에 확인한 발표자료를 재사용하므로 발행일도 고정.
        date, checked = '2026-11-13', '시안'
    folder = DOCS / ('demo' if demo else date)
    folder.mkdir(parents=True, exist_ok=True)
    if demo:
        # 레이아웃 테스트 전용 데이터: 이미지에 '디자인 시험용'이 표시되며
        # 실제 기사·시세를 뜻하지 않는다. 카카오 전송·고객용 공개 발행 금지.
        general, medical = demo_input()
        medical.append({
            'category': '건강정보', 'headline': '디자인 검증용 다섯 번째 기사',
            'title': '디자인 검증용 다섯 번째 기사',
            'summary': '해당 문장은 실제 발표를 전달하지 않습니다. 오직 다섯 번째 카드의 공간과 글자 배치가 바르게 동작하는지 확인하는 테스트 문장입니다.',
            'source': '디자인 시험용', 'date': '2026-11-13', 'url': ''})
        weather = {
            'source': '디자인 시험용',
            'narrative': '이 날씨는 실제 기상예보가 아닌 편집 시연입니다. 실제 발행에서는 해당 날짜의 날씨만 새로 확인하여 문장으로 작성합니다.',
            'cities': {name: {'lo': 0, 'hi': 0} for name in ('서울', '부산', '대구', '광주')},
        }
        day = '2026-11-13'
        market = {
            'KOSPI': {'value': 0, 'change': 0, 'date': day},
            'KOSDAQ': {'value': 0, 'change': 0, 'date': day},
            'USD/KRW': {'value': 0, 'date': day},
            '휘발유': {'value': 0, 'date': day},
            '경유': {'value': 0, 'date': day},
            '순금 24K 1돈(살 때/팔 때)': {'buy': 0, 'sell': 0, 'date': day},
        }
    else:
        # A supplied, approved manuscript takes precedence. If preparation is
        # interrupted or unavailable, keep the established verified news build
        # working. A recovery run reuses the sealed manuscript, never reselects.
        if (ROOT / 'editions' / f'{date}.json').is_file():
            edition = load_edition(ROOT, date)
        elif (folder / 'publication.json').is_file():
            verify_edition(ROOT, date)
            edition = json.loads((folder / 'edition.json').read_text(encoding='utf-8'))
        else:
            general, medical = build_news()
            edition = {'date': date, 'checked': checked, 'articles': general,
                       'medical': medical, 'weather': weather_today(),
                       'market': market_data(), 'origin': 'verified_pipeline'}
        checked = edition['checked']
        general, medical = edition['articles'], edition['medical']
        weather, market = edition['weather'], edition['market']
    render_morning(folder / 'morning.png', date, checked, general, weather, market, demo)
    render_medical(folder / 'medical.png', date, checked, medical, demo)
    (folder / 'index.html').write_text(page(date, general, medical, weather, market, checked), encoding='utf-8')
    if not demo:
        report = {'date': date, 'checked': checked, 'articles': general, 'medical': medical, 'weather': weather, 'market': market}
        (folder / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        seal(folder, edition)
    if not demo and edition_date is None:
        (DOCS / 'index.html').write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url='+date+'/">'
                                  '<a href="'+date+'/">오늘의 카드뉴스 보기</a>', encoding='utf-8')
    print('완료:', folder / 'morning.png', folder / 'medical.png')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--edition-date', help='수동 테스트용 확정 원고 날짜')
    main(edition_date=parser.parse_args().edition_date)

