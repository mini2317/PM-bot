# 🧠 Pynapse - AI Project Manager Bot

**Pynapse**는 Discord 내에서 프로젝트 관리, 회의록 정리, 코드 리뷰, 그리고 업무 자동화를 수행하는 올인원 AI 봇입니다.
Google Gemini 또는 Groq(Llama3)를 기반으로 작동하며, 사용자의 자연어를 이해하여 복잡한 명령을 수행합니다.

# ✨ 주요 기능
## 1. 📋 프로젝트 및 할 일 관리
- **계층형 프로젝트 구조**: 프로젝트 간 상하 관계 설정 가능.
- **할 일 관리**: 할 일 등록, 담당자 배정, 진행 상태 관리.
- **실시간 현황판**: `/현황판설정`을 통해 채널에 고정된 실시간 칸반 보드 제공.

## 2. 🎙️ AI 스마트 회의록
- **회의 스레드 자동화**: `/회의 시작` 시 전용 스레드 생성.
- **자동 요약 및 분석**: 회의 종료 시 AI가 대화 내용을 분석하여 요약, 할 일 추출, 역할 분담 제안을 수행.
- **인터랙티브 플로우**: AI의 제안을 버튼 클릭으로 승인/수정하여 DB에 반영.

## 3. 🐙 GitHub 연동 및 코드 리뷰
- **웹훅 연동**: Push 발생 시 실시간 알림.
- **AI 코드 리뷰**: 변경 사항을 분석하여 개선점, 버그 위험 등을 리포팅.
- **PDF 보고서**: 긴 리뷰 내용은 깔끔한 PDF 파일로 생성하여 첨부.
- **자동 업데이트**: 봇의 레포지토리에 Push가 발생하면 스스로 코드 업데이트 후 재시작.

# 🛠️ 설치 및 실행 방법
## 1. 필수 요구 사항
- Python 3.10 이상
- Discord Bot Token
- Google Gemini API Key
- Groq API Key

## 2. 프로젝트 클론 및 패키지 설치
```bash
git clone [https://github.com/YOUR_ID/PM-bot.git](https://github.com/YOUR_ID/PM-bot.git)
cd PM-bot
python3 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 3. API 키 및 설정 파일 생성
보안을 위해 키 값은 소스 코드가 아닌 별도 파일로 관리합니다. `src/key/` 폴더를 만들고 아래 파일들을 생성하세요.
- `src/key/bot_token`: 디스코드 봇 토큰
- `src/key/gemini_key`: Google Gemini API 키
- `src/key/github_key`: Github Personal Access Token (Repo 읽기 권한)
- `src/key/owner_id`: 관리자(본인)의 디스코드 유저 ID (숫자)
- `src/key/groq_key` : Groq API 사용 시 필요
- `src/config.json` 설정 (모델 선택)
```json
{
  "ai_provider": "gemini", 
  "ai_model": "gemini-1.5-pro",
  "groq_model": "llama-3.3-70b-versatile",
  "bot_repo": "Github유저명/레포지토리명"
}
```

## 4. 실행
```bash
python main_bot.py
```
# 📡 GitHub Webhook 설정
코드 리뷰 및 자동 업데이트 기능을 사용하려면 GitHub 저장소에 웹훅을 등록해야 합니다.
1. GitHub 저장소 -> **Settings** -> **Webhooks** -> **Add webhook**
2. **Payload URL**: `http://<서버_IP>:8080/github-webhook`
3. **Content type**: `application/json` **(필수)**
4. **Which events?**: `Just the push event` 선택
5. **Active** 체크 후 저장.

# 💬 명령어 목록 (Slash Command)
모든 명령어는 `/` (슬래시)로 시작합니다.

|카테고리|명령어|설명|
|---|---|---|
|**📋 프로젝트**|`/프로젝트 생성`|새 프로젝트 생성|
||`/할일등록`|할 일 추가 (프로젝트 지정 가능)|
||`/현황판`|할 일 목록 조회|
||`/현황판설정`|현재 채널에 고정형 대시보드 생성|
|**🎙️ 회의**|`/회의 시작`|회의 기록용 스레드 생성|
||`/회의 종료`|(스레드 내에서) 회의 종료 및 AI 분석 시작|
||`/회의 목록`|저장된 회의록 조회|
|**🐙 깃헙**|`/레포등록`|현재 채널에 GitHub 레포지토리 알림 연결|
||`/레포삭제`|연결 해제|

# 🛠️ 서버용 설치 방법

setup.sh 스크립트를 통해 패키지 설치, API 키 설정, 서비스 등록까지 한 번에 완료할 수 있습니다.
1. 프로젝트 클론
```bash
git clone [https://github.com/YOUR_ID/PM-bot.git](https://github.com/YOUR_ID/PM-bot.git)
cd PM-bot
```
2. 자동 설치 스크립트 실행
스크립트가 실행되면 API 키(토큰) 입력을 요청합니다. 미리 준비해주세요.
- Discord Bot Token
- Google Gemini API Key
- Github Personal Access Token
- Owner ID (관리자 디스코드 ID)

# 실행 권한 부여 및 설치 시작 (관리자 권한 필요 시 비밀번호 입력)
```bash
chmod +x setup.sh
./setup.sh
```

# ⚙️ 관리 및 유지보수
setup.sh를 통해 Systemd 서비스로 등록되었으므로, 서버가 재부팅되어도 봇은 자동으로 실행됩니다.

봇 상태 확인: sudo systemctl status pynapse

봇 재시작: sudo systemctl restart pynapse

실시간 로그 확인: journalctl -u pynapse -f