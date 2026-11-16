"""외부 API/실제 전송을 사용하지 않는 진단 스크립트 회귀 테스트."""
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src import kakao_delivery_test


def test_verifies_user_without_leaking_identity(monkeypatch, capsys):
    monkeypatch.setattr(kakao_delivery_test.requests, 'get', lambda *args, **kwargs: Mock(status_code=200, json=lambda: {'id': 123456, 'properties': {'nickname': 'SECRET_NAME'}}))
    kakao_delivery_test.verify_connected_user('fake-token')
    printed = capsys.readouterr().out
    assert '정상' in printed
    assert '123456' not in printed and 'SECRET_NAME' not in printed and 'fake-token' not in printed


def test_rejects_missing_account_id(monkeypatch):
    monkeypatch.setattr(kakao_delivery_test.requests, 'get', lambda *args, **kwargs: Mock(status_code=200, json=lambda: {}))
    with pytest.raises(RuntimeError, match='연결'):
        kakao_delivery_test.verify_connected_user('fake-token')


def test_text_send_one_call_and_accepts_code_zero(monkeypatch, capsys):
    calls = []
    def fake_post(url, **kw):
        calls.append((url, kw))
        return Mock(status_code=200, json=lambda: {'result_code': 0})
    monkeypatch.setattr(kakao_delivery_test.requests, 'post', fake_post)
    kakao_delivery_test.send_diagnostic_message('fake-token', 'BORAM-TEST-123')
    assert len(calls) == 1
    assert calls[0][0].endswith('/v2/api/talk/memo/default/send')
    assert json.loads(calls[0][1]['data']['template_object'])['object_type'] == 'text'
    assert 'BORAM-TEST-123' in calls[0][1]['data']['template_object']
    assert 'result_code=0' in capsys.readouterr().out


def test_rejects_nonzero_kakao_result(monkeypatch):
    monkeypatch.setattr(kakao_delivery_test.requests, 'post', lambda *args, **kwargs: Mock(status_code=200, json=lambda: {'result_code': -2}))
    with pytest.raises(RuntimeError, match='result_code'):
        kakao_delivery_test.send_diagnostic_message('fake-token', 'T')


def test_diagnostic_requires_manual_event(monkeypatch):
    monkeypatch.setenv('GITHUB_EVENT_NAME', 'schedule')
    with pytest.raises(RuntimeError, match='수동 실행'):
        kakao_delivery_test.main()


def test_workflow_only_manual():
    workflow = (ROOT / '.github' / 'workflows' / 'kakao-delivery-diagnostic.yml').read_text()
    assert 'workflow_dispatch:' in workflow
    assert 'schedule:' not in workflow
    assert 'src.kakao_delivery_test' in workflow
    assert 'git add data/kakao_refresh.enc' in workflow
