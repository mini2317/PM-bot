#!/bin/bash

# 스크립트 실행 중 에러 발생 시 중단
set -e

echo "🚀 Pynapse Bot 초기 설정 시작..."
CURRENT_USER=$(whoami)
PROJECT_DIR=$(pwd)

# 1. 권한 및 소유권 정리
echo "🔑 1. 파일 권한 및 소유권 설정..."
sudo chown -R $CURRENT_USER:$CURRENT_USER .
chmod +x *.sh
git config --global --add safe.directory $PROJECT_DIR

# 2. 시스템 패키지 업데이트
echo "📦 2. 시스템 패키지 확인..."
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip

# 3. Python 가상환경 설정
echo "🐍 3. 가상환경(.venv) 설정..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "   - 가상환경 생성 완료"
else
    echo "   - 가상환경이 이미 존재합니다."
fi

# 4. 라이브러리 설치
echo "📚 4. Python 라이브러리 설치..."
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

# 5. 필수 디렉토리 및 키 파일 설정
echo "📁 5. 디렉토리 구조 및 API 키 설정..."
mkdir -p src/key
mkdir -p src/fonts

KEYS=("bot_token" "gemini_key" "github_key" "groq_key" "owner_id")

for KEY in "${KEYS[@]}"; do
    FILE_PATH="src/key/$KEY"
    if [ ! -f "$FILE_PATH" ]; then
        echo ""
        echo "👉 '$KEY' 파일이 없습니다."
        if [ "$KEY" == "owner_id" ]; then
            echo "   (관리자 디스코드 유저 ID 숫자)"
        fi
        read -p "   값을 입력하세요 (Enter시 건너뜀): " KEY_VALUE
        
        if [ -n "$KEY_VALUE" ]; then
            echo "$KEY_VALUE" > "$FILE_PATH"
            echo "   ✅ $KEY 저장 완료"
        else
            echo "   ⚠️ $KEY 생성 건너뜀"
        fi
    else
        echo "   ✅ $KEY 이미 존재함"
    fi
done
echo ""

# 6. Systemd 서비스 등록
echo "⚙️ 6. Systemd 서비스 등록..."
SERVICE_FILE="pynapse.service"

cat <<EOF > $SERVICE_FILE
[Unit]
Description=Pynapse Discord Bot
After=network.target

[Service]
User=$CURRENT_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/.venv/bin/python main_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo "   - 서비스 파일 이동 (/etc/systemd/system/)"
sudo mv $SERVICE_FILE /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pynapse
sudo systemctl restart pynapse

echo "----------------------------------------------------"
echo "✅ 설정 완료!"
echo "----------------------------------------------------"
echo ""
echo "👀 상태 확인: sudo systemctl status pynapse"