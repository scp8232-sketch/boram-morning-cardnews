"""기사 검증 실패 시 고객에게 잘못된 카드뉴스 대신 본인에게만 실패 알림을 보낸다."""
from __future__ import annotations
import json
import requests
from .send_kakao import refreshed_access_token


def main():
    try:
        token=refreshed_access_token()
        template={'object_type':'text',
                  'text':'[이보람의 카드뉴스] 오늘 자동 제작 또는 카카오톡 전송에 실패했습니다. 미확인 카드를 고객에게 보내지 마세요. GitHub Actions 결과를 점검해 주세요.',
                  'link':{'web_url':'https://scp8232-sketch.github.io/boram-morning-cardnews/',
                          'mobile_web_url':'https://scp8232-sketch.github.io/boram-morning-cardnews/'}}
        r=requests.post('https://kapi.kakao.com/v2/api/talk/memo/default/send',
           headers={'Authorization':'Bearer '+token},
           data={'template_object':json.dumps(template,ensure_ascii=False)},timeout=22)
        print('검증 실패 알림:', 'API 요청 성공' if r.status_code==200 else f'전송 실패 HTTP {r.status_code}')
    except (requests.RequestException,RuntimeError,ValueError,KeyError) as e:
        print('검증 실패 알림 전송에 실패했음:',type(e).__name__)


if __name__=='__main__':main()
