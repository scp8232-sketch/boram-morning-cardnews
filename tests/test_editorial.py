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
    monkeypatch.setattr(editorial,'_call_gemini',lambda key,items,cats,repair_notes=None:{'items':[]})
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
    assert len(attempts)==6  # 1회 일괄 + 누락된 5개 분야를 각 1회 단독 검증


def test_passage_ids_grounded_in_actual_article():
    """AI chooses existing sentence IDs; it cannot make up precise quotations."""
    content=('금융위원회는 11월 13일 한국거래소에서 자본시장 정책 간담회를 개최했다. '
             '참석한 전문가들은 기업가치 저평가 문제와 소액주주 보호 제도의 개선 방안을 논의했다. '
             '간담회에서는 의무공개매수제도에 관한 여러 방안이 검토 대상에 포함됐다. '
             '금융위원회는 이날 제도의 확정과 실제 시행 여부를 발표하지 않았다. ')
    snippets=editorial.evidence_catalog(content)
    assert len(snippets)>=3, snippets
    news={'headline':'금융위, 자본시장 정책 간담회에서 소액주주 보호 논의',
          'summary':('금융위가 한국거래소에서 자본시장 정책 간담회를 열고 기업가치 저평가 문제와 소액주주 보호 방안을 다뤘습니다. '
                     '의무공개매수제도도 검토 대상에 포함됐지만 실제 시행은 확정하지 않았습니다.'),
          'evidence_ids':['E01','E02']}
    # Long strings are not silently cut off: ensure explicit limit and evidence
    assert len(news['summary'])<=125
    ok,why=editorial._check_details(news,content)
    assert ok,why
    cited,_=editorial._verified_evidence(news,content)
    assert cited==[snippets['E01'],snippets['E02']]


def test_fabricated_passage_id_fails_closed():
    content=('금융위원회는 11월 13일 한국거래소에서 자본시장 간담회를 개최했다고 설명했다. '
             '현장 참석자들은 기업가치 제고를 위한 정책 필요성을 논의했다고 밝혔다. '
             '관련 의견은 앞으로 별도로 검토할 예정이라고 덧붙였다. ')
    news={'headline':'금융위원회, 거래소에서 자본시장 간담회 개최',
          'summary':('금융위원회는 한국거래소에서 자본시장 간담회를 개최했습니다. 참석자들은 기업가치 제고를 위한 개선방안을 논의했으며 후속 검토가 필요하다는 의견을 전달했습니다.'),
          'evidence_ids':['E01','E99']}
    ok,reason=editorial._check_details(news,content)
    assert not ok and '없는 근거 문장 번호' in reason


def test_long_summary_only_removes_whole_trailing_sentence():
    first=('금융위원회가 자본시장 제도개선 간담회를 열고 소액주주 보호에 대한 여러 방안을 제시했습니다. '
           '기업가치 저평가 문제도 논의했습니다.')
    ending=' 이번 논의에서는 제안 단계의 제도를 확정된 시행 방침과 구분해야 한다는 설명을 덧붙였습니다. 아직 구체적 일정은 결정되지 않았습니다.'
    assert 70<=len(first)<=125 and len(first+ending)>125
    result=editorial._compact_long_summary({'summary':first+ending})
    assert result['summary'].startswith(first)
    assert 70 <= len(result['summary']) <= 125
    assert result['summary'].endswith('.')
    assert result['summary'] in (first, (first + ending).rsplit(' ', 5)[0]) or result['summary'] == (first + ' 이번 논의에서는 제안 단계의 제도를 확정된 시행 방침과 구분해야 한다는 설명을 덧붙였습니다.')


def test_model_receives_source_generated_ids_not_fake_quotes(monkeypatch):
    captured={}
    class Response:
        def raise_for_status(self):pass
        def json(self):return {'candidates':[{'content':{'parts':[{'text':'{"items":[]}'}]}}]}
    def fake_post(url, **kw):
        captured.update(kw)
        return Response()
    monkeypatch.setattr(editorial.requests,'post',fake_post)
    body=('국민건강보험공단은 보험료 환급금 관련 신청 절차를 공개했다고 발표했다. '
          '가입자는 공식 홈페이지와 모바일 앱에서 본인 인증을 거쳐 조회할 수 있다. '
          '일부 환급금은 신청 기한을 넘기면 소멸할 수 있어 기한을 확인하도록 안내했다.')
    result=editorial._call_gemini('test-key',[{'category':'건강보험','candidate_id':'x',
              'title':'국민건강보험공단 환급금 안내','date':'2026-11-15','content':body}],('건강보험',))
    assert result == {'items':[]}
    payload=captured['json']
    sent=payload['contents'][0]['parts'][0]['text']
    assert 'evidence_catalog' in sent
    assert 'E01' in sent and 'E02' in sent
    assert 'evidence_ids' in payload['generationConfig']['responseSchema']['properties']['items']['items']['required']
    assert 'test-key' not in sent


