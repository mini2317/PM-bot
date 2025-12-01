import discord
from discord.ext import commands
import os
import json

# 모듈화된 DB 및 AI
from database import DBManager
from ai_helper import AIHelper
from services.webhook import WebhookServer

# [설정 로드]
def load_key(filename):
    try:
        with open(f"src/key/{filename}", "r", encoding="utf-8") as f: return f.read().strip()
    except: return None

DISCORD_TOKEN = load_key("bot_token")
GEMINI_API_KEY = load_key("gemini_key")
GITHUB_TOKEN = load_key("github_key")
OWNER_ID = load_key("owner_id")

WEBHOOK_PORT = 8080
WEBHOOK_PATH = "/github-webhook"

# [초기화]
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
bot.db = DBManager()
bot.ai = AIHelper(GEMINI_API_KEY)
bot.github_headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

# 웹훅 서버 인스턴스 생성
webhook_server = WebhookServer(bot, port=WEBHOOK_PORT, path=WEBHOOK_PATH)

# [Bot Start]
@bot.event
async def on_ready():
    print(f'Logged in {bot.user}')
    
    # Load Cogs
    exts = ["cogs.meeting", "cogs.project", "cogs.github", "cogs.admin", "cogs.help", "cogs.assistant"]
    for e in exts: 
        try: await bot.load_extension(e)
        except Exception as err: print(f"Failed to load {e}: {err}")
    
    # Sync Slash Commands
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"⚠️ Sync failed: {e}")

    # Owner Auto-Register
    if OWNER_ID:
        try:
            u = await bot.fetch_user(int(OWNER_ID))
            if bot.db.ensure_admin(u.id, u.name): print(f"✅ Owner {u.name} registered")
        except: print("⚠️ Owner register failed")
    
    # Start Webhook Server
    await webhook_server.start()

# [Global Message Handler]
# 회의록 기록을 위해 필요 (Cog 이전에 실행됨)
# 회의 버퍼는 MeetingCog에서 관리하므로, 여기서는 단순 전달만 하거나 제거해도 되지만,
# meeting_buffer가 MeetingCog 내부에 있으므로 main에서는 제거해도 무방합니다.
# MeetingCog의 리스너가 처리합니다.

if __name__ == "__main__":
    if DISCORD_TOKEN: bot.run(DISCORD_TOKEN)