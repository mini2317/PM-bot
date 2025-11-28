import discord
from discord.ext import commands
from discord.ui import View, Button
import os
import aiohttp
from aiohttp import web
import asyncio
import re
from database import DBManager
from ai_helper import AIHelper
import datetime

# [1. 설정]
def load_key(filename):
    base_path = "src/key"
    path = os.path.join(base_path, filename)
    try:
        with open(path, "r", encoding="utf-8") as f: return f.read().strip()
    except: return None

DISCORD_TOKEN = load_key("bot_token")
GEMINI_API_KEY = load_key("gemini_key")
GITHUB_TOKEN = load_key("github_key")

WEBHOOK_PORT = 8080
WEBHOOK_PATH = "/github-webhook"

db = DBManager()
ai = AIHelper(GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
meeting_buffer = {} 

github_headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

# [UI]
class HelpPaginator(View):
    def __init__(self, embeds):
        super().__init__(timeout=60)
        self.embeds = embeds
        self.current_page = 0
        self.update_buttons()
    def update_buttons(self):
        self.children[0].disabled = (self.current_page == 0)
        self.children[1].disabled = (self.current_page == len(self.embeds) - 1)
    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction, button):
        self.current_page -= 1; self.update_buttons(); await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)
    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):
        self.current_page += 1; self.update_buttons(); await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

def check_permission():
    async def predicate(ctx):
        if db.is_authorized(ctx.author.id): return True
        await ctx.send("🚫 권한 없음"); return False
    return commands.check(predicate)

# [관리자/레포/할일 명령어] (이전과 동일하지만 코드를 완성형으로 제공)
@bot.command(name="초기설정")
async def init_admin(ctx):
    if db.add_user(ctx.author.id, ctx.author.name, "admin"): await ctx.send(f"👑 {ctx.author.mention} 관리자 등록")
    else: await ctx.send("이미 존재")

@bot.command(name="권한추가")
@check_permission()
async def add_auth(ctx, m: discord.Member):
    if db.add_user(m.id, m.name): await ctx.send(f"✅ {m.mention} 권한 부여")
    else: await ctx.send("이미 권한 있음")

@bot.command(name="권한삭제")
@check_permission()
async def rem_auth(ctx, m: discord.Member):
    if db.remove_user(m.id): await ctx.send(f"🗑️ {m.mention} 권한 회수")
    else: await ctx.send("미등록 유저")

@bot.command(name="레포등록")
@check_permission()
async def add_repo(ctx, r: str):
    if db.add_repo(r, ctx.channel.id, ctx.author.name): await ctx.send(f"✅ {r} 연결")
    else: await ctx.send("실패")

@bot.command(name="레포삭제")
@check_permission()
async def rem_repo(ctx, r: str):
    if db.remove_repo(r): await ctx.send(f"🗑️ {r} 해제")
    else: await ctx.send("미등록")

@bot.command(name="레포목록")
@check_permission()
async def list_repo(ctx):
    rows = db.get_all_repos()
    if not rows: await ctx.send("📭 없음"); return
    e = discord.Embed(title="🐙 Repos", color=0x6e5494)
    for r, c in rows: e.add_field(name=r, value=f"<#{c}>", inline=False)
    await ctx.send(embed=e)

@bot.command(name="할일등록")
@check_permission()
async def add_task(ctx, p: str, *, c: str):
    tid = db.add_task(p, c); await ctx.send(f"✅ [{p}] 할일 등록 (ID: {tid})")

