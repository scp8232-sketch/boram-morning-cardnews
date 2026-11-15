from datetime import date
from src import sources
from src.automation import _clean_editorial


class FakeResponse:
    def __init__(self, body='', payload=None):
        self.text = body
        self._payload = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._payload


def test_no_repeated_title_or_publisher():
    title, body = _clean_editorial('건강보험 제도 변경 - 테스트신문',
        '건강보험 제도 변경 - 테스트신문', '테스트신문')
    assert '테스트신문' not in title
    assert body == ''


def test_opinet_api(monkeypatch):
    monkeypatch.setattr(sources, 'today_kst', lambda: date(2026, 11, 13))
    monkeypatch.setattr(sources.requests, 'get', lambda *args, **kwargs: FakeResponse(payload={
        'RESULT': {'OIL': [
            {'TRADE_DT': '20261112', 'PRODCD': 'B027', 'PRICE': '1854.98'},
            {'TRADE_DT': '20261112', 'PRODCD': 'D047', 'PRICE': '1841.82'}]}}))
    result = sources.opinet_api_prices('FAKE')
    assert result['휘발유']['value'] == 1854.98
    assert result['경유']['date'] == '2026-11-12'


def test_opinet_public_page(monkeypatch):
    monkeypatch.setattr(sources, 'today_kst', lambda: date(2026, 11, 13))
    sample = '<html><table><tr><td>2026년11월12일</td><td>2381.05</td><td>1854.98</td><td>1841.82</td></tr></table></html>'
    monkeypatch.setattr(sources.requests, 'get', lambda *args, **kwargs: FakeResponse(body=sample))
    result = sources.opinet_public_prices()
    assert round(result['휘발유']['value']) == 1855
    assert round(result['경유']['value']) == 1842


def test_gold_monthly_table(monkeypatch):
    monkeypatch.setattr(sources, 'today_kst', lambda: date(2026, 11, 13))
    sample = '<html><table><tr><td>11.13 (금)</td><td>737,000</td><td>633,000</td></tr></table></html>'
    monkeypatch.setattr(sources.requests, 'get', lambda *args, **kwargs: FakeResponse(body=sample))
    result = sources.gold_prices()
    assert result['buy'] == 737000 and result['sell'] == 633000


def test_old_gold_is_rejected(monkeypatch):
    monkeypatch.setattr(sources, 'today_kst', lambda: date(2026, 11, 13))
    sample = '<table><tr><td>11.01</td><td>700,000</td><td>630,000</td></tr></table>'
    monkeypatch.setattr(sources.requests, 'get', lambda *args, **kwargs: FakeResponse(body=sample))
    assert sources.gold_prices() is None


def test_weather_narrative():
    assert '예보' not in sources.weather_sentence({'서울': {'lo': 3, 'hi': 12, 'condition': '흐림'},
        '부산': {'lo': 7, 'hi': 15, 'condition': '비'}}) or '전망' in sources.weather_sentence({'서울': {'lo': 3, 'hi': 12, 'condition': '흐림'},
        '부산': {'lo': 7, 'hi': 15, 'condition': '비'}})
