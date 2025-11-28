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
import json

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
# [3. UI 클래스 (페이지네이션)]
# ==================================================================
class EmbedPaginator(View):
    def __init__(self, embeds):
        super().__init__(timeout=60)
        self.embeds = embeds
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.children[0].disabled = (self.current_page == 0)
        self.children[1].disabled = (self.current_page == len(self.embeds) - 1)

    @discord.ui.button(label="◀️ 이전", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="다음 ▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

# ==================================================================
# [4. 권한 체크 데코레이터]
# ==================================================================
def check_permission():
    async def predicate(ctx):
        if db.is_authorized(ctx.author.id):
            return True
        await ctx.send("🚫 이 기능을 사용할 권한이 없습니다.")
        return False
    return commands.check(predicate)

# ==================================================================
# [5. 관리자/권한 명령어]
# ==================================================================
@bot.command(name="초기설정")
async def init_admin(ctx):
    if db.add_user(ctx.author.id, ctx.author.name, "admin"):
        await ctx.send(f"👑 {ctx.author.mention} 님이 최초 관리자로 등록되었습니다.")
    else:
        await ctx.send("이미 관리자가 존재합니다.")

@bot.command(name="권한추가")
@check_permission()
async def add_auth_user(ctx, member: discord.Member):
    if db.add_user(member.id, member.name):
        await ctx.send(f"✅ {member.mention} 님에게 봇 사용 권한 부여.")
    else:
        await ctx.send(f"⚠️ {member.mention} 님은 이미 권한 보유.")

@bot.command(name="권한삭제")
@check_permission()
async def remove_auth_user(ctx, member: discord.Member):
    if db.remove_user(member.id):
        await ctx.send(f"🗑️ {member.mention} 권한 회수.")
    else:
        await ctx.send("❌ 미등록 유저.")

# ==================================================================
# [6. Github 레포 명령어]
# ==================================================================
@bot.command(name="레포등록")
@check_permission()
async def add_repo(ctx, repo_name: str):
    if db.add_repo(repo_name, ctx.channel.id, ctx.author.name):
        await ctx.send(f"✅ **{repo_name}** → <#{ctx.channel.id}> 연결 성공.")
    else:
        await ctx.send("❌ 등록 실패.")

@bot.command(name="레포삭제")
@check_permission()
async def remove_repo(ctx, repo_name: str):
    if db.remove_repo(repo_name):
        await ctx.send(f"🗑️ **{repo_name}** 연결 해제.")
    else:
        await ctx.send("❌ 미등록 레포.")

@bot.command(name="레포목록")
@check_permission()
async def list_repos(ctx):
    rows = db.get_all_repos()
    if not rows:
        await ctx.send("📭 연결된 레포지토리가 없습니다.")
        return
    embed = discord.Embed(title="🐙 연동된 레포지토리", color=0x6e5494)
    for repo, channel_id in rows:
        embed.add_field(name=repo, value=f"📢 <#{channel_id}>", inline=False)
    await ctx.send(embed=embed)

# ==================================================================
# [7. 프로젝트 할 일]
# ==================================================================
@bot.command(name="할일등록")
@check_permission()
async def add_task_cmd(ctx, project_name: str, *, content: str):
    task_id = db.add_task(project_name, content)
    await ctx.send(f"✅ [Project: {project_name}] 할 일 등록 (ID: **{task_id}**)")

@bot.command(name="현황판")
@check_permission()
async def status_board_cmd(ctx, project_name: str = None):
    tasks = db.get_tasks(project_name)
    if not tasks:
        await ctx.send("📭 할 일이 없습니다.")
        return
    todo, prog, done = [], [], []
    for task in tasks:
        t_id, p_name, content, a_id, a_name, status, created, m_id = task
        assignee = f"@{a_name}" if a_name else "미정"
        prefix = f"[{p_name}] " if not project_name else ""
        mark = "🎙️" if m_id else ""
        line = f"**#{t_id}** {prefix}{content} (👤{assignee}) {mark}"
        if status == "TODO": todo.append(line)
        elif status == "IN_PROGRESS": prog.append(line)
        elif status == "DONE": done.append(line)

    title = f"📊 {project_name} 현황판" if project_name else "📊 전체 프로젝트 현황판"
    embed = discord.Embed(title=title, color=0xf1c40f)
    embed.add_field(name=f"⚪ 대기 ({len(todo)})", value="\n".join(todo) if todo else "-", inline=False)
    embed.add_field(name=f"🔵 진행 ({len(prog)})", value="\n".join(prog) if prog else "-", inline=False)
    embed.add_field(name=f"🟢 완료 ({len(done)})", value="\n".join(done) if done else "-", inline=False)
    await ctx.send(embed=embed)

@bot.command(name="완료")
@check_permission()
async def set_done_cmd(ctx, task_id: int):
    if db.update_task_status(task_id, "DONE"): await ctx.message.add_reaction("✅")
    else: await ctx.send("❌ ID 확인 불가")

@bot.command(name="담당")
@check_permission()
async def assign_task_cmd(ctx, task_id: int, member: discord.Member):
    if db.assign_task(task_id, member.id, member.name):
        await ctx.send(f"👤 할 일 **#{task_id}** 담당자: {member.mention}")
    else: await ctx.send("❌ ID 확인 불가")

# ==================================================================
# [8. 회의록 시스템]
# ==================================================================
@bot.command(name="회의시작")
@check_permission()
async def start_meeting(ctx, *, meeting_name: str = None):
    if ctx.channel.id in meeting_buffer:
        await ctx.send("🔴 이미 이 채널에서 회의가 진행 중입니다.")
        return
    
    if not meeting_name:
        meeting_name = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} 회의 (진행 중)"
    
    meeting_buffer[ctx.channel.id] = {'name': meeting_name, 'messages': [], 'jump_url': ctx.message.jump_url}
    
    embed = discord.Embed(title=f"🎙️ 회의 시작", color=0xe74c3c)
    embed.add_field(name="상태", value="🔴 녹음 중 (Recording...)", inline=True)
    embed.add_field(name="임시 제목", value=meeting_name, inline=True)
    embed.set_footer(text="!회의종료 입력 시 자동 저장됩니다.")
    
    await ctx.send(embed=embed)

