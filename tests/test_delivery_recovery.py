"""Independent delivery recovery: no external network or message is sent."""
from pathlib import Path
from datetime import datetime
import json
import pytest
import requests

from src import send_kakao

ROOT=Path(__file__).resolve().parents[1]


def workflow(name):
    # Optional only for workflow syntax tests; no dependency for production.
    yaml = pytest.importorskip('yaml')
    # BaseLoader avoids PyYAML 1.1 parsing `on` as boolean True.
    return yaml.load((ROOT/'.github/workflows'/name).read_text(encoding='utf-8'), Loader=yaml.BaseLoader)


def test_workflows_are_separate_and_reschedule():
    build=workflow('morning.yml')
    send=workflow('kakao-send-only.yml')
    rescue=workflow('pages-recover.yml')
    assert not any('카카오톡 나에게 카드' in str(step.get('name','')) for job in build['jobs'].values() for step in job['steps'])
    assert build['jobs']['deploy']['needs']=='build'
    assert any('upload-pages-artifact@v4' in str(step.get('uses','')) for step in build['jobs']['build']['steps'])
    assert 'schedule' in send['on'] and 'workflow_run' in send['on'] and 'workflow_dispatch' in send['on']
    assert send['concurrency']['group']!=build['concurrency']['group']
    assert 'schedule' in rescue['on']
    assert 'kakao-send-only.yml' not in rescue['on'].get('workflow_run',{})


def test_only_today_can_be_sent(monkeypatch, tmp_path):
    from zoneinfo import ZoneInfo
    day=datetime.now(ZoneInfo('Asia/Seoul')).date()
    old=day.fromordinal(day.toordinal()-1).isoformat()
    (tmp_path/'docs').mkdir()
    (tmp_path/'docs/index.html').write_text(f'<meta http-equiv="refresh" content="0;url={old}/">',encoding='utf-8')
    monkeypatch.setattr(send_kakao,'ROOT',tmp_path)
    with pytest.raises(RuntimeError, match='오늘자 카드'):
        send_kakao.generated_card_date()


def test_kakao_connect_timeout_retries_without_duplicate_posts(monkeypatch):
    calls=[]
    class Response:
        status_code=200
        def json(self): return {'result_code':0}
    def fake_post(*args, **kwargs):
        calls.append(1)
        if len(calls)==1: raise requests.ConnectTimeout('before connection')
        return Response()
    monkeypatch.setattr(send_kakao.requests,'post',fake_post)
    monkeypatch.setattr(send_kakao.time,'sleep',lambda _:None)
    send_kakao.send_one('dummy','test','https://x/p.jpg','https://x/p.png','2026-11-25')
    assert len(calls)==2


def test_kakao_read_timeout_not_retried(monkeypatch):
    calls=[]
    def fake_post(*args,**kwargs):
        calls.append(1)
        raise requests.ReadTimeout('response unknown')
    monkeypatch.setattr(send_kakao.requests,'post',fake_post)
    with pytest.raises(requests.ReadTimeout):
        send_kakao.send_one('dummy','test','https://x/p.jpg','https://x/p.png','2026-11-25')
    assert len(calls)==1


def test_token_auth_retry_503_then_success(monkeypatch,tmp_path):
    class Res:
        def __init__(self,code): self.status_code=code
        def json(self): return {'access_token':'test','refresh_token':'rotated'}
    responses=iter([Res(503),Res(200)])
    calls=[]
    monkeypatch.setattr(send_kakao.requests,'post',lambda *a,**k:(calls.append(1),next(responses))[1])
    monkeypatch.setattr(send_kakao.time,'sleep',lambda _:None)
    monkeypatch.setattr(send_kakao,'TOKEN_FILE',tmp_path/'refresh.enc')
    monkeypatch.setenv('KAKAO_REST_API_KEY','id')
    monkeypatch.setenv('KAKAO_CLIENT_SECRET','secret')
    monkeypatch.setenv('KAKAO_REFRESH_TOKEN','seed')
    assert send_kakao.refreshed_access_token()=='test'
    assert len(calls)==2
    assert (tmp_path/'refresh.enc').is_file()


def test_wait_page_rejects_stale_cdn_image(monkeypatch):
    import hashlib
    class Response:
        status_code = 200
        headers = {'Content-Type': 'image/png'}
        def __init__(self, data): self.content = data
    images = iter([Response(b'old edition'), Response(b'approved edition')])
    calls = []
    def get(*args, **kwargs):
        calls.append(1)
        return next(images)
    monkeypatch.setattr(send_kakao.requests, 'get', get)
    monkeypatch.setattr(send_kakao.time, 'sleep', lambda _: None)
    send_kakao.wait_page('https://example.org/morning.png',
                         expected_sha=hashlib.sha256(b'approved edition').hexdigest())
    assert len(calls) == 2

