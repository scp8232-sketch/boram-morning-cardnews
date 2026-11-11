# 이보람의 아침 카드뉴스 — 무료 클라우드 자동화

평일 오전에 뉴스 검색 → 보수적인 Gemini 요약 → 두 장의 PNG 제작 → GitHub Pages 공개 → 카카오톡 **나와의 채팅**으로 이미지 미리보기와 원본 링크 전송까지 자동화합니다. 컴퓨터가 꺼져 있어도 GitHub Actions 서버에서 실행됩니다.

## 중요: 보안

**REST API 키, Client Secret, AI API 키, 액세스/리프레시 토큰은 공개 저장소의 파일에 쓰지 마세요.** GitHub의 `Settings → Secrets and variables → Actions → New repository secret`에만 입력합니다. 토큰이 표시된 화면은 캡처하지 말고, 코드를 보여줄 때도 `Authorization: Bearer ...`, `client_secret`, `refresh_token`, `api_key` 등이 보이면 미리 가리세요.

이 코드는 카카오 로그인으로 받은 refresh token을 매번 암호화해서 `data/kakao_refresh.enc`에 저장합니다. 암호화 키는 등록한 REST API 키와 Client Secret에서 도출하고 코드에는 보관하지 않습니다. 카카오의 토큰 갱신 시 새로운 refresh token이 나오면 암호화된 내용만 갱신합니다.

## 설치 (최초 1회)

