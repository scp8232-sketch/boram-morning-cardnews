"""Customer-focused morning-news selection rules (offline, deterministic)."""
from datetime import date, datetime
from zoneinfo import ZoneInfo
from src import editorial


def row(title, cat, body=None):
    return {'title': title, 'category': cat, 'date': '2026-11-17',
            'content': body or ('보도에서 확인된 중요한 정책 변화와 구체적 사실을 안내했습니다. '*20)}


def test_economy_priority_domestic_then_us_then_other():
    today = date(2026,11,17)
    domestic = row('코스피 급락, 국내 증시 변동성 확대', '경제')
    america = row('미국 증시 나스닥 하락, 연준 금리 주목', '경제')
    taiwan = row('대만 증시 자취안 지수 하락 마감', '경제')
    assert editorial.candidate_score(domestic,today)>editorial.candidate_score(america,today)
    assert editorial.candidate_score(america,today)>editorial.candidate_score(taiwan,today)


def test_lifestyle_prioritizes_daily_use_over_exhibition():
    today=date(2026,11,17)
    practical=row('대중교통 버스 요금 환급 신청 안내','생활/문화')
    gallery=row('미술관 전시 샤갈 작품 공개','생활/문화')
    assert editorial.candidate_score(practical,today)>editorial.candidate_score(gallery,today)


def test_photo_captions_lose_to_substantive_policy_article():
    today=date(2026,11,17)
    pic=row('한일 정상 악수하며 기념촬영 [뉴시스Pic]','정치')
    substantive=row('한일 정상 안보 협력 확대 합의','정치')
    assert editorial.candidate_score(substantive,today)>editorial.candidate_score(pic,today)


def test_mismatched_news_article_is_rejected():
    article={'candidate_id':'a','category':'사회',
             'title':'중수청 포렌식 시스템 구동 완료 전문 인력 확보',
             'content':'이재명 대통령이 수능 비상점검회의를 주재했다. 부정행위를 확인하고 엄정 대응을 지시했다. '*8}
    draft={'candidate_id':'a','headline':'대통령 수능 부정행위 점검회의 주재',
           'summary':'이재명 대통령이 수능 시험 부정행위에 대한 점검회의를 열었습니다. 관계자들에게 철저한 사전 대응과 사후 조사를 당부했습니다.'}
    ok,why=editorial.validate_article(draft,article)
    assert not ok and '주제' in why


def test_topic_matches_regular_report():
    assert editorial.topic_matches_title('국회 교육위원회 학교 안전 대책 의결',
                                          '국회가 학교 안전 대책을 의결했습니다.')


def test_rss_time_preserved_and_future_story_filtered(monkeypatch):
    as_of=datetime(2026,11,17,5,10,tzinfo=ZoneInfo('Asia/Seoul'))
    xml=b'''<rss><channel><item><title>Long published news about school education reforms</title><link>https://www.yna.co.kr/view/AKR123</link><pubDate>Tue, 17 Nov 2026 21:08:00 +0900</pubDate><description>Some details</description></item></channel></rss>'''
    parsed=editorial.parse_feed(xml)
    assert parsed[0]['published_at'].startswith('2026-11-17T21:08:00')
    monkeypatch.setattr(editorial,'feed_articles',lambda *args:parsed)
    monkeypatch.setattr(editorial,'_fetch_verified_entries',lambda rows,*args,**kw: [] if not rows else (_ for _ in ()).throw(AssertionError('Future news reached fetcher')))
    result=editorial.collect_candidates(('사회',),today=as_of.date(),as_of=as_of)
    assert result['사회']==[]


def test_rss_time_before_cutoff_is_accepted(monkeypatch):
    as_of=datetime(2026,11,17,5,10,tzinfo=ZoneInfo('Asia/Seoul'))
    obj={'title':'학교 교육 제도 안전 개선 정부 정책 발표','url':'https://www.yna.co.kr/view/AKR333',
         'date':'2026-11-17','published_at':'2026-11-17T04:30:00+09:00','source':'yna.co.kr'}
    monkeypatch.setattr(editorial,'feed_articles',lambda *args:[obj])
    monkeypatch.setattr(editorial,'_fetch_verified_entries',lambda rows,cat,seen_urls,**kw: [
        {**rows[0], 'category':cat,'content':'학교 안전 점검 제도 개선을 발표했다. '*25,'candidate_id':'x'}] if rows else [])
    result=editorial.collect_candidates(('사회',),today=as_of.date(),as_of=as_of)
    assert len(result['사회'])==1