@bot.command(name="현황판")
@check_permission()
async def status(ctx, p: str = None):
    ts = db.get_tasks(p)
    if not ts: await ctx.send("📭 없음"); return
    todo, prog, done = [], [], []
    for t in ts:
        tid, pn, ct, aid, an, st, dt, mid = t
        assign = f"@{an}" if an else "미정"
        mark = "🎙️" if mid else ""
        line = f"**#{tid}** [{pn}] {ct} (👤{assign}) {mark}"
        if st=="TODO": todo.append(line)
        elif st=="IN_PROGRESS": prog.append(line)
        else: done.append(line)
    e = discord.Embed(title=f"📊 {p if p else '전체'} 현황", color=0xf1c40f)
    e.add_field(name=f"대기 ({len(todo)})", value="\n".join(todo) if todo else "-", inline=False)
    e.add_field(name=f"진행 ({len(prog)})", value="\n".join(prog) if prog else "-", inline=False)
    e.add_field(name=f"완료 ({len(done)})", value="\n".join(done) if done else "-", inline=False)
    await ctx.send(embed=e)

@bot.command(name="완료")
@check_permission()
async def done_task(ctx, tid: int):
    if db.update_task_status(tid, "DONE"): await ctx.message.add_reaction("✅")
    else: await ctx.send("❌ 실패")

@bot.command(name="담당")
@check_permission()
async def assign(ctx, tid: int, m: discord.Member):
    if db.assign_task(tid, m.id, m.name): await ctx.send(f"👤 #{tid} 담당: {m.mention}")
    else: await ctx.send("❌ 실패")


# [회의록 시스템 (수정됨)]
@bot.command(name="회의시작")
@check_permission()
async def start_meeting(ctx, *, meeting_name: str = None):
    if ctx.channel.id in meeting_buffer:
        await ctx.send("🔴 이미 회의 진행 중")
        return
    if not meeting_name:
        meeting_name = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} 회의 (진행 중)"
    
    # [변경] 메시지 버퍼를 리스트로 초기화 (객체 저장용)
    meeting_buffer[ctx.channel.id] = {'name': meeting_name, 'messages': [], 'jump_url': ctx.message.jump_url}
    
    embed = discord.Embed(title="🎙️ 회의 시작", color=0xe74c3c)
    embed.add_field(name="상태", value="🔴 녹음 중", inline=True)
    embed.add_field(name="제목", value=meeting_name, inline=True)
    embed.set_footer(text="!회의종료 시 자동 저장 및 요약")
    await ctx.send(embed=embed)

@bot.command(name="회의종료")
@check_permission()
async def stop_meeting(ctx):
    if ctx.channel.id not in meeting_buffer:
        await ctx.send("⚠️ 회의 중 아님")
        return

    data = meeting_buffer.pop(ctx.channel.id)
    raw_messages = data['messages'] # List of dicts
    
    if not raw_messages:
        await ctx.send("📝 대화 없음")
        return

    # [변경] AI에게 보낼 구조화된 문자열 생성
    formatted_transcript = ""
    for msg in raw_messages:
        # msg = {'time': '...', 'user': '...', 'content': '...'}
        formatted_transcript += f"[Speaker: {msg['user']} | Time: {msg['time']}] {msg['content']}\n"

    waiting = await ctx.send("🤖 회의 분석 중...")

    # AI 호출
    full_result = await ai.generate_meeting_summary(formatted_transcript)
    
    lines = full_result.strip().split('\n')
    if lines[0].startswith("제목:"):
        final_title = lines[0].replace("제목:", "").strip()
        summary = "\n".join(lines[1:]).strip()
    else:
        final_title = f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
        summary = full_result

    # DB 저장 (transcript 제외, summary만 저장)
    m_id = db.save_meeting(ctx.guild.id, final_title, ctx.channel.id, summary, data['jump_url'])

    # 할일 추출
    tasks = await ai.extract_tasks_from_meeting(formatted_transcript)
    task_txt = ""
    for t in tasks:
        content = t.get('content', '')
        assignee = t.get('assignee_hint', '')
        tid = db.add_task("회의도출", content, source_meeting_id=m_id)
        task_txt += f"• **#{tid}** {content} (추정: {assignee})\n"

    await waiting.delete()

    embed = discord.Embed(title=f"✅ 종료: {final_title}", color=0x2ecc71)
    embed.add_field(name="요약", value=summary[:500] + "...", inline=False)
    if task_txt: embed.add_field(name="도출된 할일", value=task_txt, inline=False)
    embed.add_field(name="관리", value=f"ID: `{m_id}` | `!회의조회 {m_id}`", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="회의목록")
