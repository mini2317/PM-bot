import discord
from discord.ext import commands
import os, asyncio
import aiohttp
from aiohttp import web
import re
import io
import html # HTML 이스케이프용

# PDF 생성 라이브러리
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# 모듈화된 DB 및 AI
from database import DBManager
from ai_helper import AIHelper
from ui import EmbedPaginator
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
bot.db = DBManager()
bot.ai = AIHelper(GEMINI_API_KEY)
bot.github_headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

# ==================================================================
# [PDF 생성 함수]
# ==================================================================
def generate_review_pdf(title, content):
    """
    텍스트 내용을 받아 PDF 파일 버퍼(BytesIO)를 반환합니다.
    한글 폰트(src/fonts/Nanum_Gothic/NanumGothic-Regular.ttf)가 있어야 한글이 깨지지 않습니다.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    
    # 폰트 등록 시도
    font_name = 'Helvetica' # 기본값 (한글 미지원)
    # [변경] 업로드된 경로에 맞춰 수정
    font_path = "src/fonts/Nanum_Gothic/NanumGothic-Regular.ttf"
    try:
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont('NanumGothic', font_path))
            font_name = 'NanumGothic'
        else:
            print(f"⚠️ 경고: 한글 폰트 파일을 찾을 수 없습니다. ({font_path})")
    except Exception as e:
        print(f"⚠️ 폰트 등록 실패: {e}")

    # 스타일 설정
    styles = getSampleStyleSheet()
    
    # 제목 스타일
    style_title = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontName=font_name,
        fontSize=18,
        leading=22,
        spaceAfter=20
    )
    
    # 본문 스타일
    style_body = ParagraphStyle(
        'CustomBody',
        parent=styles['Normal'],
        fontName=font_name,
        fontSize=10,
        leading=16, # 줄 간격
        spaceAfter=10
    )

    story = []
    
    # 1. 제목 추가
    story.append(Paragraph(html.escape(title), style_title))
    
    # 2. 본문 처리 (HTML 이스케이프 및 줄바꿈)
    # reportlab Paragraph는 XML 태그를 사용하므로 텍스트 내 <, > 등을 이스케이프해야 함
    escaped_content = html.escape(content).replace('\n', '<br/>')
    
    # 마크다운 볼드(**)를 PDF 볼드 태그(<b>)로 변환 (간단한 처리)
    escaped_content = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', escaped_content)
    
    story.append(Paragraph(escaped_content, style_body))
    
    # PDF 빌드
    doc.build(story)
    buffer.seek(0)
    return buffer

# ==================================================================
# [Webhook Logic]
# ==================================================================
async def get_github_diff(url):
    print(f"[DEBUG] Diff: {url}")
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=bot.github_headers) as r:
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
        
        diff = await get_github_diff(f"https://api.github.com/repos/{rn}/commits/{c['id']}")
        
        pdf_file = None
        review_embeds = []

        if diff and len(diff.strip()) > 0:
            review = await bot.ai.review_code(rn, c['author']['name'], c['message'], diff)
            
            # [NEW] PDF 생성
            pdf_title = f"Code Review: {rn} ({c['id'][:7]})"
            pdf_content = f"Author: {c['author']['name']}\nMessage: {c['message']}\n\n[Review Content]\n{review}"
            pdf_buffer = await asyncio.to_thread(generate_review_pdf, pdf_title, pdf_content)
            
            # Discord File 객체 준비 (버퍼 값은 전송 시마다 복사해서 써야 함)
            pdf_bytes = pdf_buffer.getvalue() 
            
            # Embed 청킹
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
                        # 채널마다 새로운 파일 객체 생성 (스트림 닫힘 방지)
                        f_send = discord.File(io.BytesIO(pdf_bytes), filename=f"Review_{c['id'][:7]}.pdf")
                        
                        if len(review_embeds) > 1: 
                            await ch.send(embed=review_embeds[0], view=EmbedPaginator(review_embeds), file=f_send)
                        else: 
                            await ch.send(embed=review_embeds[0], file=f_send)
                    elif diff is None:
                        await ch.send(embed=discord.Embed(title="⚠️ 분석 생략", description="변경량이 너무 많습니다.", color=0xe74c3c))
                except Exception as e: print(f"Err {cid}: {e}")

async def wh_handler(r):
    if r.method=='GET': return web.Response(text="OK")
    try: d=await r.json(); bot.loop.create_task(proc_webhook(d)); return web.Response(text="OK")
    except: return web.Response(status=500)

async def start_server():
    app=web.Application(); app.router.add_route('*', WEBHOOK_PATH, wh_handler)
    r=web.AppRunner(app); await r.setup(); s=web.TCPSite(r,'0.0.0.0',WEBHOOK_PORT); await s.start()
    print(f"🌍 Webhook: {WEBHOOK_PORT}")

# [Bot Start]
@bot.event
async def on_ready():
    print(f'Logged in {bot.user}')
    
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

    # Owner Auto-Register
    if OWNER_ID:
        try:
            u = await bot.fetch_user(int(OWNER_ID))
            if bot.db.ensure_admin(u.id, u.name): print(f"✅ Owner {u.name} registered")
        except: print("⚠️ Owner register failed")
        
    await start_server()

if __name__ == "__main__":
    if DISCORD_TOKEN: bot.run(DISCORD_TOKEN)