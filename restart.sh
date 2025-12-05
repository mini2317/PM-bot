git fetch --all
git reset --hard origin/main
sudo systemctl daemon-reload
sudo systemctl restart pynapse
echo "봇 재시작 완료"