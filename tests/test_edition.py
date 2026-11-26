from copy import deepcopy
import json

import pytest

from src import automation, edition


def manuscript():
    body = ('이번 문장은 실제 뉴스가 아닌 원고 전달과 이미지 배치 검사용 자료입니다. '
            '구체적인 대상과 신청 기간을 확인하는 절차를 설명하는 시험용 문장을 사용합니다. '
            '수집과 렌더링이 같은 원고를 유지하는지 검사하며 실제 발송에는 사용하지 않습니다.')
    def row(cat):
        return {'category': cat, 'title': cat+' 분야 원고 인계 검증용 기사 제목',
                'headline': cat+' 분야 원고 인계 검증용 제목', 'summary': body,
                'date': '2026-11-26', 'url': 'https://first.example/news/1',
                'source': '시험', 'sources': ['https://first.example/news/1', 'https://second.example/news/2']}
    return {'date': '2026-11-26', 'checked': '06:04',
            'articles': [row(cat) for cat in edition.GENERAL],
            'medical': [row(cat) for cat in edition.MEDICAL],
            'weather': {'narrative': '디자인 시험용'}, 'market': {'test': {'date': '2026-11-26'}}}


def save(root, data):
    path = root/'editions'/'2026-11-26.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(edition.encoded(data))


def test_missing_manuscript_fails_without_reselecting(tmp_path):
    with pytest.raises(edition.EditionError, match='확정 원고가 없습니다'):
        edition.load(tmp_path, '2026-11-26')


@pytest.mark.parametrize('change', ['date', 'short', 'duplicate', 'one_source', 'same_site'])
def test_unready_manuscript_is_blocked(change):
    data = manuscript()
    if change == 'date': data['date'] = '2026-11-25'
    if change == 'short': data['articles'][0]['summary'] = '짧습니다.'
    if change == 'duplicate': data['articles'][1]['category'] = '정치'
    if change == 'one_source': data['articles'][0]['sources'] = ['https://first.example/news/1']
    if change == 'same_site': data['articles'][0]['sources'] = ['https://first.example/news/1', 'https://first.example/news/2']
    with pytest.raises(edition.EditionError):
        edition.validate(data, '2026-11-26')


def test_production_uses_approved_text_without_fetching_or_summarising(monkeypatch, tmp_path):
    from datetime import datetime as RealDateTime
    class Clock:
        @classmethod
        def now(cls, tz): return RealDateTime(2026, 11, 26, 6, 10, tzinfo=tz)
    monkeypatch.setattr(automation, 'datetime', Clock)
    monkeypatch.setattr(automation, 'ROOT', tmp_path)
    monkeypatch.setattr(automation, 'DOCS', tmp_path/'docs')
    monkeypatch.delenv('RUN_DEMO', raising=False)
    data = manuscript()
    save(tmp_path, data)
    def forbidden(*a, **kw): raise AssertionError('approved copy must not be rewritten')
    for name in ('build_news', 'weather_today', 'market_data', 'summarise'):
        monkeypatch.setattr(automation, name, forbidden)
    seen = []
    def render(path, date, checked, articles, *a):
        seen.append(deepcopy(articles))
        path.write_bytes(b'approved image')
        path.with_name(path.stem+'-preview.jpg').write_bytes(b'approved preview')
    monkeypatch.setattr(automation, 'render_morning', render)
    monkeypatch.setattr(automation, 'render_medical', render)
    automation.main()
    assert seen == [data['articles'], data['medical']]
    exported = json.loads((tmp_path/'docs/2026-11-26/edition.json').read_text())
    assert exported == data
    assert edition.verify(tmp_path, data['date'])['date'] == data['date']
    # A recovery build must still render the saved article text unchanged.
    automation.main()
    assert seen[2:] == seen[:2]
    (tmp_path/'docs/2026-11-26/morning.png').write_bytes(b'different image')
    with pytest.raises(edition.EditionError, match='변경'):
        edition.verify(tmp_path, data['date'])


def test_changed_approved_copy_invalidates_old_images(tmp_path):
    data = manuscript()
    save(tmp_path, data)
    folder = tmp_path/'docs/2026-11-26'
    folder.mkdir(parents=True)
    for name in edition.FILES:
        (folder/name).write_text('fixture')
    edition.seal(folder, data)
    data['articles'][0]['summary'] = data['articles'][0]['summary'].replace('이번', '해당', 1)
    save(tmp_path, data)
    with pytest.raises(edition.EditionError, match='배포본이 다릅니다'):
        edition.verify(tmp_path, data['date'])


def test_regular_build_survives_missing_external_manuscript(monkeypatch, tmp_path):
    """Interrupted preparation cannot disable the established morning build."""
    from datetime import datetime as RealDateTime
    class Clock:
        @classmethod
        def now(cls, tz): return RealDateTime(2026, 11, 26, 5, 10, tzinfo=tz)
    monkeypatch.setattr(automation, 'datetime', Clock)
    monkeypatch.setattr(automation, 'ROOT', tmp_path)
    monkeypatch.setattr(automation, 'DOCS', tmp_path/'docs')
    monkeypatch.delenv('RUN_DEMO', raising=False)
    data = manuscript()
    calls = []
    monkeypatch.setattr(automation, 'build_news', lambda: (calls.append(1), (data['articles'], data['medical']))[1])
    monkeypatch.setattr(automation, 'weather_today', lambda: data['weather'])
    monkeypatch.setattr(automation, 'market_data', lambda: data['market'])
    def render(path, *args):
        path.write_bytes(b'approved image')
        path.with_name(path.stem+'-preview.jpg').write_bytes(b'approved preview')
    monkeypatch.setattr(automation, 'render_morning', render)
    monkeypatch.setattr(automation, 'render_medical', render)
    automation.main()
    assert calls == [1]
    assert edition.verify(tmp_path, data['date'])['date'] == data['date']
    automation.main()
    assert calls == [1]  # recovery uses the exact same manuscript


def test_existing_bad_external_manuscript_is_not_silently_replaced(tmp_path):
    data = manuscript()
    data['articles'][0]['summary'] = '짧습니다.'
    save(tmp_path, data)
    with pytest.raises(edition.EditionError, match='120~180'):
        edition.load(tmp_path, data['date'])
