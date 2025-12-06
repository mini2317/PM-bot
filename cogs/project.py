import discord
from discord.ext import commands
from discord import app_commands
from utils import is_authorized
from ui import ProjectCreateModal, TaskCreateModal, DashboardView

class ProjectCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------------
    # 인프라 생성 로직
    # ------------------------------------------------------------------
    async def _create_project_infrastructure(self, guild, name):
        # 1. DB 중복 체크
        if self.bot.db.get_project_id(guild.id, name):
            return False, "⚠️ 이미 존재하는 프로젝트 이름입니다."

        category = None
        try:
            # 2. 카테고리 생성
            category = await guild.create_category(name=f"📁 {name}")
            
            # 3. 포럼 채널 생성 (이슈 트래커)
            forum_tags = [
                discord.ForumTag(name="TODO", emoji="⬜"),
                discord.ForumTag(name="IN_PROGRESS", emoji="🔵"),
                discord.ForumTag(name="DONE", emoji="✅")
            ]
            
            forum = await guild.create_forum_channels(
                name="📌 이슈-보드",
                category=category,
                topic=f"[{name}] 프로젝트의 작업 및 이슈 관리",
                available_tags=forum_tags
            )

            # 4. 회의록 포럼 생성 (변경됨)
            # 회의를 포럼 게시글(Post)로 관리하기 위해 포럼 채널로 생성
            meeting_tags = [
                discord.ForumTag(name="진행중", emoji="🎙️"),
                discord.ForumTag(name="종료", emoji="✅")
            ]
            
            meeting_forum = await guild.create_forum_channels(
                name="🎙️ 회의-보드",
                category=category,
                topic=f"[{name}] 회의 기록 및 진행 아카이브",
                available_tags=meeting_tags
            )

            # 5. DB 등록
            pid = self.bot.db.create_project(
                guild_id=guild.id,
                name=name,
                category_id=category.id,
                forum_channel_id=forum.id,
                meeting_channel_id=meeting_forum.id
            )
            
            if pid:
                return True, f"✅ **{name}** 프로젝트 공간 생성 완료!\n- 카테고리: {category.name}\n- 이슈보드: {forum.mention}\n- 회의보드: {meeting_forum.mention}"
            else:
                await category.delete(); await forum.delete(); await meeting_forum.delete()
                return False, "❌ DB 등록 중 오류가 발생했습니다."

        except discord.Forbidden:
            return False, "❌ 봇에게 '채널/카테고리 관리' 권한이 없습니다."
        except Exception as e:
            return False, f"❌ 프로젝트 생성 실패: {e}"

    # ... (proj_group 명령어들 유지) ...
    @commands.hybrid_group(name="프로젝트", description="프로젝트 관리 명령어 모음")
    async def proj_group(self, ctx):
        if ctx.invoked_subcommand is None: await ctx.send_help(ctx.command)

    @proj_group.command(name="생성", description="프로젝트 카테고리와 게시판을 자동으로 세팅합니다.")
    @app_commands.describe(name="생성할 프로젝트 이름 (비워두면 폼 입력)")
    @is_authorized()
    async def create_proj(self, ctx, name: str = None):
        if name:
            await ctx.defer()
            success, msg = await self._create_project_infrastructure(ctx.guild, name)
            await ctx.send(msg)
        else:
            async def modal_callback(interaction, project_name):
                await interaction.response.defer()
                success, msg = await self._create_project_infrastructure(interaction.guild, project_name)
                await interaction.followup.send(msg)
            await ctx.interaction.response.send_modal(ProjectCreateModal(self.bot.db, ctx.guild.id, callback=modal_callback))

    @proj_group.command(name="구조", description="구조 확인")
    @is_authorized()
    async def tree_proj(self, ctx):
        rows = self.bot.db.get_project_tree(ctx.guild.id)
        if not rows: await ctx.send("📭 없음"); return
        nodes = {r[0]: {'name': r[1], 'parent': r[2], 'children': []} for r in rows}
        roots = []
        for pid, node in nodes.items():
            if node['parent'] and node['parent'] in nodes: nodes[node['parent']]['children'].append(node)
            else: roots.append(node)
        def print_node(n, l=0):
            t = f"{'　'*l}📂 **{n['name']}**\n"
            for c in n['children']: t += print_node(c, l+1)
            return t
        await ctx.send(embed=discord.Embed(title=f"🌳 {ctx.guild.name} 구조", description="".join([print_node(r) for r in roots]), color=0x3498db))

    @proj_group.command(name="상위설정", description="상하 관계 설정")
    @is_authorized()
    async def set_parent(self, ctx, child: str, parent: str):
        if self.bot.db.set_parent_project(ctx.guild.id, child, parent): await ctx.send(f"🔗 **{child}** ⊂ **{parent}**")
        else: await ctx.send("❌ 실패")
    
    # ------------------------------------------------------------------
    # 현황판 (Dashboard)
    # ------------------------------------------------------------------
    @commands.hybrid_command(name="현황판설정", description="이 채널에 고정 현황판을 생성합니다.")
    @is_authorized()
    async def set_dashboard(self, ctx):
        msg = await ctx.send("🔄 현황판 초기화 중...")
        self.bot.db.set_dashboard(ctx.guild.id, ctx.channel.id, msg.id)
        await self.refresh_dashboard(ctx.guild.id)
        await ctx.send("✅ 설정 완료", ephemeral=True)

    async def refresh_dashboard(self, guild_id):
        settings = self.bot.db.get_dashboard_settings(guild_id)
        if not settings: return
        channel_id, message_id = settings
        channel = self.bot.get_channel(channel_id)
        if not channel: return
        try: message = await channel.fetch_message(message_id)
        except: return 

        ts = self.bot.db.get_tasks(guild_id)
        todo, prog, done = [], [], []
        for t in ts:
            # t: id, name, content, aid, aname, status, tid, mid
            link_md = ""
            if len(t) > 6 and t[6]: # thread_id가 있으면 링크 생성
                # 포럼 스레드 링크는 discord://... 형식이거나 웹 링크
                # 간단히 (🔗) 표시
                link_md = " 🔗" 
            
            line = f"**#{t[0]}** [{t[1]}] {t[2]} (👤{t[4] or '-'}){link_md}"
            if t[5]=='TODO': todo.append(line)
            elif t[5]=='IN_PROGRESS': prog.append(line)
            else: done.append(line)
        
        e = discord.Embed(title=f"📊 프로젝트 실시간 현황판", color=0xf1c40f, timestamp=discord.utils.utcnow())
        e.add_field(name="⚪ 대기 (TODO)", value="\n".join(todo) or "-", inline=False)
        e.add_field(name="🔵 진행 (IN PROGRESS)", value="\n".join(prog) or "-", inline=False)
        e.add_field(name="🟢 완료 (DONE)", value="\n".join(done) or "-", inline=False)
        e.set_footer(text="자동 갱신됨")
        view = DashboardView(self.bot)
        await message.edit(content="", embed=e, view=view)

    # ------------------------------------------------------------------
    # [UPDATE] 할 일 관리 (포럼 연동)
    # ------------------------------------------------------------------
    @commands.hybrid_command(name="할일등록", description="새로운 할 일을 등록합니다.")
    @app_commands.describe(project="프로젝트명", content="할 일 내용")
    @is_authorized()
    async def add_task(self, ctx, project: str = None, *, content: str = None):
        if content:
            p_name = project or "일반"
            
            # 포럼 스레드 생성 로직 (TaskCreateModal과 동일한 로직)
            pid = self.bot.db.get_project_id(ctx.guild.id, p_name)
            project_data = self.bot.db.get_project(pid) if pid else None
            
            thread_id = None
            message_id = None
            forum_link = ""

            if project_data and project_data.get('forum_channel_id'):
                forum = ctx.guild.get_channel(project_data['forum_channel_id'])
                if forum and isinstance(forum, discord.ForumChannel):
                    todo_tag = next((t for t in forum.available_tags if t.name == "TODO"), None)
                    tags = [todo_tag] if todo_tag else []
                    try:
                        th = await forum.create_thread(
                            name=content[:100],
                            content=f"📝 **작업 상세**\n{content}\n\n👤 **생성자**: {ctx.author.mention}",
                            applied_tags=tags
                        )
                        thread_id = th.thread.id
                        message_id = th.message.id
                        forum_link = f" 🔗 [Link]({th.thread.jump_url})"
                    except: pass

            tid = self.bot.db.add_task(ctx.guild.id, p_name, content, thread_id=thread_id, message_id=message_id)
            await ctx.send(f"✅ [{p_name}] 할 일 등록 (ID: **{tid}**){forum_link}")
            await self.refresh_dashboard(ctx.guild.id)
        else:
            modal = TaskCreateModal(self.bot.db, ctx.guild.id)
            if project: modal.project.default = project
            await ctx.interaction.response.send_modal(modal)

    @commands.hybrid_command(name="현황판", description="칸반 보드 조회")
    @is_authorized()
    async def status(self, ctx, project: str = None):
        ts = self.bot.db.get_tasks(ctx.guild.id, project)
        if not ts: await ctx.send("📭 없음"); return
        # (기존 출력 로직 유지)
        todo=[]; prog=[]; done=[]
        for t in ts:
            line = f"**#{t[0]}** [{t[1]}] {t[2]} (👤{t[4] or '-'})"
            if t[5]=='TODO': todo.append(line)
            elif t[5]=='IN_PROGRESS': prog.append(line)
            else: done.append(line)
        e = discord.Embed(title=f"📊 {project or '전체'} 현황", color=0xf1c40f)
        e.add_field(name="대기", value="\n".join(todo) or "-", inline=False)
        e.add_field(name="진행", value="\n".join(prog) or "-", inline=False)
        e.add_field(name="완료", value="\n".join(done) or "-", inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="완료", description="할 일을 완료 처리합니다.")
    @is_authorized()
    async def done_task(self, ctx, task_id: int):
        # 1. DB 정보 조회
        task = self.bot.db.get_task(task_id) # {task_id, thread_id, ...}
        
        if not task:
            await ctx.send("❌ 해당 ID의 작업을 찾을 수 없습니다.")
            return

        # 2. DB 업데이트
        if self.bot.db.update_task_status(task_id, "DONE"): 
            await ctx.message.add_reaction("✅")
            
            # 3. 포럼 스레드 업데이트 (태그 변경 & 닫기)
            thread_id = task.get('thread_id')
            if thread_id:
                try:
                    thread = ctx.guild.get_thread(thread_id)
                    if thread:
                        # 태그 변경 (TODO/IN_PROGRESS -> DONE)
                        if isinstance(thread.parent, discord.ForumChannel):
                            done_tag = next((t for t in thread.parent.available_tags if t.name == "DONE"), None)
                            if done_tag:
                                await thread.edit(applied_tags=[done_tag], archived=True, locked=False)
                                await thread.send("✅ **작업이 완료되었습니다.**")
                except Exception as e:
                    print(f"스레드 업데이트 실패: {e}")

            await self.refresh_dashboard(ctx.guild.id)
        else:
            await ctx.send("❌ 실패")

    @commands.hybrid_command(name="담당", description="담당자를 지정합니다.")
    @is_authorized()
    async def assign_task(self, ctx, task_id: int, member: discord.Member):
        if self.bot.db.assign_task(task_id, member.id, member.name): 
            await ctx.send(f"👤 담당: {member.mention}")
            
            # 스레드에 담당자 알림
            task = self.bot.db.get_task(task_id)
            if task and task.get('thread_id'):
                try:
                    thread = ctx.guild.get_thread(task['thread_id'])
                    if thread: await thread.send(f"👤 **담당자 변경**: {member.mention}")
                except: pass
                
            await self.refresh_dashboard(ctx.guild.id)
        else:
            await ctx.send("❌ 실패: ID를 확인하세요.")

async def setup(bot):
    await bot.add_cog(ProjectCog(bot))