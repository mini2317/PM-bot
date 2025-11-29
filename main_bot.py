import discord
from discord.ext import commands
import os
import aiohttp
from aiohttp import web
import asyncio
import re
import datetime
import json
import io

# 분리된 모듈 임포트
from database import DBManager
from ai_helper import AIHelper
from ui_components import EmbedPaginator, StatusUpdateView, NewProjectView, TaskSelectionView

# ==================================================================
# [1. 설정 및 키 로드]
# ==================================================================
def load_key(filename):
    base_path = "src/key"
    path = os.path.join(base_path, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None

DISCORD_TOKEN = load_key("bot_token")
GEMINI_API_KEY = load_key("gemini_key")
GITHUB_TOKEN = load_key("github_key")
OWNER_ID = load_key("owner_id") # [NEW] 봇 소유자 ID 로드

WEBHOOK_PORT = 8080
WEBHOOK_PATH = "/github-webhook"

# 도움말 데이터 로드
try:
    with open("help_data.json", "r", encoding="utf-8") as f:
        COMMAND_INFO = json.load(f)
except FileNotFoundError:
    COMMAND_INFO = {}

# ==================================================================
# [2. 초기화]
# ==================================================================
db = DBManager()
ai = AIHelper(GEMINI_API_KEY)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)
meeting_buffer = {} 

github_headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# ==================================================================
# [3. 유틸리티 (스마트 청킹)]
# ==================================================================
def smart_chunk_text(text, limit=1500):
    chunks = []
    current_chunk = ""
    in_code_block = False
    code_block_lang = ""

    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 20 > limit:
            if in_code_block:
                chunks.append(current_chunk + "\n```")
                current_chunk = f"```{code_block_lang}\n{line}"
            else:
                chunks.append(current_chunk)
                current_chunk = line
        else:
            if current_chunk: current_chunk += "\n" + line
            else: current_chunk = line
        
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code_block:
                in_code_block = False
                code_block_lang = ""
            else:
                in_code_block = True
                code_block_lang = stripped.replace("```", "").strip()
    
    if current_chunk: chunks.append(current_chunk)
    return chunks

# ==================================================================
# [4. 명령어]
# ==================================================================
def check_permission():
    async def predicate(ctx):
        if db.is_authorized(ctx.author.id): return True
        await ctx.send("🚫 권한 없음"); return False
    return commands.check(predicate)

# !초기설정 삭제됨 (자동화)

@bot.command(name="권한추가")
@check_permission()
async def add_auth(ctx, m: discord.Member):
    if db.add_user(m.id, m.name): await ctx.send(f"✅ {m.mention} 권한 부여")
    else: await ctx.send("이미 있음")

@bot.command(name="권한삭제")
@check_permission()
async def rem_auth(ctx, m: discord.Member):
    if db.remove_user(m.id): await ctx.send(f"🗑️ {m.mention} 권한 회수")
    else: await ctx.send("미등록")

# [프로젝트 관리]
@bot.command(name="프로젝트생성")
@check_permission()
async def create_proj(ctx, name: str):
    if db.create_project(ctx.guild.id, name): await ctx.send(f"🆕 **{name}** 생성 완료")
    else: await ctx.send("❌ 중복된 이름")

@bot.command(name="상위설정")
@check_permission()
async def set_parent(ctx, child: str, parent: str):
    if db.set_parent_project(ctx.guild.id, child, parent): await ctx.send(f"🔗 **{child}** ⊂ **{parent}**")
    else: await ctx.send("❌ 프로젝트 확인 필요")

@bot.command(name="프로젝트구조")
@check_permission()
async def tree_proj(ctx):
    rows = db.get_project_tree(ctx.guild.id)
    if not rows: await ctx.send("📭 없음"); return
    
    nodes = {r[0]: {'name': r[1], 'parent': r[2], 'children': []} for r in rows}
    roots = []
    for pid, node in nodes.items():
        if node['parent'] and node['parent'] in nodes:
            nodes[node['parent']]['children'].append(node)
        else:
            roots.append(node)
    
    def print_node(node, level=0):
        t = f"{'　'*level}📂 **{node['name']}**\n"
        for child in node['children']: t += print_node(child, level+1)
        return t

    txt = "".join([print_node(r) for r in roots])
    await ctx.send(embed=discord.Embed(title=f"🌳 {ctx.guild.name} 구조도", description=txt, color=0x3498db))

@bot.command(name="할일등록")
@check_permission()
async def add_task(ctx, p: str, *, c: str):
    tid = db.add_task(ctx.guild.id, p, c)
    await ctx.send(f"✅ [{p}] 할일 등록 (ID: {tid})")

