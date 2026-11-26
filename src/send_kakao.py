"""카카오 '나와의 채팅'으로 미리보기 2개+원본 링크 발송. 갱신 토큰은 암호화해 저장."""
from __future__ import annotations
import base64
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
from .edition import verify as verify_edition

from cryptography.fernet import Fernet, InvalidToken
import requests

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / 'data' / 'kakao_refresh.enc'
SENT_FILE = ROOT / 'data' / 'sent.json'
KST = ZoneInfo('Asia/Seoul')


def cipher(rest_key: str, client_secret: str) -> Fernet:
    if not rest_key or not client_secret:
        raise RuntimeError('KAKAO_REST_API_KEY와 KAKAO_CLIENT_SECRET이 모두 필요합니다.')
    material = ('BoramCardNews/Kakao/' + rest_key + ':' + client_secret).encode('utf-8')
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))


def refreshed_access_token() -> str:
    rest_key = os.environ.get('KAKAO_REST_API_KEY', '').strip()
    secret = os.environ.get('KAKAO_CLIENT_SECRET', '').strip()
    crypt = cipher(rest_key, secret)
    seed = os.environ.get('KAKAO_REFRESH_TOKEN', '').strip()
    if TOKEN_FILE.exists():
        try:
            refresh = crypt.decrypt(TOKEN_FILE.read_bytes()).decode('utf-8')
        except InvalidToken as e:
            raise RuntimeError('암호화된 카카오 토큰을 읽을 수 없습니다. Client Secret 변경 여부를 확인하세요.') from e
    else:
        refresh = seed
    if not refresh:
        raise RuntimeError('KAKAO_REFRESH_TOKEN 설정이 필요합니다. README의 최초 연결 절차를 참고하세요.')
    # A temporary network connection failure must not cancel a completed news issue.
    # Only retry failures known to occur before a successful HTTP response.
    response = None
    for attempt in range(4):
        try:
            response = requests.post('https://kauth.kakao.com/oauth/token', data={
                'grant_type': 'refresh_token', 'client_id': rest_key,
                'client_secret': secret, 'refresh_token': refresh,
            }, timeout=(15, 25))
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep((5, 12, 25)[attempt])
                continue
            break
        except (requests.ConnectTimeout, requests.ConnectionError) as exc:
            if attempt == 3:
                raise RuntimeError('카카오 인증 서버 연결이 네 차례 실패했습니다.') from exc
            time.sleep((5, 12, 25)[attempt])
    if response is None:
        raise RuntimeError('카카오 인증 응답을 받지 못했습니다.')
    if response.status_code != 200:
        raise RuntimeError(f'카카오 토큰 갱신 실패: HTTP {response.status_code}. 연결 해제 여부와 Secret을 확인하세요.')
    reply = response.json()
    access = reply.get('access_token')
    if not access:
        raise RuntimeError('카카오 응답에 액세스 토큰이 없습니다.')
    refresh = reply.get('refresh_token') or refresh
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_bytes(crypt.encrypt(refresh.encode('utf-8')))
    return access


def wait_page(url: str, *, expected_sha: str | None = None) -> None:
    for attempt in range(5):
        try:
            response = requests.get(url, timeout=20)
            if (response.status_code == 200
                    and response.headers.get('Content-Type', '').startswith('image/')
                    and (expected_sha is None or hashlib.sha256(response.content).hexdigest() == expected_sha)):
                return
        except requests.RequestException:
            pass
        if attempt != 4:
            time.sleep(10)
    raise RuntimeError('GitHub Pages 이미지가 공개되지 않았거나 확정 원고의 이미지와 다릅니다. 배포 기록을 확인하세요.')


def send_one(token: str, title: str, image_url: str, original_url: str, date: str) -> None:
    template = {
        'object_type': 'feed',
        'content': {
            'title': f'{title} · {date}',
            'description': '완성된 카드뉴스 보기 · 원본 이미지 열기/저장',
            'image_url': image_url,
            'link': {'web_url': original_url, 'mobile_web_url': original_url},
        },
        'buttons': [{'title': '원본 이미지 열기', 'link': {'web_url': original_url, 'mobile_web_url': original_url}}],
    }
    # Only pre-connect errors can safely retry. A read timeout might mean
    # Kakao accepted the message, so it is NOT automatically retried here.
    response = None
    for attempt in range(3):
        try:
            response = requests.post('https://kapi.kakao.com/v2/api/talk/memo/default/send',
                headers={'Authorization': 'Bearer '+token},
                data={'template_object': json.dumps(template, ensure_ascii=False, separators=(',', ':'))},
                timeout=(12, 25))
            break
        except (requests.ConnectTimeout, requests.ConnectionError) as exc:
            if attempt == 2:
                raise RuntimeError('카카오 메시지 연결이 세 차례 실패했습니다.') from exc
            time.sleep((6, 15)[attempt])
    if response is None:
        raise RuntimeError('카카오 메시지 API 응답을 받지 못했습니다.')
    if response.status_code != 200:
        raise RuntimeError(f'카카오 메시지 발송 실패: HTTP {response.status_code}. 제품 링크 도메인/동의항목을 확인하세요.')
    if response.json().get('result_code') != 0:
        raise RuntimeError('카카오 API 응답이 발송 성공 코드가 아닙니다.')