@bot.command(name="회의종료")
@check_permission()
async def stop_meeting(ctx):
    if ctx.channel.id not in meeting_buffer:
        await ctx.send("⚠️ 진행 중인 회의가 없습니다.")
        return

    data = meeting_buffer.pop(ctx.channel.id)
    raw_messages = data['messages']
    
    if not raw_messages:
        await ctx.send("📝 대화 내용이 없어 저장하지 않습니다.")
        return

    formatted_transcript = ""
    for msg in raw_messages:
        formatted_transcript += f"[Speaker: {msg['user']} | Time: {msg['time']}] {msg['content']}\n"

    waiting = await ctx.send("🤖 AI가 회의를 분석하고 제목을 짓고 있습니다...")

    full_result = await ai.generate_meeting_summary(formatted_transcript)
    
    lines = full_result.strip().split('\n')
    if lines[0].startswith("제목:"):
        final_title = lines[0].replace("제목:", "").strip()
        summary_body = "\n".join(lines[1:]).strip()
    else:
        final_title = f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
        summary_body = full_result

    m_id = db.save_meeting(ctx.guild.id, final_title, ctx.channel.id, summary_body, data['jump_url'])
    
    extracted_tasks = await ai.extract_tasks_from_meeting(formatted_transcript)
    task_text = ""
    for task in extracted_tasks:
        content = task.get('content', '내용 없음')
        assignee = task.get('assignee_hint', '')
        t_id = db.add_task("회의도출", content, source_meeting_id=m_id)
        task_text += f"• **#{t_id}** {content} (추정: {assignee})\n"

    await waiting.delete()

    embed = discord.Embed(title=f"✅ 회의 종료: {final_title}", color=0x2ecc71)
    embed.add_field(name="📄 요약본", value=summary_body[:500] + ("..." if len(summary_body)>500 else ""), inline=False)
    
    if task_text:
        embed.add_field(name="⚡ 도출된 Action Items", value=task_text, inline=False)
    
    embed.add_field(name="관리", value=f"ID: `{m_id}` | `!회의조회 {m_id}`", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name="회의목록")
@check_permission()
async def list_meetings(ctx):
    rows = db.get_recent_meetings(ctx.guild.id)
    if not rows:
        await ctx.send("📭 이 서버에는 저장된 회의록이 없습니다.")
        return
    embed = discord.Embed(title=f"📂 {ctx.guild.name} 회의록 목록", color=0xf1c40f)
    for row in rows:
        m_id, name, date, summary, link = row
        val = f"📅 {date} | 🔗 [이동]({link})\n📝 {summary.splitlines()[0][:30]}..." if summary else "요약 없음"
        embed.add_field(name=f"ID [{m_id}] {name}", value=val, inline=False)
    await ctx.send(embed=embed)

@bot.command(name="회의조회")
@check_permission()
async def view_meeting(ctx, m_id: int):
    row = db.get_meeting_detail(m_id, ctx.guild.id)
    if not row:
        await ctx.send("❌ 해당 ID의 회의록이 없거나 이 서버의 회의가 아닙니다.")
        return
    name, date, summary, link = row
    msg = f"**📂 {name} ({date})**\n🔗 [이동]({link})\n\n{summary}"
    await ctx.send(msg)

