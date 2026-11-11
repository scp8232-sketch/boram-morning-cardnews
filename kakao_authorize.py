"""로컬 컴퓨터에서만 실행하는 카카오 최초 인증 도우미.

주의: 터미널에 나타나는 리프레시 토큰을 절대 캡처·공유·GitHub 코드에 저장하지 말 것.
"""
from __future__ import annotations
import getpass
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
from urllib.parse import urlencode, parse_qs, urlsplit
import webbrowser
import requests

REDIRECT_URI = 'http://localhost:8787/callback'


def main():
    print('주의: REST API 키, Client Secret, 리프레시 토큰은 절대로 캡처하거나 채팅에 보내지 마세요.')
    print('카카오디벨로퍼스에 리다이렉트 URI ' + REDIRECT_URI + ' 를 먼저 등록하세요.')
    key = getpass.getpass('카카오 REST API 키(입력 숨김): ').strip()
    secret = getpass.getpass('카카오 Client Secret(입력 숨김): ').strip()
    nonce = secrets.token_urlsafe(26)
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            params = parse_qs(urlsplit(self.path).query)
            if not self.path.startswith('/callback?') or params.get('state', [''])[0] != nonce:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Invalid callback/state')
                return
            result['code'] = params.get('code', [''])[0]
            result['error'] = params.get('error', [''])[0]
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write('카카오 인증 창을 닫고 터미널로 돌아가세요.'.encode('utf-8'))

        def log_message(self, fmt, *args):
            pass  # 인가 코드가 URL 로그에 남지 않도록 차단

    query = urlencode({'client_id': key, 'redirect_uri': REDIRECT_URI,
                       'response_type': 'code', 'scope': 'talk_message', 'state': nonce})
    url = 'https://kauth.kakao.com/oauth/authorize?' + query
    with HTTPServer(('127.0.0.1', 8787), Callback) as server:
        server.timeout = 180
        print('브라우저에서 카카오 계정 로그인과 메시지 전송 동의를 완료하세요.')
        webbrowser.open(url)
        server.handle_request()
    if result.get('error') or not result.get('code'):
        raise RuntimeError('인가 코드가 없습니다. 등록된 Redirect URI 또는 사용자 동의를 확인하세요.')
    response = requests.post('https://kauth.kakao.com/oauth/token', data={
        'grant_type': 'authorization_code', 'client_id': key, 'client_secret': secret,
        'redirect_uri': REDIRECT_URI, 'code': result['code'],
    }, timeout=25)
    if response.status_code != 200:
        raise RuntimeError(f'토큰 발급 실패: HTTP {response.status_code}, 상세 화면은 카카오 콘솔에서 확인')
    refresh = response.json().get('refresh_token')
    if not refresh:
        raise RuntimeError('리프레시 토큰을 받지 못했습니다.')
    print('\n' + '='*60)
    print('보안정보! 아래 값은 GitHub Secret KAKAO_REFRESH_TOKEN에만 저장하세요.')
    print('다른 사람에게 보여주거나 스크린샷을 보내지 마세요.')
    print(refresh)
    print('='*60 + '\n')


if __name__ == '__main__':
    main()