def generated_card_date() -> str:
    """생성된 카드의 실제 발행 날짜를 사용한다. 자정을 넘어도 오늘 날짜를 새로 계산하지 않는다."""
    index = ROOT / 'docs' / 'index.html'
    if not index.is_file():
        raise RuntimeError('카드뉴스 목록 파일이 없습니다. 이미지 생성·배포 단계를 확인하세요.')
    page = index.read_text(encoding='utf-8')
    match = re.search(r'url\s*=\s*(\d{4}-\d{2}-\d{2})/', page, re.IGNORECASE)
    if not match:
        raise RuntimeError('카드뉴스 목록에서 발행 날짜를 확인하지 못했습니다.')
    published = match.group(1)
    # 이전 실행의 오래된 카드를 새 카드로 오인해 전송하지 않도록 한다.
    age = (datetime.now(KST).date() - datetime.strptime(published, '%Y-%m-%d').date()).days
    if age != 0:
        raise RuntimeError('오늘자 카드가 아닙니다. 과거 카드 자동 재전송을 차단합니다.')
    image_folder = ROOT / 'docs' / published
    for key in ('morning', 'medical'):
        for name in (f'{key}.png', f'{key}-preview.jpg'):
            if not (image_folder / name).is_file():
                raise RuntimeError(f'발행 파일이 없습니다: {published}/{name}')
    verify_edition(ROOT, published)
    print(f'발행 날짜 확인: {published} (현재 한국 시간과 달라도 생성된 카드 날짜를 사용합니다)')
    return published


def main(*, test: bool = False):
    if test and (os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
                 or not re.fullmatch(r'\d+', os.environ.get('GITHUB_RUN_ID', ''))):
        raise RuntimeError('테스트 발송은 명시적인 GitHub 수동 실행에서만 허용합니다.')
    date = generated_card_date()
    base = os.environ.get('PAGES_BASE_URL', '').strip()
    if not base.startswith('https://'):
        raise RuntimeError('GitHub Pages 배포 주소를 먼저 설정해야 합니다.')
    # All triggers (scheduled, workflow_run, manual) share ONE daily delivery ledger.
    # Never use the GitHub run ID for deduplication: every event gets a new ID.
    sent = json.loads(SENT_FILE.read_text(encoding='utf-8')) if SENT_FILE.exists() else {}
    record_key = f'test-{date}-{os.environ.get("GITHUB_RUN_ID")}' if test else date
    old_record = sent.get(record_key, {})
    if isinstance(old_record, list):
        day_record = {'legacy': sorted(set(old_record))}
    elif isinstance(old_record, dict):
        day_record = old_record
    else:
        raise RuntimeError('기존 발송 기록 형식이 올바르지 않습니다. 기록을 덮어쓰지 않습니다.')

    # Read both historic per-run receipts and the new shared daily receipt.
    # This also prevents a newly patched run from duplicating cards already
    # delivered on the same day by the older workflow implementation.
    known_cards = {'morning', 'medical'}
    completed = set()
    for key, receipt in day_record.items():
        if isinstance(receipt, list):
            completed.update(set(receipt) & known_cards)
    delivery_id = 'daily'
    if completed == known_cards:
        print(f'오늘자 두 카드 이미 전송 완료: {date}. 재발송 생략.')
        return
    print(f'하루 1회 발송 / 발행일: {date} / 남은 카드: {sorted(known_cards-completed)}')
    token = refreshed_access_token()
    for key, title in [('morning', '이보람의 MORNING POST'), ('medical', '보험·의료 브리핑')]:
        if key in completed:
            continue
        original_url = urljoin(base.rstrip('/')+'/', f'{date}/{key}.png')
        preview_url = urljoin(base.rstrip('/')+'/', f'{date}/{key}-preview.jpg')
        manifest_file = ROOT / 'docs' / date / 'publication.json'
        manifest = None
        if manifest_file.is_file():
            manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
            version = manifest['manuscript_sha256'][:16]
            original_url += '?v=' + version
            preview_url += '?v=' + version
        wait_page(preview_url, expected_sha=manifest['files'][f'{key}-preview.jpg'] if manifest else None)
        if manifest:
            wait_page(original_url, expected_sha=manifest['files'][f'{key}.png'])
        if test:
            title = '[테스트] ' + title
        send_one(token, title, preview_url, original_url, date)
        completed.add(key)
        day_record[delivery_id] = sorted(completed)
        sent[record_key] = day_record
        SENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        SENT_FILE.write_text(json.dumps(sent, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(f'{title} 발송 API 성공 ({delivery_id})')
    print('카카오 API 발송 완료. 실제 카카오톡 수신은 본인 채팅에서 확인하세요.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='수동으로 요청한 테스트 카드 두 장 발송')
    main(test=parser.parse_args().test)

