"""수동 실행 전용 카카오 나에게 보내기 진단.

- 카드뉴스 전체 재발행 없이 테스트 문구 한 건만 보낸다.
- 기존 send_kakao의 보안 저장/토큰 갱신 기능을 재사용한다.
- 토큰, 이메일, 전화번호, 카카오 사용자 ID/닉네임은 로그에 출력하지 않는다.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from zoneinfo import ZoneInfo

import requests
from src.send_kakao import refreshed_access_token

KST = ZoneInfo("Asia/Seoul")
ME_URL = "https://kapi.kakao.com/v2/user/me"
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"


def verify_connected_user(access_token: str) -> None:
    """사용자 신원 데이터는 출력하지 않고 토큰의 연결 상태만 검사한다."""
    response = requests.get(
        ME_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    if response.status_code != 200:
        raise RuntimeError(f"카카오 인증 사용자 조회 실패: HTTP {response.status_code}")
    try:
        payload = response.json()
    except (ValueError, TypeError) as error:
        raise RuntimeError("카카오 사용자 조회 응답이 JSON이 아닙니다") from error
    if not isinstance(payload, dict) or not payload.get("id"):
        raise RuntimeError("카카오 사용자 조회에서 계정 연결을 확인하지 못했습니다")
    print("카카오 인증 계정 연결 확인: 정상 (개인정보는 출력하지 않음)")


def send_diagnostic_message(access_token: str, diagnostic_code: str) -> None:
    """이미지 없이 문자 한 건만 전송한다. 응답 성공은 수신 확인과 다르다."""
    template = {
        "object_type": "text",
        "text": f"이보람 카드뉴스 카카오 수신 테스트\n확인코드: {diagnostic_code}\n이 문자가 보이면 수신 성공입니다.",
        "link": {
            "web_url": "https://developers.kakao.com/",
            "mobile_web_url": "https://developers.kakao.com/",
        },
        "button_title": "카카오 개발자 문서",
    }
    response = requests.post(
        SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        data={"template_object": json.dumps(template, ensure_ascii=False)},
        timeout=25,
    )
    if response.status_code != 200:
        raise RuntimeError(f"진단 문자 전송 요청 실패: HTTP {response.status_code}")
    try:
        payload = response.json()
    except (ValueError, TypeError) as error:
        raise RuntimeError("진단 문자 전송 응답이 JSON이 아닙니다") from error
    result = payload.get("result_code") if isinstance(payload, dict) else None
    print(f"카카오 API 진단 문자 응답: HTTP {response.status_code}, result_code={result!r}")
    if result != 0:
        raise RuntimeError("진단 문자 전송 실패: result_code가 0이 아닙니다")


def main() -> None:
    # 수동 workflow만 허용, 일반 예약 발송 및 재발행에 영향 없음.
    event = os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    if event != "workflow_dispatch":
        raise RuntimeError("진단 도구는 수동 실행에서만 사용할 수 있습니다")
    code = f"BORAM-{datetime.now(KST):%m%d-%H%M}-{os.getenv('GITHUB_RUN_ID', 'LOCAL')[-6:]}"
    token = refreshed_access_token()
    verify_connected_user(token)
    print(f"진단 문자 확인코드: {code}")
    send_diagnostic_message(token, code)
    print("카카오 API 수락 확인. 휴대폰 '나와의 채팅'에서 실제 수신 여부를 별도로 확인해야 합니다.")
    print("API 수락 뒤에도 채팅방에 없다면, 카카오 로그인 연결 계정과 현재 카카오톡 계정이 같은지 비교해야 합니다.")


if __name__ == "__main__":
    main()
