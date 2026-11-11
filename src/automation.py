"""뉴스 가져오기 → Gemini 보수적 요약 → PNG 카드 2장 → 출처 포함 공개 웹페이지."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import html
import json
import os
from zoneinfo import ZoneInfo

import requests

from .sources import NEWS_QUERIES, MEDICAL_QUERIES, choose_articles, weather_today, market_data
from .render import render_morning, render_medical

KST = ZoneInfo('Asia/Seoul')
ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'


def summarise(articles: list[dict]) -> list[dict]:
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key or os.environ.get('RUN_DEMO') == '1':
        for article in articles:
            article['headline'] = article['title'][:50]
            article['summary'] = article.get('snippet') or '기사 제목과 발표일을 확인했습니다. 세부 사항은 원문에서 확인해 주세요.'
        return articles
    data = [{'idx': i, 'title': a['title'], 'date': a['date'], 'source': a['source'], 'snippet': a['snippet']}
            for i, a in enumerate(articles)]
    prompt = (
        '한국어 아침뉴스 카드뉴스용 요약 편집자입니다. 다음은 외부 RSS에서 실제로 수집한 제목과 스니펫입니다. '
        '이 자료에 직접 있는 사실만 사용하세요. 확인되지 않은 수치·배경·인과·전망·시행일을 만들지 마세요. '
        '발표/검토/확정/시행, 연구/임상/허가/급여를 혼동하지 마세요. '
        '각 기사에 대해 idx, headline(40자 이내), summary(2문장, 115자 이내)를 작성하세요. '
        'summary는 문장 3개를 끊어 나열하지 말고 흐름이 연결되는 내용은 자연스럽게 이어 쓰세요. '
        '원문에 없는 세부 정보는 적지 말고 확인이 필요한 점은 원문 확인이라고 표현하세요. '
        '반드시 {"items":[{"idx":0,"headline":"...","summary":"..."}]} JSON 객체만 반환하세요.\n'
        + json.dumps(data, ensure_ascii=False)
    )
    url = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent'
    try:
        res = requests.post(url, headers={'x-goog-api-key': key}, json={
            'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {'responseMimeType': 'application/json', 'temperature': 0.1}
        }, timeout=55)
        res.raise_for_status()
        raw = res.json()['candidates'][0]['content']['parts'][0]['text']
        output = json.loads(raw)['items']
        summaries = {int(a['idx']): a for a in output if isinstance(a, dict) and 'idx' in a}
        for i, article in enumerate(articles):
            result = summaries.get(i, {})
            article['headline'] = str(result.get('headline') or article['title'])[:80]
            article['summary'] = str(result.get('summary') or article.get('snippet') or '원문을 확인해 주세요.')[:240]
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
        print('AI 요약 실패: 기사 제목 기반 요약으로 대체합니다. (' + type(exc).__name__ + ')')
        for article in articles:
            article['headline'] = article['title']
            article['summary'] = article.get('snippet') or '자세한 내용은 원문을 확인해 주세요.'
    return articles


def demo_input():
    headlines = ['국내 주요 정책 일정과 발표 점검', '경제 지표 발표에 따른 시장 동향', '사회 안전과 제도 개선 움직임',
                 '국제 사회 협력과 외교 현안', '문화 행사와 생활 소식']
    med = ['건강보험 관련 주요 제도 확인', '민영보험 제도 변경 사항 점검', '보건의료 정책과 안내 사항',
           '새로운 의료기술 개발 동향', '예방과 건강 관련 공공 정보']
    mk = lambda title, cat: {'category': cat, 'title': title, 'headline': title, 'date': '예시',
        'source': '데모 자료', 'url': '',
        'summary': '레이아웃 확인을 위한 가상 문장입니다. 실제 기사나 수치가 아니므로 뉴스로 사용하지 마세요.'}
    return [mk(t, c) for t, c in zip(headlines, NEWS_QUERIES)], [mk(t, c) for t, c in zip(med, MEDICAL_QUERIES)]


def page(date: str, articles: list[dict], med: list[dict], weather: dict, market: dict, checked: str):
    def items(arr):
        return '\n'.join(f'<li><a target="_blank" rel="noopener noreferrer" href="{html.escape(a["url"], quote=True)}">'
                         f'{html.escape(a.get("category", ""))} · {html.escape(a.get("title", ""))}</a> '
                         f'({html.escape(a.get("source", ""))}, {html.escape(a.get("date", ""))})</li>'
                         for a in arr if a.get('url'))
    common = '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
    css = '<style>body{background:#eef2f4;color:#193047;font-family:sans-serif;max-width:920px;margin:auto;padding:24px}img{display:block;width:100%;max-width:640px;margin:12px auto;border-radius:20px}a{color:#215c8a;word-break:break-all}li{margin:9px 0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}.cards img{max-width:100%}section{background:white;border-radius:16px;padding:18px;margin:15px 0}small{color:#64768c}</style>'
    content = (f'<!doctype html><html lang="ko"><head>{common}<title>이보람의 아침 카드뉴스 {date}</title>{css}</head><body>'
               f'<h1>이보람의 아침 카드뉴스 · {date}</h1><small>자료 확인 {checked} (KST). 업데이트 지연 가능.</small>'
               '<div class="cards"><a href="morning.png"><img src="morning.png" alt="아침뉴스"></a>'
               '<a href="medical.png"><img src="medical.png" alt="보험 의료 브리핑"></a></div>'
               f'<section><h2>일반 뉴스 출처</h2><ul>{items(articles)}</ul></section>'
               f'<section><h2>보험·의료 뉴스 출처</h2><ul>{items(med)}</ul></section>'
               '<section><h2>기준·주의</h2><p>뉴스: Google 뉴스 RSS에 표시된 기사·발행일 기준. 기사 본문을 검증하지 못한 세부 사항은 단정하지 않습니다.</p>'
               '<p>날씨: Open-Meteo 참고 예보(기상청 공식 예보 아님). 증시·환율: Yahoo Finance 참고시세(한국거래소/은행 공식 고시 아님). '
               '휘발유·경유·금 시세는 확인하지 못하면 값을 표시하지 않습니다. 6시 30분 도착은 보장되지 않습니다.</p></section>'
               '</body></html>')
    return content


def main():
    now = datetime.now(KST)
    date = now.strftime('%Y-%m-%d')
    checked = now.strftime('%H:%M')
    demo = os.environ.get('RUN_DEMO') == '1'
    folder = DOCS / ('demo' if demo else date)
    folder.mkdir(parents=True, exist_ok=True)
    if demo:
        general, medical = demo_input()
        weather = {'source': '데모 자료 (실제 예보 아님)', 'cities': {}}
        market = {}
    else:
        general = choose_articles(NEWS_QUERIES)
        medical = choose_articles(MEDICAL_QUERIES)
        weather = weather_today()
        market = market_data()
        if not general:
            raise RuntimeError('최신 뉴스 수집에 모두 실패하여 발행을 중단합니다. 가짜 뉴스를 대신 발행하지 않습니다.')
        general = summarise(general)
        medical = summarise(medical)
    render_morning(folder / 'morning.png', date, checked, general, weather, market, demo)
    render_medical(folder / 'medical.png', date, checked, medical, demo)
    (folder / 'index.html').write_text(page(date, general, medical, weather, market, checked), encoding='utf-8')
    if not demo:
        (DOCS / 'index.html').write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url='+date+'/">'
                                  '<a href="'+date+'/">오늘의 카드뉴스 보기</a>', encoding='utf-8')
    print('완료:', folder / 'morning.png', folder / 'medical.png')


if __name__ == '__main__':
    main()
