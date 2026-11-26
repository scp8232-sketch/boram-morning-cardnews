"""예약/수동 발송 중복 방지 회귀 검사: 외부 API를 호출하지 않는다."""
from __future__ import annotations
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import send_kakao

DATE = '2026-11-16'


def stub_sender(monkeypatch, tmp_path, existing=None, event='schedule', run='101'):
    f = tmp_path / 'sent.json'
    if existing is not None:
        f.write_text(json.dumps({DATE: existing}, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(send_kakao, 'SENT_FILE', f)
    monkeypatch.setattr(send_kakao, 'generated_card_date', lambda: DATE)
    monkeypatch.setattr(send_kakao, 'refreshed_access_token', lambda: 'placeholder-token')
    monkeypatch.setattr(send_kakao, 'wait_page', lambda url, **kw: None)
    monkeypatch.setenv('PAGES_BASE_URL', 'https://example.github.io/boram-morning-cardnews/')
    monkeypatch.setenv('GITHUB_EVENT_NAME', event)
    monkeypatch.setenv('GITHUB_RUN_ID', run)
    sent_calls = []
    monkeypatch.setattr(send_kakao, 'send_one', lambda token, title, image_url, original_url, date: sent_calls.append((title,image_url,date)))
    return f, sent_calls


def read_day(path):
    return json.loads(path.read_text(encoding='utf-8'))[DATE]


def test_legacy_record_blocks_daily_resend(monkeypatch, tmp_path):
    path, calls = stub_sender(monkeypatch,tmp_path,existing=['medical','morning'])
    send_kakao.main()
    assert calls == []
    assert read_day(path) == ['medical','morning']


def test_manual_after_schedule_remains_deduplicated(monkeypatch, tmp_path):
    path, calls = stub_sender(monkeypatch,tmp_path,existing={'schedule':['medical','morning']},event='workflow_dispatch',run='202')
    send_kakao.main()
    assert calls == []
    monkeypatch.setenv('GITHUB_RUN_ID','203')
    send_kakao.main()
    assert calls == []


def test_manual_first_blocks_schedule(monkeypatch, tmp_path):
    path, calls = stub_sender(monkeypatch,tmp_path,existing={},event='workflow_dispatch',run='204')
    send_kakao.main()
    monkeypatch.setenv('GITHUB_EVENT_NAME','schedule')
    send_kakao.main()
    assert len(calls) == 2
    assert read_day(path)['daily'] == ['medical','morning']


def test_partial_failure_only_resends_missing_card(monkeypatch, tmp_path):
    path, calls = stub_sender(monkeypatch,tmp_path,existing={})
    def flaky(token,title,image_url,original_url,date):
        if '보험' in title:
            raise RuntimeError('simulated Kakao failure')
        calls.append(title)
    monkeypatch.setattr(send_kakao,'send_one',flaky)
    with pytest.raises(RuntimeError):
        send_kakao.main()
    assert read_day(path)['daily'] == ['morning']
    monkeypatch.setattr(send_kakao,'send_one',lambda token,title,image_url,original_url,date: calls.append(title))
    send_kakao.main()
    assert len(calls)==2
    assert '보험' in calls[-1]
    assert read_day(path)['daily'] == ['medical','morning']


def test_scheduled_cron_uses_early_buffer():
    wf=(ROOT/'.github/workflows/morning.yml').read_text(encoding='utf-8')
    assert "cron: '10 20 * * 0-4'" in wf



def test_explicit_test_does_not_reset_regular_receipt(monkeypatch, tmp_path):
    path, calls = stub_sender(monkeypatch,tmp_path,existing={'daily':['medical','morning']},event='workflow_dispatch',run='222')
    send_kakao.main(test=True)
    assert len(calls) == 2
    assert all(title.startswith('[테스트]') for title, _, _ in calls)
    records = json.loads(path.read_text())
    assert records[DATE] == {'daily':['medical','morning']}
    assert records['test-'+DATE+'-222']['daily'] == ['medical','morning']
    send_kakao.main(test=True)
    assert len(calls) == 2
    send_kakao.main()
    assert len(calls) == 2


def test_scheduled_event_cannot_request_test(monkeypatch, tmp_path):
    path, calls = stub_sender(monkeypatch,tmp_path,event='schedule')
    with pytest.raises(RuntimeError, match='수동 실행'):
        send_kakao.main(test=True)
    assert calls == []