def test_evidence_catalog_rejects_single_short_repeated_chunk():
    assert editorial.evidence_catalog('짧은 안내입니다.') == {}
    assert editorial.evidence_catalog('동일한 공지 내용이 반복되는 문장입니다. '*5) == {}


def test_invalid_summary_number_cannot_pass_with_valid_ids():
    content=('금융위원회는 11월 13일 정책 간담회를 열고 기업가치 제고 방안을 논의했다. '
             '관련 전문가들은 소액주주 보호와 시장제도 개선 방향에 대한 의견을 제시했다. '
             '구체적인 후속 일정은 당일 별도로 확정되지 않았다고 담당자가 설명했다. ')
    x={'headline':'금융위원회, 정책 간담회에서 제도 개선 방안 논의',
       'summary':('금융위원회가 간담회에서 기업가치 제고 방안을 논의했고 소액주주 보호 정책을 검토했습니다. '
                  '참석자들은 9999개 상장사에 해당 제도를 적용하기로 확정했다고 밝혔습니다.'),
       'evidence_ids':['E01','E02']}
    ok,reason=editorial._check_details(x,content)
    assert not ok and '원문에 없는 숫자' in reason


def test_google_news_aggregate_landing_not_taken_as_fulltext(monkeypatch):
    class R:
        url='https://news.google.com/articles/123'
        headers={'Content-Type':'text/html'}
        def raise_for_status(self):pass
        text='<html><main>'+'정책을 발표했습니다. '*100+'</main></html>'
    monkeypatch.setattr(editorial.requests,'get',lambda *a,**kw:R())
    assert editorial.fetch_fulltext('https://news.google.com/articles/123')==''


def test_article_title_and_publication_date_count_as_numeric_evidence():
    body=('기상청은 주말 시민들의 야외활동을 돕기 위해 새로운 예보를 발표했습니다. '
          '지자체는 시민 안전과 관련한 행사 안내를 공식 홈페이지에 게시했습니다. '
          '다음 달 관련 안내를 추가로 제공할 계획이라고 관계 기관은 밝혔습니다. ')
    candidate={'category':'생활/문화','candidate_id':'a1','title':'19일 시민 안전 행사 안내',
               'date':'2026-11-15','content':body}
    news={'candidate_id':'a1', 'headline':'19일 시민 안전 행사 안내와 지역 참여 프로그램 소개',
          'summary':('기상청은 시민들이 야외활동을 준비하도록 새로운 예보를 공개했습니다. '
                     '지자체도 안전 관련 행사 안내를 홈페이지에 게시했으며 다음 달 추가 안내를 제공할 계획이라고 밝혔습니다.'),
          'evidence_ids':['E01','E02']}
    ok, reason=editorial.validate_article(news,candidate)
    assert ok,reason
    bad={**news,'headline':news['headline'].replace('19일','999일')}
    ok, reason=editorial.validate_article(bad,candidate)
    assert not ok and '원문에 없는 숫자' in reason


