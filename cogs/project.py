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
            
            forum = await category.create_forum(
                name="📌 이슈-보드",
                topic=f"[{name}] 프로젝트의 작업 및 이슈 관리",
                available_tags=forum_tags
            )

            # 4. 회의록 포럼 생성
            meeting_tags = [
                discord.ForumTag(name="진행중", emoji="🎙️"),
                discord.ForumTag(name="종료", emoji="✅")
            ]
            
            meeting_forum = await category.create_forum(
                name="🎙️ 회의-보드",
                topic=f"[{name}] 회의 기록 및 진행 아카이브",
                available_tags=meeting_tags
            )

            # [NEW] 5. 자유 채팅방 생성
            # 기존 '회의록' 텍스트 채널을 '채팅'으로 변경하여 소통 공간으로 활용
            chat_channel = await category.create_text_channel(
                name="💬 채팅",
                topic=f"[{name}] 자유로운 소통 및 봇 명령어 사용 공간"
            )
            await chat_channel.send(f"👋 **{name}** 프로젝트의 채팅방입니다!\n여기서 `/회의 시작`을 입력하면 **회의-보드**에 기록이 시작됩니다.")

            # 6. DB 등록
            pid = self.bot.db.create_project(
                guild_id=guild.id,
                name=name,
                category_id=category.id,
                forum_channel_id=forum.id,
                meeting_channel_id=meeting_forum.id
            )
            
            if pid:
                return True, f"✅ **{name}** 프로젝트 공간 생성 완료!\n- 카테고리: {category.name}\n- 이슈보드: {forum.mention}\n- 회의보드: {meeting_forum.mention}\n- 채팅방: {chat_channel.mention}"
            else:
                # DB 등록 실패 시 롤백
                await category.delete()
                try: await forum.delete()
                except: pass
                try: await meeting_forum.delete()
                except: pass
                try: await chat_channel.delete()
                except: pass
                
                return False, "❌ DB 등록 중 오류가 발생했습니다."

        except discord.Forbidden:
            return False, "❌ 봇에게 '채널/카테고리 관리' 권한이 없습니다."
        except AttributeError:
            return False, "❌ discord.py 버전이 낮아 포럼을 생성할 수 없습니다. (2.0+ 필요)"
        except Exception as e:
            return False, f"❌ 프로젝트 생성 실패: {e}"

    # ------------------------------------------------------------------
    # 프로젝트 관리 (Group Commands)
    # ------------------------------------------------------------------
    @commands.hybrid_group(name="프로젝트", description="프로젝트 관리 명령어 모음")
    async def proj_group(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

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

    @proj_group.command(name="구조", description="현재 프로젝트의 계층 구조를 보여줍니다.")
    @is_authorized()
    async def tree_proj(self, ctx):
        rows = self.bot.db.get_project_tree(ctx.guild.id)
        if not rows:
            await ctx.send("📭 생성된 프로젝트가 없습니다.")
            return
        
        nodes = {r[0]: {'name': r[1], 'parent': r[2], 'children': []} for r in rows}
        roots = []
        for pid, node in nodes.items():
            if node['parent'] and node['parent'] in nodes:
                nodes[node['parent']]['children'].append(node)
            else:
                roots.append(node)
        
        def print_node(node, level=0):
            text = f"{'　'*level}📂 **{node['name']}**\n"
            for child in node['children']:
                text += print_node(child, level+1)
            return text

        tree_text = "".join([print_node(r) for r in roots])
        await ctx.send(embed=discord.Embed(title=f"🌳 {ctx.guild.name} 프로젝트 구조", description=tree_text, color=0x3498db))

    @proj_group.command(name="상위설정", description="프로젝트 간의 상하 관계를 설정합니다.")
    @app_commands.describe(child="하위 프로젝트", parent="상위 프로젝트")
    @is_authorized()
    async def set_parent(self, ctx, child: str, parent: str):
        if self.bot.db.set_parent_project(ctx.guild.id, child, parent):
            await ctx.send(f"🔗 **{child}** ⊂ **{parent}**")
        else:
            await ctx.send("❌ 프로젝트 이름을 확인해주세요.")

    # ------------------------------------------------------------------
    # 현황판 (Dashboard) 기능
    # ------------------------------------------------------------------
    @commands.hybrid_command(name="현황판설정", description="이 채널에 고정 현황판을 생성합니다.")
    @is_authorized()
    async def set_dashboard(self, ctx):
        msg = await ctx.send("🔄 현황판 초기화 중...")
        self.bot.db.set_dashboard(ctx.guild.id, ctx.channel.id, msg.id)
        await self.refresh_dashboard(ctx.guild.id)
        await ctx.send("✅ 설정 완료", ephemeral=True)

    async def refresh_dashboard(self, guild_id):
        """현황판 메시지를 최신 상태로 수정"""
        settings = self.bot.db.get_dashboard_settings(guild_id)
        if not settings: return
        
        channel_id, message_id = settings
        channel = self.bot.get_channel(channel_id)
        if not channel: return
        
        try:
            message = await channel.fetch_message(message_id)
        except: return 

        ts = self.bot.db.get_tasks(guild_id)
        todo, prog, done = [], [], []
        for t in ts:
            # t: task_id, proj_name, content, assignee_id, assignee_name, status...
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
    # 할 일 (Task) 관리
    # ------------------------------------------------------------------
    @commands.hybrid_command(name="할일등록", description="새로운 할 일을 등록합니다.")
    @app_commands.describe(project="프로젝트명", content="할 일 내용")
    @is_authorized()
    async def add_task(self, ctx, project: str = None, *, content: str = None):
        if content:
            p_name = project or "일반"
            
            # [포럼 스레드 생성 로직]
            pid = self.bot.db.get_project_id(ctx.guild.id, p_name)
            project_data = self.bot.db.get_project(pid) if pid else None
            
            thread_id = None
            message_id = None
            forum_link = ""

            if project_data and project_data.get('forum_channel_id'):
                forum = ctx.guild.get_channel(project_data['forum_channel_id'])
                
                if forum:
                    try:
                        # ForumChannel인 경우
                        if isinstance(forum, discord.ForumChannel):
                            todo_tag = next((t for t in forum.available_tags if t.name == "TODO"), None)
                            tags = [todo_tag] if todo_tag else []
                            th = await forum.create_thread(
                                name=content[:100],
                                content=f"📝 **작업 상세**\n{content}\n\n👤 **생성자**: {ctx.author.mention}",
                                applied_tags=tags
                            )
                            thread_id = th.thread.id
                            message_id = th.message.id
                            forum_link = f" 🔗 [Link]({th.thread.jump_url})"
                        
                        # TextChannel인 경우 (대체 생성된 경우)
                        elif isinstance(forum, discord.TextChannel):
                            msg = await forum.send(f"📝 **[TODO]** {content}\n👤 {ctx.author.mention}")
                            # 텍스트 채널은 스레드 생성이 필수는 아니지만, 댓글용으로 생성 가능
                            th = await msg.create_thread(name=content[:100])
                            thread_id = th.id
                            message_id = msg.id
                            forum_link = f" 🔗 [Link]({msg.jump_url})"

                    except Exception as e:
                        print(f"게시글 생성 실패: {e}")

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
        if not ts:
            await ctx.send("📭 할 일이 없습니다.")
            return
        
        todo, prog, done = [], [], []
        for t in ts:
            line = f"**#{t[0]}** [{t[1]}] {t[2]} (👤{t[4] or '미정'})"
            if t[5]=='TODO': todo.append(line)
            elif t[5]=='IN_PROGRESS': prog.append(line)
            else: done.append(line)
        
        e = discord.Embed(title=f"📊 {project if project else '전체'} 현황", color=0xf1c40f)
        e.add_field(name="대기", value="\n".join(todo) or "-", inline=False)
        e.add_field(name="진행", value="\n".join(prog) or "-", inline=False)
        e.add_field(name="완료", value="\n".join(done) or "-", inline=False)
        await ctx.send(embed=e)

    @commands.hybrid_command(name="완료", description="할 일을 완료 처리합니다.")
    @app_commands.describe(task_id="완료할 작업 ID")
    @is_authorized()
    async def done_task(self, ctx, task_id: int):
        task = self.bot.db.get_task(task_id)
        if not task:
            await ctx.send("❌ 해당 ID의 작업을 찾을 수 없습니다.")
            return

        if self.bot.db.update_task_status(task_id, "DONE"): 
            await ctx.message.add_reaction("✅")
            
            # 스레드 업데이트
            thread_id = task.get('thread_id')
            if thread_id:
                try:
                    thread = ctx.guild.get_thread(thread_id) or await ctx.guild.fetch_channel(thread_id)
                    if thread:
                        if isinstance(thread.parent, discord.ForumChannel):
                            done_tag = next((t for t in thread.parent.available_tags if t.name == "DONE"), None)
                            if done_tag:
                                await thread.edit(applied_tags=[done_tag], archived=True, locked=False)
                                await thread.send("✅ **작업이 완료되었습니다.**")
                        elif isinstance(thread.parent, discord.TextChannel):
                            await thread.edit(archived=True, locked=False)
                            await thread.send("✅ **작업이 완료되었습니다.**")

                except Exception as e:
                    print(f"스레드 업데이트 실패: {e}")

            await self.refresh_dashboard(ctx.guild.id)
        else:
            await ctx.send("❌ 실패")

    @commands.hybrid_command(name="담당", description="담당자를 지정합니다.")
    @app_commands.describe(task_id="작업 ID", member="담당자 멘션")
    @is_authorized()
    async def assign_task(self, ctx, task_id: int, member: discord.Member):
        if self.bot.db.assign_task(task_id, member.id, member.name): 
            await ctx.send(f"👤 담당: {member.mention}")
            
            task = self.bot.db.get_task(task_id)
            if task and task.get('thread_id'):
                try:
                    thread = ctx.guild.get_thread(task['thread_id']) or await ctx.guild.fetch_channel(task['thread_id'])
                    if thread: await thread.send(f"👤 **담당자 변경**: {member.mention}")
                except: pass
                
            await self.refresh_dashboard(ctx.guild.id)
        else:
            await ctx.send("❌ 실패: ID를 확인하세요.")

async def setup(bot):
    await bot.add_cog(ProjectCog(bot))