@bot.command(name="현황판")
@check_permission()
async def status(ctx, p: str = None):
    ts = db.get_tasks(ctx.guild.id, p)
    if not ts: await ctx.send("📭 없음"); return
    todo, prog, done = [], [], []
    for t in ts:
        line = f"**#{t[0]}** [{t[1]}] {t[2]} (👤{t[4] or '미정'})"
        if t[5]=="TODO": todo.append(line)
        elif t[5]=="IN_PROGRESS": prog.append(line)
        else: done.append(line)
    e = discord.Embed(title=f"📊 {p if p else '전체'} 현황", color=0xf1c40f)
    e.add_field(name="대기", value="\n".join(todo) or "-", inline=False)
    e.add_field(name="진행", value="\n".join(prog) or "-", inline=False)
    e.add_field(name="완료", value="\n".join(done) or "-", inline=False)
    await ctx.send(embed=e)

@bot.command(name="완료")
@check_permission()
async def done_task(ctx, tid: int):
    if db.update_task_status(tid, "DONE"): await ctx.message.add_reaction("✅")
    else: await ctx.send("❌ 실패")

@bot.command(name="담당")
@check_permission()
async def assign(ctx, tid: int, m: discord.Member):
    if db.assign_task(tid, m.id, m.name): await ctx.send(f"👤 담당: {m.mention}")
    else: await ctx.send("❌ 실패")

# [회의록 시스템]
@bot.command(name="회의시작")
@check_permission()
async def start_m(ctx, *, name: str = None):
    if ctx.channel.id in meeting_buffer: await ctx.send("🔴 진행 중"); return
    if not name: name = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} 회의 (진행 중)"
    meeting_buffer[ctx.channel.id] = {'name': name, 'messages': [], 'jump_url': ctx.message.jump_url}
    await ctx.send(embed=discord.Embed(title="🎙️ 회의 시작", description=name, color=0xe74c3c))

@bot.command(name="회의종료")
@check_permission()
async def stop_m(ctx):
    if ctx.channel.id not in meeting_buffer: await ctx.send("⚠️ 회의 중 아님"); return
    data = meeting_buffer.pop(ctx.channel.id)
    raw = data['messages']
    if not raw: await ctx.send("📝 대화 없음"); return
    
    txt = "".join([f"[Speaker: {m['user']} | Time: {m['time']}] {m['content']}\n" for m in raw])
    waiting = await ctx.send("🤖 AI 분석 중...")
    
    summary_raw = await ai.generate_meeting_summary(txt)
    lines = summary_raw.strip().split('\n')
    title = lines[0].replace("제목:", "").strip() if lines[0].startswith("제목:") else data['name']
    summary = "\n".join(lines[1:]).strip() if lines[0].startswith("제목:") else summary_raw
    
    mid = db.save_meeting(ctx.guild.id, title, ctx.channel.id, summary, data['jump_url'])
    
    proj_rows = db.get_project_tree(ctx.guild.id)
    id_to_name = {r[0]: r[1] for r in proj_rows}
    struct_txt = "".join([f"- {r[1]} (상위: {id_to_name.get(r[2],'Root')})\n" for r in proj_rows])
    active = db.get_active_tasks_simple(ctx.guild.id)
    
    ai_res = await ai.extract_tasks_and_updates(txt, struct_txt, active)
    new_t = ai_res.get('new_tasks', [])
    updates = ai_res.get('updates', [])
    
    await waiting.delete()
    
    e = discord.Embed(title=f"✅ 종료: {title}", color=0x2ecc71)
    e.add_field(name="요약", value=summary[:500]+"...", inline=False)
    await ctx.send(embed=e)

    async def step3(ch, tasks):
        if not tasks: await ch.send("💡 할일 없음"); return
        await ch.send("📝 **할일 등록:**", view=TaskSelectionView(tasks, mid, ctx.author, ctx.guild.id, db))

    async def step2(ch, tasks):
        new_proj = {}
        for t in tasks:
            if t.get('is_new_project'): new_proj[t['project']] = t.get('suggested_parent')
        
        if new_proj:
            desc = "\n".join([f"• **{k}** (상위: {v or '없음'})" for k, v in new_proj.items()])
            await ch.send(f"🆕 **새 프로젝트 제안**\n{desc}", view=NewProjectView(new_proj, tasks, ctx.author, step3, ctx.guild.id, db))
        else: await step3(ch, tasks)

    if updates:
        await ctx.send("🔄 **상태 변경**", view=StatusUpdateView(updates, ctx.author, lambda c: step2(c, new_t), db))
    else: await step2(ctx.channel, new_t)