def test_missing_categories_repaired_together(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','fake')
    content=('보건복지부는 지역 보건소의 신청 창구를 새롭게 운영한다고 발표했습니다. '
             '관계자는 지역 거점에서 관련 서류를 접수하며 현장 안내를 제공한다고 밝혔습니다. '
             '접수 과정의 혼선을 줄이기 위해 공식 안내를 함께 게시했다고 설명했습니다. ')
    categories={cat:[{'category':cat,'candidate_id':cat,'content':content,
                     'title':cat+' 정책 공지','date':'2026-11-15','source':'공식','url':'https://example.com/x'}]
                for cat in editorial.GENERAL_CATEGORIES}
    summary=('관계 기관은 지역 보건소의 새 신청 창구를 운영하고 현장 안내를 제공한다고 발표했습니다. '
             '서류 접수 과정의 혼선을 줄이기 위해 공식 안내도 함께 게시했다고 설명했습니다.')
    assert 70<=len(summary)<=125
    calls=[]
    def mock_call(key, payload, requested, repair_notes=None):
        calls.append(tuple(requested))
        def news(cat):
            return {'category':cat,'candidate_id':cat,
                    'headline':cat+' 분야 관계 기관이 새로운 신청 창구 운영을 발표',
                    'summary':summary,'evidence_ids':['E01','E02']}
        if len(calls)==1:
            return {'items':[news('정치')]}
        return {'items':[news(cat) for cat in requested]}
    monkeypatch.setattr(editorial,'_call_gemini',mock_call)
    monkeypatch.setattr(editorial,'has_duplicate_topics',lambda items:False)
    assert len(editorial.write_verified_news(categories))==5
    assert len(calls)==5
    assert calls[1:] == [("경제",), ("사회",), ("국제",), ("생활/문화",)]


def test_gemini_retry_503_then_success(monkeypatch):
    calls=[]
    class Fail:
        status_code=503
        def json(self): return {'error':{'status':'UNAVAILABLE','message':'server busy'}}
        def raise_for_status(self):
            err=editorial.requests.HTTPError('503')
            err.response=self
            raise err
    class OK:
        status_code=200
        def json(self):return {'candidates':[{'content':{'parts':[{'text':'{"items":[]}'}]}}]}
        def raise_for_status(self):return None
    def fake_post(*args,**kwargs):
        calls.append(1)
        return Fail() if len(calls)<3 else OK()
    monkeypatch.setattr(editorial.requests,'post',fake_post)
    monkeypatch.setattr(editorial.time,'sleep',lambda seconds:None)
    assert editorial._call_gemini('secret',[],('사회',))=={'items':[]}
    assert len(calls)==3


def test_429_daily_quota_is_not_retried(monkeypatch):
    calls=[]
    class Fail:
        status_code=429
        def json(self):return {'error':{'status':'RESOURCE_EXHAUSTED', 'message':'Daily quota exceeded per day'}}
        def raise_for_status(self):
            exc=editorial.requests.HTTPError('429')
            exc.response=self
            raise exc
    def fake_post(*args,**kwargs):
        calls.append(1)
        return Fail()
    monkeypatch.setattr(editorial.requests,'post',fake_post)
    with pytest.raises(editorial.GeminiApiRequestError,match='HTTP 429') as exc:
        editorial._call_gemini('secret',[],('사회',))
    assert exc.value.retryable is False
    assert len(calls)==1


def test_omitted_categories_are_retried_individually(monkeypatch):
    """Regression: politics/culture omission is not retried as same batch."""
    monkeypatch.setenv('GEMINI_API_KEY','test-key')
    details=(
        '담당 기관은 해당 분야의 새로운 제도에 관하여 공식적인 설명회를 개최했다고 발표했다. '
        '설명회에서는 지역 현장 접수와 온라인 안내 서비스의 운영을 구분하여 공개했다. '
        '관계자는 두 가지 이용 절차를 정리해 신청 대상자에게 별도로 안내했다. '
    )
    cats=editorial.GENERAL_CATEGORIES
    candidates={cat:[{'candidate_id':cat,'category':cat,'title':cat+' 새로운 제도 운영 안내',
       'date':'2026-11-15','url':'https://example.org/a/'+str(i),
       'source':'기관 발표','content':details}] for i,cat in enumerate(cats)}
    example_summary=('담당 기관은 새로운 제도를 소개하고 지역 현장 접수와 온라인 서비스의 운영 방법을 나누어 공개했습니다. '
       '참석자는 두 가지 안내 절차를 확인해 신청 대상자에게 추가 설명을 제공했습니다.')
    assert 70<=len(example_summary)<=125
    def make(cat):
        return {'category':cat,'candidate_id':cat,
            'headline':cat+' 분야의 새로운 제도에 관한 공식 설명회 개최',
            'summary':example_summary,'evidence_ids':['E01','E02']}
    seen=[]
    def fake(key,rows,requested,repair_notes=None):
        seen.append(requested)
        if len(requested)>1:
            return {'items':[make(cat) for cat in requested if cat not in ('정치','생활/문화')]}
        return {'items':[make(requested[0])]}
    monkeypatch.setattr(editorial,'_call_gemini',fake)
    monkeypatch.setattr(editorial,'has_duplicate_topics',lambda arr:False)
    result=editorial.write_verified_news(candidates)
    assert len(result)==5
    assert seen==[cats,('정치',),('생활/문화',)]


def test_empty_source_category_has_diagnostic_not_fake_filler(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','test-key')
    details=('담당 기관은 새로운 지역 서비스를 시행한다고 공식적으로 발표했다. '
        '시민은 온라인에서도 서비스를 신청할 수 있게 됐다고 밝혔다. '
        '지역별 신청 절차가 서로 다르다는 점도 설명했다. ')
    cats=editorial.GENERAL_CATEGORIES
    candidates={cat:[{'candidate_id':cat,'category':cat,'title':'공식 안내',
              'date':'2026-11-15','url':'https://example.org/a',
              'source':'기관 발표','content':details}] for cat in cats[1:]}
    candidates[cats[0]]=[]
    monkeypatch.setattr(editorial,'_call_gemini',lambda *a,**kw:{'items':[]})
    with pytest.raises(editorial.PublicationQualityError,match='원문 전문과 사실 근거가 확인된 기사 후보가 없음'):
        editorial.write_verified_news(candidates)
