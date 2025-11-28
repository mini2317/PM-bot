import discord
from discord.ext import commands
import os
import aiohttp
from aiohttp import web
import asyncio
import datetime
import google.generativeai as genai
import sqlite3
import json

# ==================================================================
# [설정 및 키 로드 영역]
# ==================================================================

def load_key(filename):
    """src/key/ 경로에서 키 파일을 읽어옵니다."""
    base_path = "src/key"
    path = os.path.join(base_path, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"❌ 오류: '{path}' 파일을 찾을 수 없습니다.")
        return None

DISCORD_TOKEN = load_key("bot_token")
GEMINI_API_KEY = load_key("gemini_key")
GITHUB_TOKEN = load_key("github_key")

WEBHOOK_PORT = 8080 
WEBHOOK_PATH = "/github-webhook"

# Github API 헤더 (토큰 로드 후 설정)
github_headers = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# ==================================================================
# [데이터베이스 매니저 (SQLite3)]
# ==================================================================
class DBManager:
    def __init__(self, db_name="pm_bot.db"):
        self.db_name = db_name
        self.init_db()

    def init_db(self):
        """테이블 초기화"""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        
        # 사용자 권한 테이블
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, username TEXT, role TEXT, joined_at TEXT)''')
        
        # 회의록 저장 테이블 (jump_url 컬럼 추가됨)
        c.execute('''CREATE TABLE IF NOT EXISTS meetings
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      name TEXT, 
                      date TEXT, 
                      channel_id INTEGER, 
                      transcript TEXT, 
                      summary TEXT,
                      jump_url TEXT)''')
        
        # 기존 테이블에 jump_url 컬럼이 없는 경우를 위한 마이그레이션
        try:
            c.execute("SELECT jump_url FROM meetings LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE meetings ADD COLUMN jump_url TEXT")

        # 레포지토리 추적 테이블
        c.execute('''CREATE TABLE IF NOT EXISTS repositories
                     (repo_name TEXT PRIMARY KEY, channel_id INTEGER, added_by TEXT, date TEXT)''')

        # [NEW] 할 일(Task) 관리 테이블
        c.execute('''CREATE TABLE IF NOT EXISTS tasks
                     (task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      project_name TEXT,
                      content TEXT,
                      assignee_id INTEGER,
                      assignee_name TEXT,
                      status TEXT DEFAULT 'TODO',
                      created_at TEXT)''')
        
        conn.commit()
        conn.close()

    # --- 사용자 관리 ---
    def add_user(self, user_id, username, role="user"):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (user_id, username, role, joined_at) VALUES (?, ?, ?, ?)",
                      (user_id, username, role, datetime.datetime.now().strftime("%Y-%m-%d")))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False 
        finally:
            conn.close()

    def remove_user(self, user_id):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def is_authorized(self, user_id):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result is not None

    # --- 회의록 관리 ---
    def save_meeting(self, name, channel_id, transcript, summary, jump_url):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        c.execute("INSERT INTO meetings (name, date, channel_id, transcript, summary, jump_url) VALUES (?, ?, ?, ?, ?, ?)",
                  (name, date_str, channel_id, transcript, summary, jump_url))
        log_id = c.lastrowid
        conn.commit()
        conn.close()
        return log_id

    def get_recent_meetings(self, limit=5):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT id, name, date, summary, jump_url FROM meetings ORDER BY id DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        return rows

    def get_meeting_detail(self, meeting_id):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT name, date, summary, transcript, jump_url FROM meetings WHERE id = ?", (meeting_id,))
        row = c.fetchone()
        conn.close()
        return row

    # --- 레포지토리 관리 ---
    def add_repo(self, repo_name, channel_id, added_by):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        try:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            c.execute("INSERT OR REPLACE INTO repositories (repo_name, channel_id, added_by, date) VALUES (?, ?, ?, ?)",
                      (repo_name, channel_id, added_by, date_str))
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def remove_repo(self, repo_name):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("DELETE FROM repositories WHERE repo_name = ?", (repo_name,))
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def get_repo_channel(self, repo_name):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT channel_id FROM repositories WHERE repo_name = ?", (repo_name,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else None

    def get_all_repos(self):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT repo_name, channel_id FROM repositories")
        rows = c.fetchall()
        conn.close()
        return rows

    # --- [NEW] 할 일(Task) 관리 메서드 ---
    def add_task(self, project_name, content):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        c.execute("INSERT INTO tasks (project_name, content, status, created_at) VALUES (?, ?, 'TODO', ?)",
                  (project_name, content, date_str))
        task_id = c.lastrowid
        conn.commit()
        conn.close()
        return task_id

    def get_tasks(self, project_name=None):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        if project_name:
            c.execute("SELECT * FROM tasks WHERE project_name = ? ORDER BY task_id", (project_name,))
        else:
            c.execute("SELECT * FROM tasks ORDER BY task_id")
        rows = c.fetchall()
        conn.close()
        return rows

    def update_task_status(self, task_id, status):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("UPDATE tasks SET status = ? WHERE task_id = ?", (status, task_id))
        updated = c.rowcount > 0
        conn.commit()
        conn.close()
        return updated

    def assign_task(self, task_id, assignee_id, assignee_name):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("UPDATE tasks SET assignee_id = ?, assignee_name = ? WHERE task_id = ?", 
                  (assignee_id, assignee_name, task_id))
        updated = c.rowcount > 0
        conn.commit()
        conn.close()
        return updated

db = DBManager()

# ==================================================================
# [봇 초기화]
# ==================================================================
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-2.0-flash-exp')
else:
    print("❌ Gemini Key가 로드되지 않았습니다.")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# 회의 데이터 버퍼: {channel_id: {'name': '회의명', 'messages': [], 'jump_url': 'URL'}}
meeting_buffer = {}

# ==================================================================
# [권한 체크 데코레이터]
# ==================================================================
def check_permission():
    async def predicate(ctx):
        if db.is_authorized(ctx.author.id):
            return True
        await ctx.send("🚫 이 기능을 사용할 권한이 없습니다. 관리자에게 문의하세요.")
        return False
    return commands.check(predicate)

# ==================================================================
# [도움말 명령어]
# ==================================================================
@bot.command(name="도움말")
async def help_command(ctx):
    """사용 가능한 명령어 목록을 보여줍니다."""
    embed = discord.Embed(title="🤖 PM 봇 도움말", description="올인원 프로젝트 관리 봇입니다.", color=0x00ff00)
    
    embed.add_field(name="📋 프로젝트/할일", value=(
        "`!할일등록 [프로젝트] [내용]`: 할 일을 추가합니다.\n"
        "`!현황판 [프로젝트]`: 칸반 보드를 봅니다.\n"
        "`!진행 [ID]`, `!완료 [ID]`: 상태를 변경합니다.\n"
        "`!담당 [ID] [@멘션]`: 담당자를 지정합니다."
    ), inline=False)

    embed.add_field(name="🎙️ 회의 관리", value=(
        "`!회의시작 [주제]` : 대화 기록을 시작합니다.\n"
        "`!회의종료` : 회의를 마치고 AI 요약본을 저장합니다.\n"
        "`!회의목록` : 저장된 회의록과 바로가기 링크를 봅니다.\n"
        "`!회의조회 [ID]` : 상세 내용을 확인합니다."
    ), inline=False)

    embed.add_field(name="🐙 Github 연동", value=(
        "`!레포등록 [Owner/Repo]` : 레포지토리 알림 연결\n"
        "`!레포삭제 [Owner/Repo]` : 연결 해제\n"
        "`!레포목록` : 목록 확인"
    ), inline=False)
    
    embed.add_field(name="👑 관리자 전용", value=(
        "`!초기설정`, `!권한추가`, `!권한삭제`"
    ), inline=False)
    
    await ctx.send(embed=embed)

# ==================================================================
# [관리자 명령어]
# ==================================================================
@bot.command(name="초기설정")
async def init_admin(ctx):
    conn = sqlite3.connect(db.db_name)
    c = conn.cursor()
    c.execute("SELECT count(*) FROM users")
    count = c.fetchone()[0]
    conn.close()

    if count == 0:
        db.add_user(ctx.author.id, ctx.author.name, "admin")
        await ctx.send(f"👑 {ctx.author.mention} 님이 최초 관리자로 등록되었습니다.")
    else:
        await ctx.send("이미 관리자가 존재합니다.")

@bot.command(name="권한추가")
@check_permission()
async def add_auth_user(ctx, member: discord.Member):
    if db.add_user(member.id, member.name):
        await ctx.send(f"✅ {member.mention} 님에게 권한 부여 완료.")
    else:
        await ctx.send(f"⚠️ {member.mention} 님은 이미 권한이 있습니다.")

@bot.command(name="권한삭제")
@check_permission()
async def remove_auth_user(ctx, member: discord.Member):
    if db.remove_user(member.id):
        await ctx.send(f"🗑️ {member.mention} 님의 권한 회수 완료.")
    else:
        await ctx.send("❌ 해당 유저는 등록되어 있지 않습니다.")

# ==================================================================
# [레포지토리 관리 명령어]
# ==================================================================
@bot.command(name="레포등록")
@check_permission()
async def add_repo(ctx, repo_name: str):
    if db.add_repo(repo_name, ctx.channel.id, ctx.author.name):
        await ctx.send(f"✅ **{repo_name}** 연결 완료.")
    else:
        await ctx.send("❌ 등록 실패.")

@bot.command(name="레포삭제")
@check_permission()
async def remove_repo(ctx, repo_name: str):
    if db.remove_repo(repo_name):
        await ctx.send(f"🗑️ **{repo_name}** 해제 완료.")
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
# [NEW] 프로젝트 및 할 일 관리 시스템
# ==================================================================

@bot.command(name="할일등록")
@check_permission()
async def add_task_cmd(ctx, project_name: str, *, content: str):
    """새로운 할 일을 등록합니다. (예: !할일등록 MVP개발 로그인페이지구현)"""
    task_id = db.add_task(project_name, content)
    await ctx.send(f"✅ [Project: {project_name}] 할 일 등록 완료 (ID: **{task_id}**)")

@bot.command(name="현황판")
@check_permission()
async def status_board_cmd(ctx, project_name: str = None):
    """프로젝트 현황판을 보여줍니다. 프로젝트명을 입력하지 않으면 전체를 보여줍니다."""
    tasks = db.get_tasks(project_name)
    if not tasks:
        await ctx.send("📭 등록된 할 일이 없습니다.")
        return

    # 상태별 분류
    todo_list = []
    prog_list = []
    done_list = []

    for task in tasks:
        # task: (id, project, content, assignee_id, assignee_name, status, created_at)
        t_id, p_name, content, a_id, a_name, status, created = task
        assignee = f"@{a_name}" if a_name else "미정"
        # 전체 조회일 경우 프로젝트명도 표시
        prefix = f"[{p_name}] " if not project_name else ""
        line = f"**#{t_id}** {prefix}{content} (👤{assignee})"

        if status == "TODO":
            todo_list.append(line)
        elif status == "IN_PROGRESS":
            prog_list.append(line)
        elif status == "DONE":
            done_list.append(line)

    title = f"📊 {project_name} 현황판" if project_name else "📊 전체 프로젝트 현황판"
    embed = discord.Embed(title=title, color=0xf1c40f)
    
    embed.add_field(name=f"⚪ 대기 중 ({len(todo_list)})", value="\n".join(todo_list) if todo_list else "-", inline=False)
    embed.add_field(name=f"🔵 진행 중 ({len(prog_list)})", value="\n".join(prog_list) if prog_list else "-", inline=False)
    embed.add_field(name=f"🟢 완료 ({len(done_list)})", value="\n".join(done_list) if done_list else "-", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name="진행")
@check_permission()
async def set_progress_cmd(ctx, task_id: int):
    """할 일 상태를 '진행 중'으로 변경합니다."""
    if db.update_task_status(task_id, "IN_PROGRESS"):
        await ctx.message.add_reaction("🏃")
    else:
        await ctx.send("❌ 해당 ID의 할 일을 찾을 수 없습니다.")

@bot.command(name="완료")
@check_permission()
async def set_done_cmd(ctx, task_id: int):
    """할 일 상태를 '완료'로 변경합니다."""
    if db.update_task_status(task_id, "DONE"):
        await ctx.message.add_reaction("✅")
    else:
        await ctx.send("❌ 해당 ID의 할 일을 찾을 수 없습니다.")

@bot.command(name="담당")
@check_permission()
async def assign_task_cmd(ctx, task_id: int, member: discord.Member):
    """할 일의 담당자를 지정합니다."""
    if db.assign_task(task_id, member.id, member.name):
        await ctx.send(f"👤 할 일 **#{task_id}** 담당자가 {member.mention}님으로 지정되었습니다.")
    else:
        await ctx.send("❌ 해당 ID의 할 일을 찾을 수 없습니다.")

# ==================================================================
# [회의록 시스템]
# ==================================================================

@bot.command(name="회의시작")
@check_permission()
async def start_meeting(ctx, *, meeting_name: str):
    """회의를 시작하고 시작 메시지의 링크를 저장합니다."""
    if ctx.channel.id in meeting_buffer:
        current_name = meeting_buffer[ctx.channel.id]['name']
        await ctx.send(f"🔴 이미 '{current_name}' 회의가 진행 중입니다.")
        return
    
    # [NEW] 시작 메시지의 Jump URL 저장
    meeting_buffer[ctx.channel.id] = {
        'name': meeting_name,
        'messages': [],
        'jump_url': ctx.message.jump_url 
    }
    
    embed = discord.Embed(title=f"🎙️ 회의 시작: {meeting_name}", 
                          description="지금부터 대화 내용이 기록됩니다.\n종료하려면 `!회의종료`를 입력하세요.", 
                          color=0xe74c3c)
    await ctx.send(embed=embed)

@bot.command(name="회의종료")
@check_permission()
async def stop_meeting(ctx):
    """회의를 종료하고 요약본을 저장합니다."""
    if ctx.channel.id not in meeting_buffer:
        await ctx.send("⚠️ 진행 중인 회의가 없습니다.")
        return

    data = meeting_buffer.pop(ctx.channel.id)
    meeting_name = data['name']
    messages = data['messages']
    jump_url = data.get('jump_url', '') # 저장된 URL 가져오기
    
    if not messages:
        await ctx.send("📝 기록된 대화가 없어 회의록을 생성하지 않습니다.")
        return

    waiting_msg = await ctx.send(f"🤖 '{meeting_name}' 회의 정리 중... (AI 분석 및 DB 저장)")

    transcript = "\n".join(messages)
    
    prompt = f"""
    [회의 주제]: {meeting_name}
    [대화 스크립트]:
    {transcript}

    위 내용을 바탕으로 아래 양식의 회의록을 작성해줘.
    
    # 📅 {meeting_name} 회의록
    
    ## 1. 3줄 요약
    ## 2. 주요 논의사항
    ## 3. 결정된 사항
    ## 4. 향후 할 일 (Assignee 포함)
    """

    try:
        response = await asyncio.to_thread(model.generate_content, prompt)
        summary = response.text
        
        # URL 포함하여 저장
        log_id = db.save_meeting(meeting_name, ctx.channel.id, transcript, summary, jump_url)
        
        await waiting_msg.delete()
        
        result_msg = f"✅ **회의록 저장 완료 (ID: {log_id})**\n\n{summary}"
        if len(result_msg) > 2000:
             await ctx.send(f"✅ **회의록 저장 완료 (ID: {log_id})**\n내용이 너무 길어 요약본 앞부분만 출력합니다.")
             await ctx.send(summary[:1900] + "...")
        else:
            await ctx.send(result_msg)
            
    except Exception as e:
        await ctx.send(f"❌ 회의록 생성 또는 저장 실패: {e}")

@bot.command(name="회의목록")
@check_permission()
async def list_meetings(ctx):
    """최근 회의록 목록 조회 (바로가기 링크 포함)"""
    rows = db.get_recent_meetings()
    if not rows:
        await ctx.send("📭 저장된 회의록이 없습니다.")
        return
    
    embed = discord.Embed(title="📂 최근 회의록 목록", color=0xf1c40f)
    for row in rows:
        m_id, name, date, summary, jump_url = row
        
        # 요약본 대신 바로가기 링크 제공
        value_text = f"📅 {date}\n"
        if jump_url:
            value_text += f"🔗 [대화 내용 보러가기]({jump_url})\n"
        else:
            value_text += "🔗 (링크 없음)\n"
            
        short_summary = summary.split('\n')[0][:30] + "..." if summary else "요약 없음"
        value_text += f"📝 {short_summary}"

        embed.add_field(name=f"ID [{m_id}] {name}", value=value_text, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name="회의조회")
@check_permission()
async def view_meeting(ctx, meeting_id: int):
    """회의록 상세 조회"""
    row = db.get_meeting_detail(meeting_id)
    if not row:
        await ctx.send("❌ 해당 ID의 회의록을 찾을 수 없습니다.")
        return
    
    name, date, summary, transcript, jump_url = row
    
    msg = f"**📂 회의: {name} ({date})**\n"
    if jump_url:
        msg += f"🔗 [당시 대화로 이동하기]({jump_url})\n"
    msg += f"\n{summary}"
    
    await ctx.send(msg)

# ==================================================================
# [이벤트 핸들러]
# ==================================================================
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.channel.id in meeting_buffer:
        if not message.content.startswith('!'):
            timestamp = message.created_at.strftime("%H:%M")
            log = f"[{timestamp}] {message.author.display_name}: {message.content}"
            meeting_buffer[message.channel.id]['messages'].append(log)

    await bot.process_commands(message)

# ==================================================================
# [Github Webhook & AI Review]
# ==================================================================
async def get_github_diff(commit_url):
    """Github Diff 가져오기"""
    async with aiohttp.ClientSession() as session:
        async with session.get(commit_url, headers=github_headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                diff_text = ""
                for file in data.get('files', []):
                    patch = file.get('patch', '(Binary or Large file)')
                    diff_text += f"📄 File: {file['filename']}\n{patch}\n\n"
                return diff_text
            return None

async def process_webhook_payload(data):
    """Webhook 데이터 처리 및 리뷰 트리거"""
    if 'commits' not in data or 'repository' not in data:
        return

    repo_full_name = data['repository']['full_name'] 
    target_channel_id = db.get_repo_channel(repo_full_name)

    if not target_channel_id:
        print(f"⚠️ 알림 스킵: 등록되지 않은 레포지토리 ({repo_full_name})")
        return

    channel = bot.get_channel(target_channel_id)
    if not channel:
        print(f"❌ 오류: 채널 ID {target_channel_id}를 찾을 수 없습니다.")
        return

    for commit in data['commits']:
        author = commit['author']['name']
        message = commit['message']
        url = commit['url']
        commit_id = commit['id'][:7]

        await channel.send(f"🚀 **New Code Pushed!**\nRepo: `{repo_full_name}`\nCommit: `{commit_id}` by **{author}**\nMessage: `{message}`\nAI가 코드를 검토 중입니다...")

        diff_text = await get_github_diff(url)
        
        if not diff_text:
            await channel.send("⚠️ 변경 사항(Diff)을 가져오지 못했습니다.")
            continue

        prompt = f"""
        GitHub 커밋 코드 리뷰 요청.
        [Commit Info] Repo: {repo_full_name}, Author: {author}, Msg: {message}
        [Code Diff]
        {diff_text[:15000]} 

        [리뷰 가이드]
        1. 코드 의도 파악
        2. 잠재적 버그/성능 문제 지적
        3. 개선안 제안
        4. 친절한 한국어로 답변
        """
        
        try:
            response = await asyncio.to_thread(model.generate_content, prompt)
            review = response.text
            
            embed = discord.Embed(title=f"🤖 AI Code Review ({commit_id})", url=url, color=0x2ecc71)
            embed.set_author(name=author)
            
            if len(review) > 1024:
                embed.description = review[:1024] + "...\n(내용이 길어 일부만 표시됨)"
            else:
                embed.description = review
                
            await channel.send(embed=embed)
            
        except Exception as e:
            await channel.send(f"❌ AI 리뷰 중 오류 발생: {e}")

async def webhook_handler(request):
    try:
        data = await request.json()
        bot.loop.create_task(process_webhook_payload(data))
        return web.Response(text="Webhook received", status=200)
    except Exception as e:
        return web.Response(text=f"Error: {str(e)}", status=500)

async def start_web_server():
    app = web.Application()
    app.router.add_post(WEBHOOK_PATH, webhook_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT)
    await site.start()
    print(f"🌍 Webhook Server running on port {WEBHOOK_PORT}")
    print(f"📢 GitHub Webhook Payload URL에 다음 경로를 추가하세요: [당신의_외부_IP_또는_도메인]{WEBHOOK_PATH}")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    if not DISCORD_TOKEN or not GEMINI_API_KEY:
        print("❌ CRITICAL: 키 파일 로드 실패. src/key 폴더를 확인하세요.")
        return
    if not GITHUB_TOKEN:
        print("⚠️ Warning: Github 키가 로드되지 않았습니다. AI 코드 리뷰 기능을 사용할 수 없습니다.")
    await start_web_server()

if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("봇 토큰이 없어 실행할 수 없습니다.")