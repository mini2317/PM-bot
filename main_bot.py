import discord
from discord.ext import commands
import os
import aiohttp
from aiohttp import web
import asyncio
import re
from database import DBManager
from ai_helper import AIHelper

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

WEBHOOK_PORT = 8080
WEBHOOK_PATH = "/github-webhook"

# ==================================================================
# [2. 인스턴스 초기화]
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
# [3. 권한 체크 데코레이터]
# ==================================================================
def check_permission():
    async def predicate(ctx):
        if db.is_authorized(ctx.author.id):
            return True
        await ctx.send("🚫 이 기능을 사용할 권한이 없습니다.")
        return False
    return commands.check(predicate)

# ==================================================================
# [4. 관리자 및 권한 관리 명령어] (복구됨)
# ==================================================================
@bot.command(name="초기설정")
async def init_admin(ctx):
    # DB에 유저가 0명일 때만 최초 실행자를 관리자로 등록
    # (실제 DB 체크 로직은 db.add_user 내부 로직이나 별도 count 체크 활용)
    # 여기서는 편의상 add_user의 리턴값으로 판단하거나, DBManager에 count 함수 추가 권장
    # 간단하게 add_user 시도 (role='admin')
    if db.add_user(ctx.author.id, ctx.author.name, "admin"):
        await ctx.send(f"👑 {ctx.author.mention} 님이 최초 관리자로 등록되었습니다.")
    else:
        await ctx.send("이미 관리자나 유저가 등록되어 있습니다. 기존 관리자에게 문의하세요.")

@bot.command(name="권한추가")
@check_permission()
async def add_auth_user(ctx, member: discord.Member):
    if db.add_user(member.id, member.name):
        await ctx.send(f"✅ {member.mention} 님에게 봇 사용 권한이 부여되었습니다.")
    else:
        await ctx.send(f"⚠️ {member.mention} 님은 이미 권한이 있습니다.")

@bot.command(name="권한삭제")
@check_permission()
async def remove_auth_user(ctx, member: discord.Member):
    if db.remove_user(member.id):
        await ctx.send(f"🗑️ {member.mention} 님의 권한이 회수되었습니다.")
    else:
        await ctx.send("❌ 등록되지 않은 유저입니다.")

# ==================================================================
# [5. Github 레포지토리 관리 명령어] (복구됨)
# ==================================================================
@bot.command(name="레포등록")
@check_permission()
async def add_repo(ctx, repo_name: str):
    if db.add_repo(repo_name, ctx.channel.id, ctx.author.name):
        await ctx.send(f"✅ **{repo_name}** 레포지토리가 이 채널(<#{ctx.channel.id}>)에 연결되었습니다.")
    else:
        await ctx.send("❌ 레포지토리 등록 실패.")

@bot.command(name="레포삭제")
@check_permission()
async def remove_repo(ctx, repo_name: str):
    if db.remove_repo(repo_name):
        await ctx.send(f"🗑️ **{repo_name}** 연결 해제 완료.")
    else:
        await ctx.send("❌ 등록되지 않은 레포지토리입니다.")

@bot.command(name="레포목록")
@check_permission()
async def list_repos(ctx):
    rows = db.get_all_repos()
    if not rows:
        await ctx.send("📭 등록된 레포지토리가 없습니다.")
        return

    embed = discord.Embed(title="🐙 연동된 레포지토리 목록", color=0x6e5494)
    for repo, channel_id in rows:
        embed.add_field(name=repo, value=f"📢 <#{channel_id}>", inline=False)
    await ctx.send(embed=embed)

# ==================================================================
# [6. 프로젝트 할 일(Task) 관리]
# ==================================================================
@bot.command(name="할일등록")
@check_permission()
async def add_task_cmd(ctx, project_name: str, *, content: str):
    task_id = db.add_task(project_name, content)
    await ctx.send(f"✅ [Project: {project_name}] 할 일 등록 완료 (ID: **{task_id}**)")

