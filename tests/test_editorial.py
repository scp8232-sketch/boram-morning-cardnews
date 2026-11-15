"""실제 고객에게 보낼 수 없는 추상/반복/미검증 문장을 자동 발행하지 않는지 검증."""
from datetime import date
import pytest
from src import editorial


def item(head,summary,content,proofs=None):
    return {'headline':head,'summary':summary,'evidence': proofs or [content[:55],content[58:135]]}


@pytest.mark.parametrize('headline,summary', [
    ('정치 주요 정책의 추진 일정과 향후 논의 방향', '정부 발표 이후 관련 논의가 이어지고 있습니다. 세부 일정과 시행 여부는 공식 발표를 통해 구분할 필요가 있습니다.'),
    ('국제사회 주요 현안 관련 협의 이어져', '주요 국가들은 현안 조율을 위한 접촉을 이어가고 있습니다. 실제 합의 여부와 후속 일정은 추가 발표를 통해 확인해야 합니다.'),
    ('보험제도 관련 정책 개선 방향', '보험 가입자 보호를 위한 관련 논의가 진행되고 있습니다. 내용이 정해지는 대로 추가 발표를 확인하면 좋습니다.'),
])
def test_empty_news_rejected(headline,summary):
    ok,why=editorial._check_details(item(headline,summary,'아주 긴 ' * 90),'아주 긴 ' *90)
    assert not ok


def test_verified_concrete_details_pass():
    content=(
        '금융위원회는 11월 13일 한국거래소에서 자본시장 정책 간담회를 개최한다. '
        '이번 간담회에서는 기업가치 저평가와 M&A 과정에서의 소액주주 보호 대책을 전문가들이 제안한다. '
        '정부는 논의 내용을 수렴해 추후 자본시장 정책에 반영할 계획이다. '
        '금융위원회 설명에 따르면 PBR 1 미만 기업이 코스피 560개사와 코스닥 877개사다. '
    )
    headline='금융위, 13일 자본시장 정책 간담회 개최'
    summary=('금융위는 한국거래소에서 소액주주 보호와 저평가 기업의 가치 제고 방안을 논의했습니다. '
             '전문가들은 의무공개매수 등 개선안을 제안했으며, 아직 확정된 제도는 아닙니다.')
    content+='전문가들은 의무공개매수 등 개선안을 제안했으며 아직 제도 확정 전이다.'
    x=item(headline,summary,content,[
        '금융위원회는 11월 13일 한국거래소에서 자본시장 정책 간담회를 개최한다.',
        '전문가들은 의무공개매수 등 개선안을 제안했으며 아직 제도 확정 전이다.'])
    ok, why=editorial._check_details(x,content)
    assert ok,why


def test_fake_unquoted_statistics_fail():
    evidence='금융위원회는 11월 13일 상장기업 간담회를 개최했다고 발표했다. 추가로 장기적인 시장 개혁 방향을 제시했다.'*4
    x=item('금융위, 상장기업 간담회에서 시장 개선 논의',
        '정부는 한국거래소에서 정책 간담회를 열고 소액주주 보호와 시장 개선에 관한 전문가 의견을 청취했습니다. 새로운 제도가 확정된 것은 아니지만, 9999개 기업이 대상으로 지정됐습니다.',
        evidence,[evidence[:55],evidence[58:130]])
    ok, why=editorial._check_details(x,evidence)
    assert not ok
    assert '원문에 없는 숫자' in why


def test_unreadable_link_rejected():
    assert not editorial.valid_link('http://localhost:8989/secrets')
    assert not editorial.valid_link('https://127.0.0.1/report')
    assert editorial.valid_link('https://www.yna.co.kr/view/AKR20261113000000000')