@bot.command(name="회의목록")
@check_permission()
async def list_m(ctx):
    rows = db.get_recent_meetings(ctx.guild.id)
    if not rows: await ctx.send("📭 없음"); return
    e = discord.Embed(title=f"📂 {ctx.guild.name} 회의록", color=0xf1c40f)
    for r in rows: e.add_field(name=f"ID [{r[0]}] {r[1]}", value=f"📅 {r[2]} | [이동]({r[4]})", inline=False)
    await ctx.send(embed=e)

@bot.command(name="회의조회")
@check_permission()
async def view_m(ctx, mid: int):
    row = db.get_meeting_detail(mid, ctx.guild.id)
    if not row: await ctx.send("❌ 없음"); return
    name, date, summary, link = row
    
    chunks = smart_chunk_text(summary)
    embeds = []
    for i, chunk in enumerate(chunks):
        e = discord.Embed(title=f"📂 {name} ({date})", description=chunk, color=0xf1c40f)
        if link: e.add_field(name="링크", value=f"[이동]({link})", inline=False)
        if len(chunks)>1: e.set_footer(text=f"{i+1}/{len(chunks)}")
        embeds.append(e)
    
    if len(embeds)>1: await ctx.send(embed=embeds[0], view=EmbedPaginator(embeds, ctx.author))
    else: await ctx.send(embed=embeds[0])

@bot.command(name="회의삭제")
@check_permission()
async def del_m(ctx, mid: int):
    if db.delete_meeting(mid, ctx.guild.id): await ctx.send(f"🗑️ #{mid} 삭제")
    else: await ctx.send("❌ 실패")

# [Github]
@bot.command(name="레포등록")
@check_permission()
async def add_r(ctx, r: str):
    if db.add_repo(r, ctx.channel.id, ctx.author.name): await ctx.send(f"✅ {r} 연결")
    else: await ctx.send("실패")

@bot.command(name="레포삭제")
@check_permission()
async def del_r(ctx, r: str):
    if db.remove_repo(r, ctx.channel.id): await ctx.send(f"🗑️ {r} 해제")
    else: await ctx.send("없음")

@bot.command(name="레포목록")
@check_permission()
async def list_r(ctx):
    rows = db.get_all_repos()
    if not rows: await ctx.send("📭 없음"); return
    e = discord.Embed(title="🐙 Repos", color=0x6e5494)
    for r, c in rows: e.add_field(name=r, value=f"<#{c}>", inline=False)
    await ctx.send(embed=e)

async def get_github_diff(url):
    print(f"DEBUG: Diff {url}")
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=github_headers) as r:
            if r.status==200:
                d = await r.json(); lines = []
                ignores = ['lock', '.png', '.jpg', '.svg', '.pdf']
                for f in d.get('files', []):
                    fn = f['filename']
                    if any(x in fn for x in ignores): lines.append(f"📄 {fn} (Skipped)")
                    elif not f.get('patch'): lines.append(f"📄 {fn} (No Patch)")
                    else:
                        patch = f['patch']
                        if len(patch)>2500: patch=patch[:2500]+"\n...(Truncated)"
                        lines.append(f"📄 {fn}\n{patch}")
                return "\n".join(lines)
    return None

async def proc_webhook(d):
    if 'repository' not in d: return
    rn = d['repository']['full_name']
    cids = db.get_repo_channels(rn)
    if not cids: return
    for c in d.get('commits', []):
        msg = f"🚀 `{rn}` Commit: `{c['id'][:7]}`\n{c['message']}"
        matches = re.findall(r'(?:fix|close|resolve)\s*#(\d+)', c['message'], re.IGNORECASE)
        closed = []
        for t in matches:
            if db.update_task_status(int(t),"DONE"): closed.append(t)
        if closed: msg += f"\n✅ Closed: {', '.join(closed)}"
        
        diff = await get_github_diff(f"https://api.github.com/repos/{rn}/commits/{c['id']}")
        review_file = None
        review_embeds = []

        if diff:
            review = await ai.review_code(rn, c['author']['name'], c['message'], diff)
            md = f"# Review: {rn}\nCommit: {c['id']}\n\n{review}"
            review_file = io.BytesIO(md.encode()) # Will create File object later
            
            chunks = smart_chunk_text(review)
            for i, ch in enumerate(chunks):
                e = discord.Embed(title="🤖 Review", description=ch, color=0x2ecc71)
                e.set_footer(text=f"{i+1}/{len(chunks)}")
                review_embeds.append(e)

        for cid in cids:
            ch = bot.get_channel(cid)
            if ch:
                try:
                    # BytesIO position reset needed or create new for each
                    f_send = discord.File(io.BytesIO(review_file.getvalue()), filename="Review.md") if review_file else None
                    if review_embeds:
                        if len(review_embeds)>1: 
                            await ch.send(msg, embed=review_embeds[0], view=EmbedPaginator(review_embeds), file=f_send)
                        else: 
                            await ch.send(msg, embed=review_embeds[0], file=f_send)
                    else: await ch.send(msg)
                except Exception as e: print(f"Err send {cid}: {e}")

