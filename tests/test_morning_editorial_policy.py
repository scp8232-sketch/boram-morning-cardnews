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


def test_suneung_ai_story_across_politics_and_society_is_same_event():
    a={'category':'정치','title':'여야, 수능 AI 부정행위 처벌강화 법안 발의',
       'headline':'수능 인공지능 부정행위 처벌 강화'}
    b={'category':'사회','title':'대통령 수능 비상점검 회의 부정행위 근절 강조',
       'headline':'수능 AI 부정행위 전수조사 지시'}
    assert editorial.same_news_event(a,b)
    assert editorial.has_duplicate_topics([a,b])


def test_different_education_stories_do_not_trigger_event_match():
    a={'category':'정치','title':'수능 AI 부정행위 법안 발의'}
    b={'category':'사회','title':'초등학교 돌봄교실 신청 확대'}
    assert not editorial.same_news_event(a,b)


def test_life_events_fall_behind_consumer_advice():
    event=row('서울문화재단 AI 예술교육 포럼 개최','생활/문화')
    daily=row('겨울철 난방비 환급 신청 기간 안내','생활/문화')
    assert editorial.editorial_priority(daily)>editorial.editorial_priority(event)


def test_duplicate_politics_society_replaced_with_second_society_candidate(monkeypatch):
    """End-to-end offline selection: same exam story cannot occupy two categories."""
    monkeypatch.setenv('GEMINI_API_KEY', 'test')
    categories = {}
    names = {
        '정치': '여야, 수능 AI 부정행위 처벌 강화 법안 발의',
        '경제': '코스피 지수 변동과 외환시장 동향 발표',
        '사회': '수능 인공지능 부정행위 전수조사 지시',
        '국제': '국제 해상물류 공급망 대응 정상 협력',
        '생활/문화': '버스 요금 환급 신청 제도 개선 안내',
    }
    for cat in editorial.GENERAL_CATEGORIES:
        categories[cat]=[{'category':cat, 'candidate_id':cat+'-0',
             'title':names[cat], 'url':'https://example.org/'+cat+'-0',
             'date':'2026-11-17','source':'test', 'content':'사실 근거를 확인하기 위한 독립된 내용입니다. '*30}]
    categories['사회'].append({'category':'사회', 'candidate_id':'사회-1',
        'title':'도로 안전시설 전면 점검 후 결과 발표',
        'url':'https://example.org/society-other', 'date':'2026-11-17',
        'source':'test','content':'서로 다른 도로 안전 기사 본문입니다. '*30})
    monkeypatch.setattr(editorial,'validate_article',lambda draft,src:(True,''))
    monkeypatch.setattr(editorial,'_verified_evidence',lambda draft,content:(['확인된 근거 1','확인된 근거 2'],''))
    def model(key, sources, requested,repair_notes=None):
        return {'items':[{'category':source['category'], 'candidate_id':source['candidate_id'],
              'headline':source['title'],'summary':'제목과 겹치지 않는 핵심 추가 사실을 상세히 확인했습니다.',
              'evidence_ids':['E01','E02']} for source in sources]}
    monkeypatch.setattr(editorial,'_call_gemini',model)
    result=editorial.write_verified_news(categories)
    assert len(result)==5
    assert result[2]['title']=='도로 안전시설 전면 점검 후 결과 발표'
    assert not editorial.has_duplicate_topics(result)