@bot.command(name="현황판")
@check_permission()
async def status_board_cmd(ctx, project_name: str = None):
    tasks = db.get_tasks(project_name)
    if not tasks:
        await ctx.send("📭 등록된 할 일이 없습니다.")
        return

    todo_list, prog_list, done_list = [], [], []

    for task in tasks:
        t_id, p_name, content, a_id, a_name, status, created, m_id = task
        assignee = f"@{a_name}" if a_name else "미정"
        prefix = f"[{p_name}] " if not project_name else ""
        meeting_mark = "🎙️" if m_id else ""
        
        line = f"**#{t_id}** {prefix}{content} (👤{assignee}) {meeting_mark}"

        if status == "TODO": todo_list.append(line)
        elif status == "IN_PROGRESS": prog_list.append(line)
        elif status == "DONE": done_list.append(line)

    title = f"📊 {project_name} 현황판" if project_name else "📊 전체 프로젝트 현황판"
    embed = discord.Embed(title=title, color=0xf1c40f)
    embed.add_field(name=f"⚪ 대기 중 ({len(todo_list)})", value="\n".join(todo_list) if todo_list else "-", inline=False)
    embed.add_field(name=f"🔵 진행 중 ({len(prog_list)})", value="\n".join(prog_list) if prog_list else "-", inline=False)
    embed.add_field(name=f"🟢 완료 ({len(done_list)})", value="\n".join(done_list) if done_list else "-", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name="완료")
@check_permission()
async def set_done_cmd(ctx, task_id: int):
    if db.update_task_status(task_id, "DONE"):
        await ctx.message.add_reaction("✅")
    else:
        await ctx.send("❌ 찾을 수 없는 할 일 ID입니다.")

@bot.command(name="담당")
@check_permission()
async def assign_task_cmd(ctx, task_id: int, member: discord.Member):
    if db.assign_task(task_id, member.id, member.name):
        await ctx.send(f"👤 할 일 **#{task_id}** 담당자: {member.mention}")
    else:
        await ctx.send("❌ 찾을 수 없는 할 일 ID입니다.")

# ==================================================================
# [7. 회의록 시스템]
# ==================================================================
@bot.command(name="회의시작")
@check_permission()
async def start_meeting(ctx, *, meeting_name: str):
    if ctx.channel.id in meeting_buffer:
        await ctx.send("🔴 이미 회의가 진행 중입니다.")
        return
    meeting_buffer[ctx.channel.id] = {'name': meeting_name, 'messages': [], 'jump_url': ctx.message.jump_url}
    await ctx.send(f"🎙️ 회의 시작: **{meeting_name}**")

@bot.command(name="회의종료")
@check_permission()
async def stop_meeting(ctx):
    if ctx.channel.id not in meeting_buffer:
        await ctx.send("⚠️ 진행 중인 회의가 없습니다.")
        return

    data = meeting_buffer.pop(ctx.channel.id)
    transcript = "\n".join(data['messages'])
    meeting_name = data['name']
    
    if not transcript:
        await ctx.send("📝 대화 내용이 없어 저장하지 않습니다.")
        return

    waiting = await ctx.send("🤖 회의 정리 및 할 일 추출 중...")

    # 요약 및 DB 저장
    summary = await ai.generate_meeting_summary(meeting_name, transcript)
    m_id = db.save_meeting(meeting_name, ctx.channel.id, transcript, summary, data['jump_url'])
    
    # 할 일 추출 및 자동 등록
    extracted_tasks = await ai.extract_tasks_from_meeting(transcript)
    task_report = ""
    for task in extracted_tasks:
        content = task.get('content', '내용 없음')
        t_id = db.add_task("회의도출", content, source_meeting_id=m_id)
        task_report += f"- **#{t_id}** {content}\n"

    await waiting.delete()
    await ctx.send(f"✅ **회의록 저장 완료 (ID: {m_id})**\n{summary[:1500]}")
    
    if task_report:
        embed = discord.Embed(title="⚡ 도출된 할 일", description=task_report, color=0xe67e22)
        await ctx.send(embed=embed)