async def wh_handler(r):
    if r.method=='GET': return web.Response(text="OK")
    try: d=await r.json(); bot.loop.create_task(proc_webhook(d)); return web.Response(text="OK")
    except: return web.Response(status=500)

async def start_server():
    app=web.Application(); app.router.add_route('*', WEBHOOK_PATH, wh_handler)
    r=web.AppRunner(app); await r.setup(); s=web.TCPSite(r,'0.0.0.0',WEBHOOK_PORT); await s.start()
    print(f"🌍 Webhook: {WEBHOOK_PORT}")

@bot.command(name="도움말")
async def help(ctx, cmd: str = None):
    # [변경] JSON 데이터 기반 상세 도움말 + Embed 목록
    if cmd:
        info = COMMAND_INFO.get(cmd)
        if info:
            e = discord.Embed(title=f"❓ !{cmd}", color=0x00ff00)
            e.add_field(name="설명", value=info['desc'], inline=False)
            e.add_field(name="사용법", value=f"`{info['usage']}`", inline=False)
            e.add_field(name="예시", value=f"`{info['ex']}`", inline=False)
            await ctx.send(embed=e)
        else: await ctx.send("❌ 해당 명령어에 대한 도움말이 없습니다.")
    else:
        # 카테고리별로 명령어 목록 생성 (간단 설명 포함)
        def make_embed(title, cmds, color):
            e = discord.Embed(title=title, color=color)
            for c in cmds:
                info = COMMAND_INFO.get(c, {})
                # desc의 첫 줄만 가져와서 한 줄 요약으로 표시
                short_desc = info.get('desc', '설명 없음').split('\n')[0]
                e.add_field(name=f"!{c}", value=short_desc, inline=False)
            return e

        e1 = make_embed("📋 프로젝트 관리", ["프로젝트생성", "상위설정", "프로젝트구조", "할일등록", "현황판", "완료", "담당"], 0x3498db)
        e2 = make_embed("🎙️ 회의 시스템", ["회의시작", "회의종료", "회의목록", "회의조회", "회의삭제"], 0xe74c3c)
        e3 = make_embed("🐙 깃헙 & 관리", ["레포등록", "레포삭제", "레포목록", "초기설정", "권한추가", "권한삭제"], 0x9b59b6)
        e3.set_footer(text="!도움말 [명령어] 로 상세 정보를 확인하세요.")
        
        view = EmbedPaginator([e1, e2, e3], ctx.author)
        await ctx.send(embed=e1, view=view)

@bot.event
async def on_message(msg):
    if msg.author.bot: return
    if msg.channel.id in meeting_buffer and not msg.content.startswith('!'):
        meeting_buffer[msg.channel.id]['messages'].append({'user':msg.author.display_name, 'time':msg.created_at.strftime("%H:%M"), 'content':msg.content})
    await bot.process_commands(msg)

@bot.event
async def on_ready():
    print(f'Logged in {bot.user}')
    # [NEW] 봇 켜질 때 Owner 자동 관리자 등록
    if OWNER_ID:
        try:
            # 봇이 볼 수 있는 멤버인지 확인은 어렵지만 DB에는 ID만 있으면 됨
            # 이름은 API 호출 없이 알 수 없으므로 'Owner' 등 임시값 또는 fetch 사용
            # 여기서는 안전하게 fetch 시도 (실패시 ID로 저장)
            try:
                owner_user = await bot.fetch_user(int(OWNER_ID))
                name = owner_user.name
            except:
                name = "Owner"
            
            if db.ensure_admin(int(OWNER_ID), name):
                print(f"✅ Owner({name}) automatically registered as Admin.")
        except Exception as e:
            print(f"⚠️ Failed to register owner: {e}")
            
    await start_server()

if __name__ == "__main__": 
    if DISCORD_TOKEN: bot.run(DISCORD_TOKEN)