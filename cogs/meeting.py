import discord
from discord.ext import commands
from discord import app_commands
import datetime
from ui_components import EmbedPaginator, TaskSelectionView, StatusUpdateView, NewProjectView, RoleCreationView, RoleAssignmentView
from utils import is_authorized, smart_chunk_text

class MeetingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.meeting_buffer = {} 

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if message.channel.id in self.meeting_buffer and not message.content.startswith(('!', '/')):
            msg_obj = {'time': message.created_at.strftime("%H:%M"), 'user': message.author.display_name, 'content': message.content}
            self.meeting_buffer[message.channel.id]['messages'].append(msg_obj)

    @commands.hybrid_group(name="회의", description="회의 관리 명령어")
    async def meeting_group(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @meeting_group.command(name="시작", description="회의 기록을 시작합니다.")
    @app_commands.describe(name="회의 주제 (선택)")
    @is_authorized()
    async def start_meeting(self, ctx, *, name: str = None):
        if ctx.channel.id in self.meeting_buffer:
            await ctx.send("🔴 이미 진행 중입니다.")
            return
        if not name: name = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} 회의"
        self.meeting_buffer[ctx.channel.id] = {'name': name, 'messages': [], 'jump_url': ctx.message.jump_url}
        await ctx.send(embed=discord.Embed(title="🎙️ 회의 시작", description=name, color=0xe74c3c))

    @meeting_group.command(name="종료", description="회의를 종료하고 AI 분석을 시작합니다.")
    @is_authorized()
    async def stop_meeting(self, ctx):
        if ctx.channel.id not in self.meeting_buffer:
            await ctx.send("⚠️ 진행 중인 회의가 없습니다.")
            return

        data = self.meeting_buffer.pop(ctx.channel.id)
        raw = data['messages']
        if not raw:
            await ctx.send("📝 대화 내용이 없습니다.")
            return

        txt = "".join([f"[Speaker: {m['user']}] {m['content']}\n" for m in raw])
        waiting = await ctx.send("🤖 AI 분석 및 플로우 생성 중...")

        # 1. 요약
        full_result = await self.bot.ai.generate_meeting_summary(txt)
        lines = full_result.strip().split('\n')
        title = lines[0].replace("제목:", "").strip() if lines[0].startswith("제목:") else data['name']
        summary = "\n".join(lines[1:]).strip() if lines[0].startswith("제목:") else full_result
        m_id = self.bot.db.save_meeting(ctx.guild.id, title, ctx.channel.id, summary, data['jump_url'])

        # 2. 분석
        projs = [r[1] for r in self.bot.db.get_project_tree(ctx.guild.id)]
        active_tasks = self.bot.db.get_active_tasks_simple(ctx.guild.id)
        roles_str = ", ".join([r.name for r in ctx.guild.roles if not r.is_default()])
        members_str = ", ".join([m.display_name for m in ctx.guild.members if not m.bot])

        ai_data = await self.bot.ai.extract_tasks_and_updates(txt, ", ".join(projs), active_tasks, roles_str, members_str)
        
        new_tasks = ai_data.get('new_tasks', [])
        updates = ai_data.get('updates', [])
        create_roles = ai_data.get('create_roles', [])
        assign_roles = ai_data.get('assign_roles', [])

        await waiting.delete()
        
        e = discord.Embed(title=f"✅ 종료: {title}", color=0x2ecc71)
        e.add_field(name="요약", value=summary[:500]+"...", inline=False)
        await ctx.send(embed=e)

        # 5-Step Flow
        async def step5_add_tasks():
            if not new_tasks: await ctx.send("💡 등록할 할일 없음"); return
            await ctx.send("📝 **5. 할 일 등록**", view=TaskSelectionView(new_tasks, m_id, ctx.author, ctx.guild.id, self.bot.db))

        async def step4_assign_roles():
            if not assign_roles: await step5_add_tasks(); return
            await ctx.send(f"👤 **4. 역할 부여 제안 ({len(assign_roles)}건)**", view=RoleAssignmentView(assign_roles, ctx.author, step5_add_tasks, ctx.guild))

        async def step3_create_roles():
            if not create_roles: await step4_assign_roles(); return
            await ctx.send(f"🛡️ **3. 새 역할 생성 제안: {', '.join(create_roles)}**", view=RoleCreationView(create_roles, ctx.author, step4_assign_roles, ctx.guild))

        async def step2_create_projects():
            new_proj_info = {}
            for t in new_tasks:
                if t.get('is_new_project'): new_proj_info[t['project']] = t.get('suggested_parent')
            if new_proj_info:
                desc = "\n".join([f"• **{k}** (상위: {v or '없음'})" for k, v in new_proj_info.items()])
                await ctx.send(f"🆕 **2. 새 프로젝트 생성 제안**\n{desc}", view=NewProjectView(new_proj_info, new_tasks, ctx.author, step3_create_roles, ctx.guild.id, self.bot.db))
            else: await step3_create_roles()

        if updates:
            await ctx.send("🔄 **1. 상태 변경 감지**", view=StatusUpdateView(updates, ctx.author, step2_create_projects, self.bot.db))
        else: await step2_create_projects()

    @meeting_group.command(name="목록", description="저장된 회의록을 보여줍니다.")
    @is_authorized()
    async def list_meetings(self, ctx):
        rows = self.bot.db.get_recent_meetings(ctx.guild.id)
        if not rows: await ctx.send("📭 없음"); return
        e = discord.Embed(title=f"📂 {ctx.guild.name} 회의록", color=0xf1c40f)
        for r in rows: e.add_field(name=f"ID [{r[0]}] {r[1]}", value=f"📅 {r[2]} | [이동]({r[4]})", inline=False)
        await ctx.send(embed=e)

    @meeting_group.command(name="조회", description="회의록 상세 내용을 봅니다.")
    @app_commands.describe(id="회의록 ID")
    @is_authorized()
    async def view_meeting(self, ctx, id: int):
        row = self.bot.db.get_meeting_detail(id, ctx.guild.id)
        if not row: await ctx.send("❌ 없음"); return
        chunks = smart_chunk_text(row[2])
        embeds = []
        for i, ch in enumerate(chunks):
            e = discord.Embed(title=f"📂 {row[0]}", description=ch, color=0xf1c40f)
            if row[3]: e.add_field(name="링크", value=f"[이동]({row[3]})", inline=False)
            if len(chunks)>1: e.set_footer(text=f"{i+1}/{len(chunks)}")
            embeds.append(e)
        if embeds: await ctx.send(embed=embeds[0], view=EmbedPaginator(embeds, ctx.author) if len(embeds)>1 else None)

async def setup(bot):
    await bot.add_cog(MeetingCog(bot))