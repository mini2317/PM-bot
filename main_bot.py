import discord
from discord.ext import commands
import os
import io
import re
import aiohttp
from aiohttp import web

# 모듈화된 DB 및 AI
from database import DBManager
from ai_helper import AIHelper
from utils import smart_chunk_text
from ui import EmbedPaginator

# [설정]
def load_key(f):
    try: return open(f"src/key/{f}", "r", encoding="utf-8").read().strip()
    except: return None

DISCORD_TOKEN = load_key("bot_token")
GEMINI_API_KEY = load_key("gemini_key")
GITHUB_TOKEN = load_key("github_key")
OWNER_ID = load_key("owner_id")
WEBHOOK_PORT = 8080

# [초기화]
intents = discord.Intents.default(); intents.message_content=True; intents.members=True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
bot.db = DBManager()
bot.ai = AIHelper(GEMINI_API_KEY)
bot.github_headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

# [Webhook]
async def get_diff(url):
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=bot.github_headers) as r:
            if r.status==200:
                d=await r.json(); l=[]
                for f in d.get('files',[]):
                    if not f.get('patch'): l.append(f"📄 {f['filename']} (No Patch)")
                    else: l.append(f"📄 {f['filename']}\n{f['patch'][:2000]}")
                return "\n".join(l)
    return None

async def proc_webhook(d):
    if 'repository' not in d: return
    rn = d['repository']['full_name']
    cids = bot.db.get_repo_channels(rn)
    if not cids: return
    for c in d.get('commits', []):
        msg = f"🚀 `{rn}` Commit: `{c['id'][:7]}`\n{c['message']}"
        closed = []
        for t in re.findall(r'(?:fix|close|resolve)\s*#(\d+)', c['message'], re.IGNORECASE):
            if bot.db.update_task_status(int(t),"DONE"): closed.append(t)
        if closed: msg += f"\n✅ Closed: {', '.join(closed)}"
        
        diff = await get_diff(f"https://api.github.com/repos/{rn}/commits/{c['id']}")
        review_file = None; review_embeds = []
        if diff:
            review = await bot.ai.review_code(rn, c['author']['name'], c['message'], diff)
            review_file = io.BytesIO(f"# Review\n{review}".encode())
            chunks = smart_chunk_text(review)
            for i, ch in enumerate(chunks):
                e = discord.Embed(title="🤖 Review", description=ch, color=0x2ecc71)
                e.set_footer(text=f"{i+1}/{len(chunks)}")
                review_embeds.append(e)
        
        for cid in cids:
            ch = bot.get_channel(cid)
            if ch:
                try:
                    f = discord.File(io.BytesIO(review_file.getvalue()), filename="Review.md") if review_file else None
                    if review_embeds:
                        if len(review_embeds)>1: await ch.send(msg, embed=review_embeds[0], view=EmbedPaginator(review_embeds), file=f)
                        else: await ch.send(msg, embed=review_embeds[0], file=f)
                    else: await ch.send(msg)
                except: pass

async def wh_handler(r):
    if r.method=='GET': return web.Response(text="OK")
    try: d=await r.json(); bot.loop.create_task(proc_webhook(d)); return web.Response(text="OK")
    except: return web.Response(status=500)

async def start_server():
    app=web.Application(); app.router.add_route('*', "/github-webhook", wh_handler)
    r=web.AppRunner(app); await r.setup(); s=web.TCPSite(r,'0.0.0.0',WEBHOOK_PORT); await s.start()
    print(f"🌍 Webhook: {WEBHOOK_PORT}")

@bot.event
async def on_ready():
    print(f'Logged in {bot.user}')
    # Cogs 로드
    for e in ["cogs.meeting", "cogs.project", "cogs.github", "cogs.admin", "cogs.help"]:
        try: await bot.load_extension(e)
        except Exception as err: print(f"Load {e} fail: {err}")
    # 슬래시 커맨드 동기화
    await bot.tree.sync()
    if OWNER_ID:
        try: 
            u = await bot.fetch_user(int(OWNER_ID))
            bot.db.ensure_admin(u.id, u.name)
        except: pass
    await start_server()

if __name__ == "__main__":
    if DISCORD_TOKEN: bot.run(DISCORD_TOKEN)