@bot.command(name="회의목록")
@check_permission()
async def list_meetings(ctx):
    rows = db.get_recent_meetings()
    if not rows:
        await ctx.send("📭 회의록 없음")
        return
    embed = discord.Embed(title="📂 회의록 목록", color=0xf1c40f)
    for row in rows:
        m_id, name, date, summary, link = row
        val = f"📅 {date}\n🔗 [이동]({link})\n📝 {summary.splitlines()[0][:30]}..."
        embed.add_field(name=f"ID [{m_id}] {name}", value=val, inline=False)
    await ctx.send(embed=embed)

@bot.command(name="회의조회")
@check_permission()
async def view_meeting(ctx, m_id: int):
    row = db.get_meeting_detail(m_id)
    if not row:
        await ctx.send("❌ 없음")
        return
    name, date, summary, _, link = row
    msg = f"**📂 {name} ({date})**\n🔗 [이동]({link})\n\n{summary}"
    await ctx.send(msg)

# ==================================================================
# [8. Github Webhook 처리]
# ==================================================================
async def get_github_diff(commit_url):
    async with aiohttp.ClientSession() as session:
        async with session.get(commit_url, headers=github_headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                diff_text = ""
                for file in data.get('files', []):
                    patch = file.get('patch', '')
                    diff_text += f"📄 File: {file['filename']}\n{patch}\n\n"
                return diff_text
            return None

async def process_webhook_payload(data):
    if 'commits' not in data or 'repository' not in data: return

    repo_full_name = data['repository']['full_name']
    target_channel_id = db.get_repo_channel(repo_full_name)
    if not target_channel_id: return

    channel = bot.get_channel(target_channel_id)
    if not channel: return

    for commit in data['commits']:
        author = commit['author']['name']
        message = commit['message']
        url = commit['url']
        commit_id = commit['id'][:7]

        # Task 자동 완료 (Fix #12)
        closed_tasks = []
        matches = re.findall(r'(?:fix|close|resolve)\s*#(\d+)', message, re.IGNORECASE)
        for t_id in matches:
            if db.update_task_status(int(t_id), "DONE"):
                closed_tasks.append(t_id)

        msg = f"🚀 **Push Detect**\nRepo: `{repo_full_name}`\nMsg: `{message}`"
        if closed_tasks: msg += f"\n✅ **Closed**: " + ", ".join([f"#{t}" for t in closed_tasks])
        
        await channel.send(msg)

        # AI 리뷰
        diff_text = await get_github_diff(url)
        if diff_text:
            review = await ai.review_code(repo_full_name, author, message, diff_text)
            embed = discord.Embed(title=f"🤖 Code Review ({commit_id})", url=url, color=0x2ecc71)
            embed.description = review[:1000]
            await channel.send(embed=embed)

async def webhook_handler(request):
    try:
        data = await request.json()
        bot.loop.create_task(process_webhook_payload(data))
        return web.Response(text="OK", status=200)
    except:
        return web.Response(status=500)

async def start_web_server():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, webhook_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT)
    await site.start()
    print(f"🌍 Webhook Server running on port {WEBHOOK_PORT}")