@bot.command(name="회의삭제")
@check_permission()
async def delete_meeting(ctx, m_id: int):
    if db.delete_meeting(m_id, ctx.guild.id):
        await ctx.send(f"🗑️ 회의록 **#{m_id}** 삭제 완료.")
    else:
        await ctx.send("❌ 삭제 실패 (존재하지 않거나 권한 없음).")

# ==================================================================
# [9. Github Webhook & Code Review (수정됨)]
# ==================================================================
async def get_github_diff(api_url):
    """
    [개선된 Diff 로직]
    1. 노이즈 파일(lock파일, 이미지 등) 제외
    2. 파일별 길이 제한 적용 (특정 파일이 너무 크면 앞부분만 전송)
    3. 전체 Diff 텍스트 생성
    """
    print(f"DEBUG: Diff 요청 API URL: {api_url}")
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url, headers=github_headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                diff_lines = []
                
                # 무시할 파일 및 확장자
                ignored_files = ['package-lock.json', 'yarn.lock', 'poetry.lock', 'Gemfile.lock']
                ignored_exts = ('.svg', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf')

                for file in data.get('files', []):
                    filename = file['filename']
                    
                    # 1. 노이즈 필터링
                    if filename in ignored_files or filename.endswith(ignored_exts):
                        diff_lines.append(f"📄 File: {filename} (Skipped: Auto-generated/Asset)")
                        continue

                    # 2. Patch(Diff) 유무 확인
                    # GitHub API는 너무 큰 파일의 patch는 보내지 않습니다.
                    patch = file.get('patch', None)
                    if not patch:
                        diff_lines.append(f"📄 File: {filename} (Skipped: Binary or Too Large)")
                        continue
                    
                    # 3. 파일별 길이 제한 (예: 2500자)
                    # 한 파일이 너무 길면 잘라서 다른 파일들의 내용도 담을 수 있게 합니다.
                    if len(patch) > 2500:
                        patch = patch[:2500] + "\n... (Diff truncated due to length) ..."
                    
                    diff_lines.append(f"📄 File: {filename}\n{patch}\n")
                
                return "\n".join(diff_lines)
            else:
                print(f"DEBUG: API 요청 실패 code={resp.status}")
                return None

async def process_webhook_payload(data):
    if 'repository' not in data: return
    
    # 1. 정보 추출
    repo_name = data['repository']['full_name'] # 예: mini2317/PM-bot
    
    target_channel_id = db.get_repo_channel(repo_name)
    if not target_channel_id:
        print(f"DEBUG: 알 수 없는 레포지토리: {repo_name}")
        return
    
    channel = bot.get_channel(target_channel_id)
    if not channel: return

    commits = data.get('commits', [])
    if not commits: return

    for commit in commits:
        author = commit['author']['name']
        message = commit['message']
        web_url = commit['url'] # 사용자에게 보여줄 클릭용 링크 ([github.com/](https://github.com/)...)
        commit_id = commit['id']
        short_id = commit_id[:7]

        # 2. Task 자동 완료
        closed_tasks = []
        matches = re.findall(r'(?:fix|close|resolve)\s*#(\d+)', message, re.IGNORECASE)
        for t_id in matches:
            if db.update_task_status(int(t_id), "DONE"):
                closed_tasks.append(t_id)

        # 3. 알림 메시지 (링크 포함)
        msg = f"🚀 **Push** `{repo_name}`\nCommit: [`{short_id}`]({web_url}) by **{author}**\nMsg: `{message}`"
        if closed_tasks:
            msg += f"\n✅ Closed: " + ", ".join([f"#{t}" for t in closed_tasks])
        
        await channel.send(msg)

        # 4. [수정] Diff 가져오기 (API URL 생성)
        api_url = f"[https://api.github.com/repos/](https://api.github.com/repos/){repo_name}/commits/{commit_id}"
        
        diff_text = await get_github_diff(api_url)
        
        if diff_text:
            review_result = await ai.review_code(repo_name, author, message, diff_text)
            
            chunks = []
            current_chunk = ""
            
            for line in review_result.split('\n'):
                if len(current_chunk) + len(line) + 1 > 1500:
                    chunks.append(current_chunk)
                    current_chunk = line
                else:
                    if current_chunk:
                        current_chunk += "\n" + line
                    else:
                        current_chunk = line
            
            if current_chunk:
                chunks.append(current_chunk)
            
            embeds = []
            for i, chunk in enumerate(chunks):
                embed = discord.Embed(title=f"🤖 Code Review ({short_id})", url=web_url, color=0x2ecc71)
                embed.description = chunk
                if len(chunks) > 1:
                    embed.set_footer(text=f"Page {i+1}/{len(chunks)}")
                embeds.append(embed)
            
            if len(embeds) > 1:
                view = EmbedPaginator(embeds)
                await channel.send(embed=embeds[0], view=view)
            else:
                await channel.send(embed=embeds[0])
        else:
            print("DEBUG: Diff 텍스트를 가져오지 못했습니다.")

async def webhook_handler(request):
    if request.method == 'GET':
        return web.Response(text="🟢 Bot Webhook Server OK")
    try:
        data = await request.json()
        bot.loop.create_task(process_webhook_payload(data))
        return web.Response(text="OK")
    except Exception:
        return web.Response(status=500)

async def start_web_server():
    app = web.Application()
    app.router.add_route('*', WEBHOOK_PATH, webhook_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', WEBHOOK_PORT)
    await site.start()
    print(f"🌍 Webhook Server running on port {WEBHOOK_PORT}")

# ==================================================================
# [10. 도움말 (페이지네이션 적용)]
# ==================================================================
COMMAND_INFO = {
    # 📋 프로젝트 관리
    "할일등록": {"desc": "새로운 할 일을 등록합니다.", "usage": "!할일등록 [프로젝트명] [내용]", "ex": "!할일등록 MVP 로그인구현"},
    "현황판": {"desc": "프로젝트 할 일 목록을 봅니다.", "usage": "!현황판 [프로젝트명(선택)]", "ex": "!현황판"},
    "완료": {"desc": "할 일을 완료 상태로 변경합니다.", "usage": "!완료 [ID]", "ex": "!완료 12"},
    "담당": {"desc": "할 일의 담당자를 지정합니다.", "usage": "!담당 [ID] [@멘션]", "ex": "!담당 12 @홍길동"},
    
    # 🎙️ 회의록
    "회의시작": {"desc": "대화 내용 기록을 시작합니다. (제목 자동 생성)", "usage": "!회의시작 [제목(선택)]", "ex": "!회의시작"},
    "회의종료": {"desc": "기록을 마치고 회의록/할일을 생성합니다.", "usage": "!회의종료", "ex": "!회의종료"},
    "회의목록": {"desc": "저장된 회의록 리스트를 봅니다.", "usage": "!회의목록", "ex": "!회의목록"},
    "회의조회": {"desc": "회의록 상세 내용과 링크를 봅니다.", "usage": "!회의조회 [ID]", "ex": "!회의조회 5"},
    "회의삭제": {"desc": "회의록을 삭제합니다.", "usage": "!회의삭제 [ID]", "ex": "!회의삭제 5"},

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
        embed1 = discord.Embed(title="📋 프로젝트 관리 명령어", description="할 일과 프로젝트를 관리하세요.", color=0x3498db)
        embed1.add_field(name="!할일등록 [프로젝트] [내용]", value="새로운 할 일을 등록합니다.", inline=False)
        embed1.add_field(name="!현황판 [프로젝트(선택)]", value="칸반 보드를 보여줍니다.", inline=False)
        embed1.add_field(name="!완료 [ID]", value="할 일을 완료 처리합니다.", inline=False)
        embed1.add_field(name="!담당 [ID] [@멘션]", value="담당자를 지정합니다.", inline=False)
        embed1.set_footer(text="Page 1/3")

        embed2 = discord.Embed(title="🎙️ 회의 시스템 명령어", description="회의를 기록하고 AI로 요약하세요.", color=0xe74c3c)
        embed2.add_field(name="!회의시작 [제목(선택)]", value="기록을 시작합니다.", inline=False)
        embed2.add_field(name="!회의종료", value="기록을 끝내고 요약본을 만듭니다.", inline=False)
        embed2.add_field(name="!회의목록", value="저장된 회의록을 봅니다.", inline=False)
        embed2.add_field(name="!회의조회 [ID]", value="상세 내용을 확인합니다.", inline=False)
        embed2.add_field(name="!회의삭제 [ID]", value="회의록을 삭제합니다.", inline=False)
        embed2.set_footer(text="Page 2/3")

        embed3 = discord.Embed(title="⚙️ Github & 관리 명령어", description="레포지토리 연동 및 권한 설정.", color=0x9b59b6)
        embed3.add_field(name="!레포등록 [Owner/Repo]", value="Github 알림 채널 연결.", inline=False)
        embed3.add_field(name="!레포삭제 [Owner/Repo]", value="연결 해제.", inline=False)
        embed3.add_field(name="!레포목록", value="목록 확인.", inline=False)
        embed3.add_field(name="!초기설정", value="최초 관리자 등록.", inline=False)
        embed3.add_field(name="!권한추가/삭제 [@멘션]", value="권한 부여/회수.", inline=False)
        embed3.set_footer(text="Page 3/3")

        view = EmbedPaginator([embed1, embed2, embed3])
        await ctx.send(embed=embed1, view=view)

# ==================================================================
# [11. 실행]
# ==================================================================
@bot.event
async def on_message(message):
    if message.author.bot: return
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
    await start_web_server()

if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ 토큰 없음")