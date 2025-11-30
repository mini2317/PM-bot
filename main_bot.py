import discord
from discord.ext import commands
import os
import aiohttp
from aiohttp import web
import asyncio
import re
import io
import json

from database import DBManager
from ai_helper import AIHelper
from ui_components import EmbedPaginator
from utils import smart_chunk_text

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

# 전역 객체 할당 (Cog에서 접근 가능하도록)
bot.db = DBManager()
bot.ai = AIHelper(GEMINI_API_KEY)
bot.github_headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

# [Webhook Logic - 글로벌 유지]
# 웹훅 처리는 봇의 핵심 이벤트 루프와 강하게 결합되어 있어 메인에 두는 것이 안정적입니다.
async def get_github_diff(api_url):
    print(f"[DEBUG] Diff: {api_url}")
    async with aiohttp.ClientSession() as s:
        async with s.get(api_url, headers=bot.github_headers) as r:
            if r.status==200:
                d = await r.json(); lines = []
                ignores = ['lock', '.png', '.jpg', '.svg', '.pdf']
                for f in d.get('files', []):
                    fn = f['filename']
                    if any(x in fn for x in ignores): lines.append(f"📄 {fn} (Skip)")
                    elif not f.get('patch'): lines.append(f"📄 {fn} (No Patch)")
                    else:
                        p = f['patch']
                        if len(p)>2500: p=p[:2500]+"\n...(Trunc)"
                        lines.append(f"📄 {fn}\n{p}")
                return "\n".join(lines)
    return None

async def process_webhook(data):
    if 'repository' not in data: return
    rn = data['repository']['full_name']
    cids = bot.db.get_repo_channels(rn)
    if not cids: return
    
    for c in data.get('commits', []):
        msg = f"🚀 `{rn}` Commit: `{c['id'][:7]}`\n{c['message']}"
        closed = []
        for t in re.findall(r'(?:fix|close|resolve)\s*#(\d+)', c['message'], re.IGNORECASE):
            if bot.db.update_task_status(int(t),"DONE"): closed.append(t)
        if closed: msg += f"\n✅ Closed: {', '.join(closed)}"
        
        diff = await get_github_diff(f"https://api.github.com/repos/{rn}/commits/{c['id']}")
        review_file = None
        review_embeds = []

        if diff and len(diff.strip()) > 0:
            review = await bot.ai.review_code(rn, c['author']['name'], c['message'], diff)
            review_file = io.BytesIO(f"# Review: {rn}\n\n{review}".encode())
            chunks = smart_chunk_text(review)
            for i, ch in enumerate(chunks):
                e = discord.Embed(title="🤖 Review", description=ch, color=0x2ecc71)
                e.set_footer(text=f"{i+1}/{len(chunks)}")
                review_embeds.append(e)
        
        for cid in cids:
            ch = bot.get_channel(cid)
            if ch:
                try:
                    await ch.send(msg)
                    if review_embeds:
                        f = discord.File(io.BytesIO(review_file.getvalue()), filename="Review.md")
                        if len(review_embeds)>1: 
                            await ch.send(embed=review_embeds[0], view=EmbedPaginator(review_embeds), file=f)
                        else: 
                            await ch.send(embed=review_embeds[0], file=f)
                    elif diff is None:
                        await ch.send(embed=discord.Embed(title="⚠️ 분석 생략", description="변경량이 너무 많습니다.", color=0xe74c3c))
                except Exception as e: print(f"Err {cid}: {e}")

async def webhook_handler(r):
    if r.method=='GET': return web.Response(text="OK")
    try: d=await r.json(); bot.loop.create_task(process_webhook(d)); return web.Response(text="OK")
    except: return web.Response(status=500)

async def start_server():
    app=web.Application(); app.router.add_route('*', WEBHOOK_PATH, webhook_handler)
    r=web.AppRunner(app); await r.setup(); s=web.TCPSite(r,'0.0.0.0',WEBHOOK_PORT); await s.start()
    print(f"🌍 Webhook: {WEBHOOK_PORT}")

# [Bot Start]
@bot.event
async def on_ready():
    print(f'Logged in {bot.user}')
    
    # Load Cogs
    await bot.load_extension("cogs.meeting")
    await bot.load_extension("cogs.project")
    await bot.load_extension("cogs.github")
    await bot.load_extension("cogs.admin")
    await bot.load_extension("cogs.help")
    print("✅ All Cogs Loaded")

    # Owner Auto-Register
    if OWNER_ID:
        try:
            u = await bot.fetch_user(int(OWNER_ID))
            if bot.db.ensure_admin(u.id, u.name): print(f"✅ Owner {u.name} registered")
        except: print("⚠️ Owner register failed")
        
    await start_server()

if __name__ == "__main__":
    if DISCORD_TOKEN: bot.run(DISCORD_TOKEN)