def test_novalid_article_pipeline_stops(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','fake-key')
    categories={k:[{'candidate_id':k, 'category':k,'url':'https://example.org/a','content':'근거'*200,
                    'title':'정책','date':'2026-11-13','source':'공식기관'}] for k in editorial.GENERAL_CATEGORIES}
    monkeypatch.setattr(editorial,'_call_gemini',lambda key,items,cats:{'items':[]})
    with pytest.raises(editorial.PublicationQualityError,match='검증 미통과'):
        editorial.write_verified_news(categories,medical=False)


def test_two_evidences_required():
    s='어제 오후 한국거래소에서는 자본시장 정책 간담회가 열렸다. 주요 기관의 논의에서는 소액주주 보호방안과 M&A 가격공정성에 관해 대화를 나눴다.'*4
    x=item('금융당국, 자본시장 정책 간담회 개최',
        '금융위는 한국거래소에서 기업가치 제고와 주주 보호방안을 논의했습니다. 관계자는 저평가 개선과 제도 준비에 집중하고 있다고 설명했지만, 시행이 확정된 것은 아닙니다.',s,[s[0:55]])
    assert not editorial._check_details(x,s)[0]


def test_direct_rss_parsing():
    xml=b'''<rss><channel><item><title>Actual title with two named institutions</title><link>https://www.yna.co.kr/view/AKR123</link><pubDate>Fri, 13 Nov 2026 09:00:00 +0900</pubDate><description>Report details</description></item></channel></rss>'''
    row=editorial.parse_feed(xml)[0]
    assert row['date']=='2026-11-13'
    assert 'yna.co.kr' in row['url']


def test_short_news_is_regenerated_without_relaxing_quality(monkeypatch):
    """회귀검사: 기존 11/15 장애(짧은 기사 설명)가 다시 발행 중단을 일으키지 않게 한다."""
    monkeypatch.setenv('GEMINI_API_KEY','unit-test-key')
    parts=[
        '담당 기관은 지역별 신청 절차와 접수 방식을 구체적으로 발표했다.',
        '현장 접수 창구와 온라인 접수 창구를 별도로 운영한다고 밝혔다.',
    ]
    good_summary=('담당 기관은 지역별 신청 방법을 나누고 현장 창구와 온라인 접수 절차를 구분해 운영한다고 설명했습니다. '
                  '접수 방식을 구체적으로 발표하면서 대상자들이 이용할 수 있는 행정 절차를 함께 공개했습니다.')
    assert 70 <= len(good_summary) <= 125
    candidates={}
    for cat in editorial.GENERAL_CATEGORIES:
        candidates[cat]=[{'candidate_id':cat,'category':cat,'title':cat+' 분야 행정 조치 안내',
                          'date':'2026-11-15','url':'https://example.com/'+cat,
                          'source':'검사원문',
                          'content':'해당 분야의 공식 발표 전문입니다. '*20+parts[0]+' '+parts[1]}]
    def make_item(cat, summary=good_summary):
        return {'category':cat,'candidate_id':cat,
                'headline':cat+' 분야 담당 기관이 새로운 행정 조치를 발표했습니다',
                'summary':summary,'evidence':parts}
    calls=[]
    def fake_model(key, rows, categories, repair_notes=None):
        calls.append((categories,repair_notes))
        if repair_notes:
            return {'items':[make_item(categories[0])]}
        return {'items':[make_item(cat,'관련 내용이 발표되었습니다.' if cat=='정치' else good_summary)
                         for cat in categories]}
    monkeypatch.setattr(editorial,'_call_gemini',fake_model)
    monkeypatch.setattr(editorial,'has_duplicate_topics',lambda items:False)
    result=editorial.write_verified_news(candidates)
    assert len(result)==5
    assert len(calls)==2
    assert calls[1][0]==('정치',)
    assert '길이' in calls[1][1]['정치']


def test_unverifiable_news_remains_blocked_after_one_retry(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','unit-test-key')
    candidates={cat:[{'candidate_id':cat,'category':cat,
                    'title':cat+' 분야 원문', 'date':'2026-11-15',
                    'url':'https://example.com/foo','source':'원문',
                    'content':'확인된 원문 내용을 공개합니다. '*30}]
                for cat in editorial.GENERAL_CATEGORIES}
    attempts=[]
    def no_facts(key,rows,categories,repair_notes=None):
        attempts.append(categories)
        return {'items':[]}
    monkeypatch.setattr(editorial,'_call_gemini',no_facts)
    with pytest.raises(editorial.PublicationQualityError,match='재시도 후'):
        editorial.write_verified_news(candidates)
    assert len(attempts)==6  # 최초 일괄 1회 + 미검증 다섯 분야의 각 1회
