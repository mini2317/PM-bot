import sys
import types

# [Patch] Python 3.13+ compatibility
if sys.version_info >= (3, 13):
    try:
        import audioop
    except ImportError:
        mock_audioop = types.ModuleType("audioop")
        class error(Exception): pass
        mock_audioop.error = error
        sys.modules["audioop"] = mock_audioop

import discord
from discord.ext import commands
import os
import json
import datetime

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
GROQ_API_KEY = load_key("groq_key")

WEBHOOK_PORT = 8080
WEBHOOK_PATH = "/github-webhook"

# [초기화]
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
bot.db = DBManager()
bot.ai = AIHelper(GEMINI_API_KEY, GROQ_API_KEY)
bot.github_headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

# 웹훅 서버 인스턴스 생성
webhook_server = WebhookServer(bot, port=WEBHOOK_PORT, path=WEBHOOK_PATH)

# [Bot Start]
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    
    # Load Cogs
    exts = ["cogs.meeting", "cogs.project", "cogs.github", "cogs.admin", "cogs.help"]
    for e in exts: 
        try: await bot.load_extension(e)
        except Exception as err: print(f"Failed to load {e}: {err}")
    
    # Sync Slash Commands
    try:
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"⚠️ Sync failed: {e}")

    # [UPDATE] Owner 등록 및 구동 알림 DM 전송
    if OWNER_ID:
        try:
            u = await bot.fetch_user(int(OWNER_ID))
            
            # 1. 관리자 DB 등록
            if bot.db.ensure_admin(u.id, u.name): 
                print(f"✅ Owner {u.name} registered")
            
            # 2. 구동 정보 DM 전송
            conf = bot.ai.config
            provider = conf.get('ai_provider', 'Unknown')
            
            # 현재 사용 중인 모델 확인
            current_model = "Unknown"
            if provider == 'gemini':
                current_model = conf.get('ai_model', 'Default Gemini')
            elif provider == 'groq':
                current_model = conf.get('groq_model', 'Default Groq')

            embed = discord.Embed(title="🟢 Pynapse System Online", color=discord.Color.brand_green())
            embed.add_field(name="🤖 AI Provider", value=f"`{provider.upper()}`", inline=True)
            embed.add_field(name="🧠 Active Model", value=f"`{current_model}`", inline=True)
            embed.add_field(name="📡 Webhook Port", value=f"`{WEBHOOK_PORT}`", inline=True)
            embed.set_footer(text=f"Logged in as {bot.user.name} | {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            await u.send(embed=embed)
            print(f"📨 Startup notification sent to owner ({u.name})")

        except Exception as e: 
            print(f"⚠️ Owner setup/notification failed: {e}")
    
    # Start Webhook Server
    await webhook_server.start()

if __name__ == "__main__":
    if DISCORD_TOKEN: bot.run(DISCORD_TOKEN)