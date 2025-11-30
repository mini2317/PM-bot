import discord
from discord.ext import commands
from utils import is_authorized

class ProjectCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group(name="프로젝트", invoke_without_command=True)
    async def proj_group(self, ctx):
        """프로젝트 및 할 일 관리 명령어"""
        embed = discord.Embed(title="📋 프로젝트 관리", description="`!프로젝트 [명령어]` 형식으로 사용하세요.", color=0x3498db)
        embed.add_field(name="생성 [이름]", value="새 프로젝트를 만듭니다.", inline=True)
        embed.add_field(name="구조", value="프로젝트 계층 구조를 봅니다.", inline=True)
        embed.add_field(name="상위설정 [자식] [부모]", value="상하 관계를 설정합니다.", inline=False)
        embed.add_field(name="--- 할 일 ---", value="아래 명령어는 `!할일` 등으로도 사용 가능", inline=False)
        embed.add_field(name="할일 [프로젝트] [내용]", value="할 일을 등록합니다.", inline=False)
        embed.add_field(name="현황 [프로젝트]", value="칸반 보드를 봅니다.", inline=False)
        await ctx.send(embed=embed)

    @proj_group.command(name="생성")
    @is_authorized()
    async def create_proj(self, ctx, name: str):
        if self.bot.db.create_project(ctx.guild.id, name):
            await ctx.send(f"🆕 프로젝트 **{name}** 생성 완료")
        else:
            await ctx.send("❌ 이미 존재하는 이름입니다.")

    @proj_group.command(name="구조")
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

    @proj_group.command(name="상위설정")
    @is_authorized()
    async def set_parent(self, ctx, child: str, parent: str):
        if self.bot.db.set_parent_project(ctx.guild.id, child, parent):
            await ctx.send(f"🔗 **{child}** ⊂ **{parent}**")
        else:
            await ctx.send("❌ 프로젝트 이름을 확인해주세요.")

    # --- 할 일 관련 (단축 명령어 지원을 위해 별도 커맨드로도 등록) ---
    
    @commands.command(name="할일") # !할일 == !프로젝트 할일
    @is_authorized()
    async def add_task_alias(self, ctx, p: str, *, c: str):
        await self.add_task(ctx, p, c=c)

    @proj_group.command(name="할일")
    @is_authorized()
    async def add_task(self, ctx, p: str, *, c: str):
        tid = self.bot.db.add_task(ctx.guild.id, p, c)
        await ctx.send(f"✅ [{p}] 할 일 등록 (ID: **{tid}**)")

    @commands.command(name="현황")
    @is_authorized()
    async def status_alias(self, ctx, p: str = None):
        await self.status(ctx, p)

    @proj_group.command(name="현황")
    @is_authorized()
    async def status(self, ctx, p: str = None):
        ts = self.bot.db.get_tasks(ctx.guild.id, p)
        if not ts:
            await ctx.send("📭 할 일이 없습니다.")
            return
        
        todo, prog, done = [], [], []
        for t in ts:
            # t: task_id, proj_name, content, assignee_id, assignee_name, status...
            line = f"**#{t[0]}** [{t[1]}] {t[2]} (👤{t[4] or '미정'})"
            if t[5]=="TODO": todo.append(line)
            elif t[5]=="IN_PROGRESS": prog.append(line)
            else: done.append(line)
        
        e = discord.Embed(title=f"📊 {p if p else '전체'} 현황", color=0xf1c40f)
        e.add_field(name="대기", value="\n".join(todo) or "-", inline=False)
        e.add_field(name="진행", value="\n".join(prog) or "-", inline=False)
        e.add_field(name="완료", value="\n".join(done) or "-", inline=False)
        await ctx.send(embed=e)

    @commands.command(name="완료")
    @is_authorized()
    async def done_task(self, ctx, tid: int):
        if self.bot.db.update_task_status(tid, "DONE"): await ctx.message.add_reaction("✅")
        else: await ctx.send("❌ 실패")

    @commands.command(name="담당")
    @is_authorized()
    async def assign_task(self, ctx, tid: int, m: discord.Member):
        if self.bot.db.assign_task(tid, m.id, m.name): await ctx.send(f"👤 담당: {m.mention}")
        else: await ctx.send("❌ 실패")

async def setup(bot):
    await bot.add_cog(ProjectCog(bot))