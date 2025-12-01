import discord
from discord.ext import commands
from discord import app_commands
from utils import is_authorized

class ProjectCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------------
    # 프로젝트 관리 (Group Commands)
    # ------------------------------------------------------------------
    @commands.hybrid_group(name="프로젝트", description="프로젝트 관리 명령어 모음")
    async def proj_group(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @proj_group.command(name="생성", description="새로운 프로젝트를 생성합니다.")
    @app_commands.describe(name="생성할 프로젝트 이름")
    @is_authorized()
    async def create_proj(self, ctx, name: str):
        if self.bot.db.create_project(ctx.guild.id, name):
            await ctx.send(f"🆕 프로젝트 **{name}** 생성 완료")
        else:
            await ctx.send("❌ 이미 존재하는 이름입니다.")

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
            t = f"{'　'*level}📂 **{node['name']}**\n"
            for child in node['children']: t += print_node(child, level+1)
            return t

        txt = "".join([print_node(r) for r in roots])
        await ctx.send(embed=discord.Embed(title=f"🌳 {ctx.guild.name} 프로젝트 구조", description=txt, color=0x3498db))

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
        # 1. 초기 메시지 전송
        msg = await ctx.send("🔄 현황판 초기화 중...")
        # 2. DB 저장 (SettingsMixin 메서드 사용)
        self.bot.db.set_dashboard(ctx.guild.id, ctx.channel.id, msg.id)
        # 3. 갱신 실행
        await self.refresh_dashboard(ctx.guild.id)
        await ctx.send("✅ 현황판이 설정되었습니다. 할 일이 변경될 때마다 자동 갱신됩니다.", ephemeral=True)

    async def refresh_dashboard(self, guild_id):
        """현황판 메시지를 최신 상태로 수정"""
        settings = self.bot.db.get_dashboard_settings(guild_id)
        if not settings: return
        
        channel_id, message_id = settings
        channel = self.bot.get_channel(channel_id)
        if not channel: return
        
        try:
            message = await channel.fetch_message(message_id)
        except: return # 메시지가 삭제됨

        # 데이터 조회
        ts = self.bot.db.get_tasks(guild_id)
        todo, prog, done = [], [], []
        for t in ts:
            # t: task_id, proj_name, content, assignee_id, assignee_name, status...
            line = f"**#{t[0]}** [{t[1]}] {t[2]} (👤{t[4] or '미정'})"
            if t[5]=="TODO": todo.append(line)
            elif t[5]=="IN_PROGRESS": prog.append(line)
            else: done.append(line)
        
        e = discord.Embed(title=f"📊 프로젝트 실시간 현황판", color=0xf1c40f, timestamp=discord.utils.utcnow())
        e.add_field(name="⚪ 대기 (TODO)", value="\n".join(todo) or "-", inline=False)
        e.add_field(name="🔵 진행 (IN PROGRESS)", value="\n".join(prog) or "-", inline=False)
        e.add_field(name="🟢 완료 (DONE)", value="\n".join(done) or "-", inline=False)
        e.set_footer(text="자동 갱신됨")
        
        await message.edit(content="", embed=e)

    # ------------------------------------------------------------------
    # 할 일 (Task) 관리 (Shortcuts & Slash)
    # ------------------------------------------------------------------
    @commands.hybrid_command(name="할일등록", description="새로운 할 일을 등록합니다.")
    @app_commands.describe(project="프로젝트명 (띄어쓰기 가능)", content="할 일 내용")
    @is_authorized()
    async def add_task(self, ctx, project: str, *, content: str):
        tid = self.bot.db.add_task(ctx.guild.id, project, content)
        await ctx.send(f"✅ [{project}] 할 일 등록 (ID: **{tid}**)")
        await self.refresh_dashboard(ctx.guild.id) # 갱신

    @commands.hybrid_command(name="현황판", description="칸반 보드 형식으로 현황을 봅니다.")
    @app_commands.describe(project="특정 프로젝트만 보기 (선택)")
    @is_authorized()
    async def status(self, ctx, project: str = None):
        ts = self.bot.db.get_tasks(ctx.guild.id, project)
        if not ts:
            await ctx.send("📭 할 일이 없습니다.")
            return
        
        todo, prog, done = [], [], []
        for t in ts:
            line = f"**#{t[0]}** [{t[1]}] {t[2]} (👤{t[4] or '미정'})"
            if t[5]=="TODO": todo.append(line)
            elif t[5]=="IN_PROGRESS": prog.append(line)
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
        if self.bot.db.update_task_status(task_id, "DONE"): 
            await ctx.message.add_reaction("✅")
            await self.refresh_dashboard(ctx.guild.id) # 갱신
        else: await ctx.send("❌ 실패: ID를 확인하세요.")

    @commands.hybrid_command(name="담당", description="할 일의 담당자를 지정합니다.")
    @app_commands.describe(task_id="작업 ID", member="담당자 멘션")
    @is_authorized()
    async def assign_task(self, ctx, task_id: int, member: discord.Member):
        if self.bot.db.assign_task(task_id, member.id, member.name): 
            await ctx.send(f"👤 담당: {member.mention}")
            await self.refresh_dashboard(ctx.guild.id) # 갱신
        else: await ctx.send("❌ 실패: ID를 확인하세요.")

async def setup(bot):
    await bot.add_cog(ProjectCog(bot))