1. 이 저장소로 압축을 푼 파일/폴더들을 업로드합니다. `.github/workflows/morning.yml`까지 **디렉터리 구조를 유지**해야 합니다.
2. [Google AI Studio](https://aistudio.google.com/app/apikey)에서 무료 Gemini API 키를 발급합니다. 유료 전환/결제 연결은 하지 않고 무료 티어를 이용하세요. 요약에 사용하는 모델은 `gemini-2.5-flash-lite`입니다.
3. [카카오디벨로퍼스](https://developers.kakao.com/console/app)에서 이미 만든 **이보람의 아침 카드 뉴스** 앱에 들어갑니다. `카카오 로그인` ON, `talk_message` 선택 동의는 이미 진행한 설정을 유지합니다.
4. 해당 앱의 `앱 → 플랫폼 키 → REST API 키`에서 REST API 키와 **Client Secret**을 확인합니다. 현재 카카오 앱은 Client Secret이 기본 활성화일 수 있습니다.
5. 같은 화면에서 카카오 로그인 **리다이렉트 URI**에 `http://localhost:8787/callback`을 추가하고, 카카오의 제품 링크 웹 도메인 설정에 `https://scp8232-sketch.github.io`를 등록합니다. 사이트의 실제 주소는 `https://scp8232-sketch.github.io/boram-morning-cardnews/`입니다.
6. **처음 한 번만** 본인 PC에서 Python 3 설치 후 `pip install requests`를 실행하고, `python scripts/kakao_authorize.py`를 실행해 카카오 로그인을 진행합니다. 이 스크립트는 REST API 키/Client Secret을 숨겨 입력받고, 메시지 전송에 동의한 뒤 GitHub Secret에 넣을 refresh token을 터미널에 표시합니다. **터미널 전체 화면/토큰을 캡처하지 마세요.** 받은 토큰은 아래 Secret에만 저장합니다.
7. GitHub 저장소 `Settings → Secrets and variables → Actions`에 **다음 네 개를 정확히 등록**합니다.
   - `GEMINI_API_KEY`: Google AI Studio 키
   - `KAKAO_REST_API_KEY`: 카카오 REST API 키
   - `KAKAO_CLIENT_SECRET`: 카카오 Client Secret
   - `KAKAO_REFRESH_TOKEN`: 6번에서 받은 refresh token
8. GitHub 저장소 `Settings → Pages → Build and deployment → Source`에서 **GitHub Actions**를 선택합니다.
9. `Settings → Actions → General → Workflow permissions`의 기본 `GITHUB_TOKEN`에 **Read and write permissions**를 허용합니다. 공개 저장소의 `docs/` 이미지를 액션이 커밋해 웹에서 공개하기 위함입니다. `Pages`에 필요한 권한도 워크플로에 선언되어 있습니다.
10. 저장소의 `Actions → 이보람의 평일 아침 카드뉴스 → Run workflow`로 처음 수동 실행해 봅니다. `Pages`의 공개 URL에 두 장의 이미지가 나타나고, 카카오톡 `나와의 채팅`에 **두 개의 미리보기+원본 링크**가 도착해야 완료입니다. 처음 실행이 성공하기 전에는 자동 발송이 연결되었다고 간주하지 마세요.

### 정기 실행

- 기본 예약은 **한국 시간 월~금 오전 5시 34분 시작**입니다. `morning.yml`의 `34 20 * * 0-4`는 UTC 일~목 20:34로, 한국의 다음날 월~금 05:34에 해당합니다.
- GitHub Actions 무료 예약 실행은 **지연 또는 누락될 수 있어 06:30 이전 도착을 보장하지 않습니다.** 프로젝트에 더 높은 안정성이 필요하면 별도 유료 실행 환경을 검토해야 합니다.
- GitHub 무료 공개 저장소에서 예약 워크플로는 60일간 활동이 없으면 비활성화될 수 있으므로 관리가 필요합니다. 자동 생성된 커밋 등 활동 상태를 확인하세요.
- 카카오 API 제공 범위에서 메시지 전송은 *사진 파일 첨부*가 아니라 **이미지 미리보기와 이미지 원본 링크**를 보내는 형태입니다.

## 데이터 정확성 / 현재 한계

- 뉴스: Google 뉴스 RSS에 게시된 제목, 출처, 발행일, 스니펫을 가져옵니다. AI는 자료에 **직접 적힌 범위만** 요약하도록 제한되지만, 사람의 기사 본문 검증을 대체하지 못합니다. 뉴스 원문 링크는 날짜별 페이지에서 확인하세요.
- 날씨: 현재는 **Open-Meteo 예보**를 쓰며 **기상청 공식 발표가 아닙니다**. 서울/대전/광주/대구/부산의 최저/최고기온과 강수확률입니다. 기상특보는 아직 포함하지 않습니다.
- 증시·환율: Yahoo Finance **참고시세**로, KRX/은행의 공식 고시와 차이가 날 수 있습니다. 조회 실패 시 `확인 불가`로 표시합니다.
- 휘발유·경유 및 금 거래가: 공식 원문 인증 연결이 아직 없으므로 `확인 불가`로 처리합니다. **숫자를 임의로 채우지 않습니다.**
- AI API 무료 한도와 카카오 정책은 바뀔 수 있습니다. 무료 범위에서 실패할 때에는 원인 확인이 필요합니다. Gemini 무료 티어에 제출한 데이터는 서비스 개선 등에 사용될 수 있으니 개인정보를 입력하지 않습니다.
- GitHub Pages에 발행된 두 카드/소스 링크는 **공개 URL**입니다. 민감 정보·고객정보를 포함하지 마세요.

## 로컬 데모

아래 데모는 **실제 뉴스가 아닌 가상 제목**만 사용하며 카드 오른쪽에 `데모 시안` 표시가 있습니다. 실제 정기 발행에는 해당 문구가 없습니다.

```bash
pip install -r requirements.txt
RUN_DEMO=1 python -m src.automation
```

Windows PowerShell에서는 `RUN_DEMO=1` 대신 `$env:RUN_DEMO="1"; python -m src.automation`을 사용합니다. 결과는 `docs/demo/`에 생성됩니다. 테스트 파일을 실제 뉴스라고 공유하지 마세요.

## 기술 구조

`src/sources.py` RSS·날씨·참고 시세 수집, `src/automation.py` Gemini 요약 및 페이지 생성, `src/render.py` PIL을 통한 1080x1900 PNG 두 장 생성(네 귀퉁이 투명), `src/send_kakao.py` 이미지 링크 발송·토큰 자동 갱신 및 암호화, `scripts/kakao_authorize.py` 최초 로그인 도우미, `.github/workflows/morning.yml` 평일 예약 실행.

참고 공식 문서: [카카오 나에게 기본 템플릿 메시지 발송](https://developers.kakao.com/docs/ko/kakaotalk-message/rest-api), [카카오 로그인 토큰 갱신](https://developers.kakao.com/docs/ko/kakaologin/rest-api), [GitHub Pages Actions 배포](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site), [Gemini 요금 및 무료 모델](https://ai.google.dev/gemini-api/docs/pricing).
