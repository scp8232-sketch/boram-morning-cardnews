import json
from pathlib import Path
from src import send_kakao as mod

def setup(monkeypatch, tmp_path, record):
    f=tmp_path/'sent.json'; f.write_text(json.dumps({'2026-11-25':record}),encoding='utf8')
    monkeypatch.setattr(mod,'SENT_FILE',f)
    monkeypatch.setattr(mod,'generated_card_date',lambda:'2026-11-25')
    monkeypatch.setenv('PAGES_BASE_URL','https://example.org/')
    return f

def test_historic_two_manual_runs_skips(monkeypatch,tmp_path):
    f=setup(monkeypatch,tmp_path, {'manual-111':['morning','medical']})
    monkeypatch.setattr(mod,'refreshed_access_token',lambda:(_ for _ in ()).throw(AssertionError('must not refresh')))
    mod.main()
    assert json.loads(f.read_text())['2026-11-25']=={'manual-111':['morning','medical']}

def test_partial_old_receipt_sends_only_missing(monkeypatch,tmp_path):
    f=setup(monkeypatch,tmp_path, {'manual-111':['morning']})
    calls=[]
    monkeypatch.setattr(mod,'refreshed_access_token',lambda:'token')
    monkeypatch.setattr(mod,'wait_page',lambda url, **kw:None)
    monkeypatch.setattr(mod,'send_one',lambda token,title,img,orig,date:calls.append(title))
    mod.main()
    assert calls==['보험·의료 브리핑']
    saved=json.loads(f.read_text())['2026-11-25']
    assert saved['daily']==['medical','morning']
    mod.main()
    assert len(calls)==1

def test_new_daily_receipt_blocks_next_manual_run(monkeypatch,tmp_path):
    f=setup(monkeypatch,tmp_path,{})
    calls=[]
    monkeypatch.setattr(mod,'refreshed_access_token',lambda:'token')
    monkeypatch.setattr(mod,'wait_page',lambda url, **kw:None)
    monkeypatch.setattr(mod,'send_one',lambda *a:calls.append(1))
    monkeypatch.setenv('GITHUB_RUN_ID','100')
    mod.main()
    monkeypatch.setenv('GITHUB_RUN_ID','101')
    mod.main()
    assert len(calls)==2
    assert json.loads(f.read_text())['2026-11-25']['daily']==['medical','morning']