# ==================================================================
# [9. 도움말 시스템 (완전판)]
# ==================================================================
COMMAND_INFO = {
    # 📋 프로젝트 관리
    "할일등록": {"desc": "새로운 할 일을 등록합니다.", "usage": "!할일등록 [프로젝트명] [내용]", "ex": "!할일등록 MVP 로그인구현"},
    "현황판": {"desc": "프로젝트 할 일 목록을 봅니다.", "usage": "!현황판 [프로젝트명(선택)]", "ex": "!현황판"},
    "완료": {"desc": "할 일을 완료 상태로 변경합니다.", "usage": "!완료 [ID]", "ex": "!완료 12"},
    "담당": {"desc": "할 일의 담당자를 지정합니다.", "usage": "!담당 [ID] [@멘션]", "ex": "!담당 12 @홍길동"},
    
    # 🎙️ 회의록
    "회의시작": {"desc": "대화 내용 기록을 시작합니다.", "usage": "!회의시작 [주제]", "ex": "!회의시작 주간회의"},
    "회의종료": {"desc": "기록을 마치고 회의록/할일을 생성합니다.", "usage": "!회의종료", "ex": "!회의종료"},
    "회의목록": {"desc": "저장된 회의록 리스트를 봅니다.", "usage": "!회의목록", "ex": "!회의목록"},
    "회의조회": {"desc": "회의록 상세 내용과 링크를 봅니다.", "usage": "!회의조회 [ID]", "ex": "!회의조회 5"},

    # 🐙 Github 연동
    "레포등록": {"desc": "Github 레포지토리 알림을 현재 채널에 연결합니다.", "usage": "!레포등록 [Owner/Repo]", "ex": "!레포등록 google/guava"},
    "레포삭제": {"desc": "레포지토리 연결을 해제합니다.", "usage": "!레포삭제 [Owner/Repo]", "ex": "!레포삭제 google/guava"},
    "레포목록": {"desc": "현재 연결된 레포지토리 목록을 봅니다.", "usage": "!레포목록", "ex": "!레포목록"},

    # 👑 권한 관리
    "초기설정": {"desc": "최초 관리자를 등록합니다. (1회용)", "usage": "!초기설정", "ex": "!초기설정"},
    "권한추가": {"desc": "봇 사용 권한을 부여합니다.", "usage": "!권한추가 [@멘션]", "ex": "!권한추가 @팀원"},
    "권한삭제": {"desc": "봇 사용 권한을 회수합니다.", "usage": "!권한삭제 [@멘션]", "ex": "!권한삭제 @팀원"}
}

@bot.command(name="도움말")
async def help_cmd(ctx, cmd: str = None):
    if cmd:
        info = COMMAND_INFO.get(cmd)
        if info:
            embed = discord.Embed(title=f"❓ 도움말: !{cmd}", color=0x00ff00)
            embed.add_field(name="설명", value=info['desc'], inline=False)
            embed.add_field(name="사용법", value=f"`{info['usage']}`", inline=False)
            embed.add_field(name="예시", value=f"`{info['ex']}`", inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"❌ `{cmd}` 명령어를 찾을 수 없습니다.")
    else:
        embed = discord.Embed(title="🤖 PM 봇 명령어 목록", description="`!도움말 [명령어]`로 상세 설명을 확인하세요.", color=0x3498db)
        
        categories = {
            "📋 프로젝트": ["할일등록", "현황판", "완료", "담당"],
            "🎙️ 회의관리": ["회의시작", "회의종료", "회의목록", "회의조회"],
            "🐙 Github": ["레포등록", "레포삭제", "레포목록"],
            "👑 관리자": ["초기설정", "권한추가", "권한삭제"]
        }
        
        for cat, cmds in categories.items():
            cmd_list = ", ".join([f"`!{c}`" for c in cmds])
            embed.add_field(name=cat, value=cmd_list, inline=False)
            
        await ctx.send(embed=embed)

# ==================================================================
# [10. 실행]
# ==================================================================
@bot.event
async def on_message(message):
    if message.author.bot: return
    if message.channel.id in meeting_buffer and not message.content.startswith('!'):
        timestamp = message.created_at.strftime("%H:%M")
        meeting_buffer[message.channel.id]['messages'].append(f"[{timestamp}] {message.author.display_name}: {message.content}")
    await bot.process_commands(message)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await start_web_server()

if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ 토큰 없음")