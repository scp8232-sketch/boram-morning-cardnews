"""Regressions for medical category '0 valid article' failures on 2026-11-15."""
from datetime import date
from types import SimpleNamespace
import sys
from src import editorial


CONTENT = (
    '국민건강보험공단은 11월 11일 건강보험 본인부담금환급금 대상자의 조회와 신청을 안내했다. '
    '진료비 중 심사결과 기준을 초과하여 부담한 금액은 공단에서 환급받을 수 있다고 설명했다. '
    '대상자는 공단 누리집 또는 모바일 앱에서 환급금을 조회하고 신청할 수 있다고 밝혔다. '
    '건보공단은 우편과 전화상담을 통해 환급금 신청도 도울 예정이라고 덧붙였다. '
) * 3


def article(i, *, google=False, category='건강보험', day='2026-11-12'):
    host = 'news.google.com/rss/articles' if google else 'www.newsis.com/view'
    return {'title':f'{category} 환급금 신청방법과 대상자 안내 내용 {i}',
            'url':f'https://{host}/test-{i}', 'date':day,
            'source':'원문 뉴스', 'snippet':'건강보험 공단 보도자료 안내'}


def test_medical_source_prioritizes_real_article_over_google_links(monkeypatch):
    """The older version searched 12 newest Google links and returned zero.

    A direct publisher article must be checked even when many Google wrapper
    entries look more recent.
    """
    rows=[article(i,google=True,day='2026-11-15') for i in range(70)]
    rows += [article(99,google=False,day='2026-11-11')]
    monkeypatch.setattr(editorial,'feed_articles',lambda u: rows if 'news.google.com' in u else [])
    calls=[]
    def fetch(url):
        calls.append(url)
        return CONTENT if 'newsis.com' in url else ''
    monkeypatch.setattr(editorial,'fetch_fulltext',fetch)
    # No internet decode is needed if a verified direct link exists.
    monkeypatch.setattr(editorial,'_decode_google_rows',lambda rows,limit=14:(_ for _ in ()).throw(AssertionError('unneeded decoder')))
    out=editorial.collect_candidates(('건강보험',),today=date(2026,11,15),max_per_category=1)
    assert len(out['건강보험'])==1
    assert 'newsis.com' in out['건강보험'][0]['url']
    assert len(calls)==1


def test_google_decoder_only_returns_verified_publisher_links(monkeypatch):
    entry=article(1,google=True)
    fake=SimpleNamespace(decode_many=lambda urls:{entry['url']:'https://www.yna.co.kr/view/AKR123'})
    monkeypatch.setitem(sys.modules,'gnews_decoder',fake)
    out=editorial._decode_google_rows([entry])
    assert len(out)==1 and out[0]['url']=='https://www.yna.co.kr/view/AKR123'
    fake2=SimpleNamespace(decode_many=lambda urls:{entry['url']:'https://news.google.com/articles/abc'})
    monkeypatch.setitem(sys.modules,'gnews_decoder',fake2)
    assert editorial._decode_google_rows([entry])==[]


def test_long_candidate_pool_does_not_stop_after_twelve(monkeypatch):
    rows=[article(i,google=False) for i in range(18)]
    monkeypatch.setattr(editorial,'feed_articles',lambda url:rows if 'newsis.com/RSS/society.xml' in url else [])
    monkeypatch.setattr(editorial,'fetch_fulltext',lambda url:CONTENT if url.endswith('/test-16') else '')
    out=editorial.collect_candidates(('건강보험',),today=date(2026,11,15),max_per_category=1)
    assert len(out['건강보험'])==1
    assert out['건강보험'][0]['url'].endswith('test-16')


def test_article_body_jsonld_is_not_removed_before_extraction(monkeypatch):
    import json
    script='<script type="application/ld+json">'+json.dumps({'@type':'NewsArticle','articleBody':CONTENT},ensure_ascii=False)+'</script>'
    class R:
        url='https://www.newsis.com/view/test'
        headers={'Content-Type':'text/html; charset=utf-8'}
        text='<html><head>'+script+'</head><body><nav>메뉴</nav></body></html>'
        def raise_for_status(self):return None
    monkeypatch.setattr(editorial.requests,'get', lambda *args,**kwargs: R())
    assert editorial.fetch_fulltext('https://www.newsis.com/view/test')==editorial.compact(CONTENT)[:5200]


def test_insurance_sources_include_finance_and_wider_lookback():
    assert any('bank.xml' in url for url in editorial.FEEDS['보험제도'])
    assert any('society.xml' in url for url in editorial.FEEDS['건강보험'])
    assert editorial.is_recent('2026-11-04',max_days=16,now=date(2026,11,15))


def test_google_wrappers_are_decoded_before_article_read(monkeypatch):
    rows=[article(7,google=True)]
    monkeypatch.setattr(editorial,'feed_articles',lambda url:rows if 'news.google.com' in url else [])
    decoded={**rows[0],'url':'https://www.newsis.com/view/test-medical'}
    monkeypatch.setattr(editorial,'_decode_google_rows',lambda x,limit=14:[decoded])
    monkeypatch.setattr(editorial,'fetch_fulltext',lambda url:CONTENT if url==decoded['url'] else '')
    out=editorial.collect_candidates(('건강보험',),today=date(2026,11,15),max_per_category=1)
    assert len(out['건강보험'])==1
    assert out['건강보험'][0]['url']==decoded['url']