@check_permission()
async def list_meetings(ctx):
    rows = db.get_recent_meetings(ctx.guild.id)
    if not rows: await ctx.send("📭 없음"); return
    e = discord.Embed(title=f"📂 {ctx.guild.name} 회의록", color=0xf1c40f)
    for rid, name, date, smry, link in rows:
        e.add_field(name=f"[{rid}] {name}", value=f"📅 {date} | [이동]({link})", inline=False)
    await ctx.send(embed=e)

@bot.command(name="회의조회")
@check_permission()
async def view_meeting(ctx, mid: int):
    # [변경] transcript 반환받지 않음
    row = db.get_meeting_detail(mid, ctx.guild.id)
    if not row: await ctx.send("❌ 없음"); return
    name, date, summary, link = row
    msg = f"**📂 {name} ({date})**\n🔗 [이동]({link})\n\n{summary}"
    await ctx.send(msg)

@bot.command(name="회의삭제")
@check_permission()
async def del_meeting(ctx, mid: int):
    if db.delete_meeting(mid, ctx.guild.id): await ctx.send(f"🗑️ #{mid} 삭제")
    else: await ctx.send("❌ 실패")


# [Webhook & Run]
async def webhook_handler(r):
    if r.method=='GET': return web.Response(text="🟢 Bot OK")
    try:
        d = await r.json(); bot.loop.create_task(process_webhook(d)); return web.Response(text="OK")
    except: return web.Response(status=500)

async def process_webhook(d):
    if 'repository' not in d: return
    rn = d['repository']['full_name']
    cid = db.get_repo_channel(rn)
    if not cid: return
    ch = bot.get_channel(cid)
    if not ch: return
    for c in d.get('commits',[]):
        msg = f"🚀 **Push** `{rn}`\nMsg: `{c['message']}`"
        matches = re.findall(r'(?:fix|close|resolve)\s*#(\d+)', c['message'], re.IGNORECASE)
        if matches:
            closed = []
            for t in matches:
                if db.update_task_status(int(t),"DONE"): closed.append(t)
            if closed: msg += f"\n✅ Closed: {', '.join(closed)}"
        await ch.send(msg)
        diff = await get_diff(c['url'])
        if diff:
            rev = await ai.review_code(rn, c['author']['name'], c['message'], diff)
            e = discord.Embed(title="🤖 Review", description=rev[:1000], color=0x2ecc71)
            await ch.send(embed=e)

async def get_diff(url):
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=github_headers) as r:
            if r.status==200: d=await r.json(); return "".join([f"📄 {f['filename']}\n{f.get('patch','')}\n\n" for f in d.get('files',[])])
    return None

async def start_server():
    app = web.Application()
    app.router.add_route('*', WEBHOOK_PATH, webhook_handler)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT); await site.start()
    print(f"🌍 Webhook: {WEBHOOK_PORT}")

@bot.command(name="도움말")
async def help_cmd(ctx):
    e = discord.Embed(title="🤖 명령어", description="!할일등록, !회의시작, !레포등록 등", color=0x3498db)
    await ctx.send(embed=e)

@bot.event
async def on_message(message):
    if message.author.bot: return
    # [변경] 메시지를 구조화된 객체(dict)로 저장
    if message.channel.id in meeting_buffer and not message.content.startswith('!'):
        msg_obj = {
            'time': message.created_at.strftime("%H:%M"),
            'user': message.author.display_name,
            'content': message.content
        }
        meeting_buffer[message.channel.id]['messages'].append(msg_obj)
    await bot.process_commands(message)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await start_server()

if __name__ == "__main__":
    if DISCORD_TOKEN: bot.run(DISCORD_TOKEN)