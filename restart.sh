git fetch --all
git reset --hard origin/main
source .venv/bin/activate
pip uninstall discord discord.py -y
pip install -r requirements.txt
sudo systemctl daemon-reload
sudo systemctl restart pynapse
echo "✅ 봇이 성공적으로 재시작되었습니다."