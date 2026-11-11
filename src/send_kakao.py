"""카카오 '나와의 채팅'으로 미리보기 2개+원본 링크 발송. 갱신 토큰은 암호화해 저장."""
from __future__ import annotations
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

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
    response = requests.post('https://kauth.kakao.com/oauth/token', data={
        'grant_type': 'refresh_token', 'client_id': rest_key,
        'client_secret': secret, 'refresh_token': refresh,
    }, timeout=20)
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


def wait_page(url: str) -> None:
    for attempt in range(16):
        try:
            response = requests.get(url, timeout=20)
            if response.status_code == 200 and response.headers.get('Content-Type', '').startswith('image/'):
                return
        except requests.RequestException:
            pass
        if attempt != 15:
            time.sleep(12)
    raise RuntimeError('GitHub Pages 이미지가 공개되지 않았습니다. Pages 설정과 배포 기록을 확인하세요.')


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
    response = requests.post('https://kapi.kakao.com/v2/api/talk/memo/default/send',
        headers={'Authorization': 'Bearer '+token},
        data={'template_object': json.dumps(template, ensure_ascii=False, separators=(',', ':'))},
        timeout=25)
    if response.status_code != 200:
        raise RuntimeError(f'카카오 메시지 발송 실패: HTTP {response.status_code}. 제품 링크 도메인/동의항목을 확인하세요.')
    if response.json().get('result_code') != 0:
        raise RuntimeError('카카오 API 응답이 발송 성공 코드가 아닙니다.')


def main():
    date = datetime.now(KST).strftime('%Y-%m-%d')
    base = os.environ.get('PAGES_BASE_URL', '').strip()
    if not base.startswith('https://'):
        raise RuntimeError('GitHub Pages 배포 주소를 먼저 설정해야 합니다.')
    # 신규 중복 실행시 이미 보낸 카드 재발송 방지
    sent = json.loads(SENT_FILE.read_text(encoding='utf-8')) if SENT_FILE.exists() else {}
    if sent.get(date) == ['morning', 'medical']:
        print('오늘은 이미 두 장을 발송했습니다. 중복 발송을 생략합니다.')
        return
    token = refreshed_access_token()
    completed = set(sent.get(date, []))
    for key, title in [('morning', '이보람의 MORNING POST'), ('medical', '보험·의료 브리핑')]:
        if key in completed:
            continue
        original_url = urljoin(base.rstrip('/')+'/', f'{date}/{key}.png')
        preview_url = urljoin(base.rstrip('/')+'/', f'{date}/{key}-preview.jpg')
        wait_page(preview_url)
        send_one(token, title, preview_url, original_url, date)
        completed.add(key)
        sent[date] = sorted(completed)
        SENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        SENT_FILE.write_text(json.dumps(sent, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(title + ' 발송 API 성공')
    print('카카오 API 발송 완료. 실제 카카오톡 수신은 본인 채팅에서 확인하세요.')


if __name__ == '__main__':
    main()
