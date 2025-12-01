import discord
from discord.ext import commands
from discord import app_commands
import datetime
import json
from ui import EmbedPaginator, TaskSelectionView, StatusUpdateView, NewProjectView, RoleCreationView, RoleAssignmentView, AutoAssignTaskView
from utils import is_authorized, smart_chunk_text

class MeetingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # meeting_buffer key: channel_id -> thread_id 로 변경
        self.meeting_buffer = {} 

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if message.channel.id in self.meeting_buffer and not message.content.startswith(('!', '/')):
            msg_obj = {'time': message.created_at.strftime("%H:%M"), 'user': message.author.display_name, 'content': message.content}
            self.meeting_buffer[message.channel.id]['messages'].append(msg_obj)

    @commands.hybrid_group(name="회의", description="회의 관리")
    async def meeting_group(self, ctx):
        if ctx.invoked_subcommand is None: await ctx.send_help(ctx.command)

    @meeting_group.command(name="시작", description="회의 스레드를 생성하고 기록을 시작합니다.")
    @app_commands.describe(name="주제")
    @is_authorized()
    async def start_meeting(self, ctx, *, name: str = None):
        if ctx.channel.id in self.meeting_buffer: 
            await ctx.send("🔴 이미 진행 중입니다.")
            return
        if not name: name = f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
        
        try:
            thread = await ctx.channel.create_thread(name=f"🎙️ {name}", type=discord.ChannelType.public_thread, auto_archive_duration=60)
            self.meeting_buffer[thread.id] = {'name': name, 'messages': [], 'jump_url': thread.jump_url}
            await ctx.send(embed=discord.Embed(title="🎙️ 회의실 생성", description=f"{thread.mention} 에서 시작하세요.", color=0xe74c3c))
            await thread.send(f"🔴 **{name}** 기록 시작.")
        except Exception as e:
            await ctx.send(f"❌ 스레드 생성 실패: {e}")

    @meeting_group.command(name="종료", description="회의 종료 및 분석")
    @is_authorized()
    async def stop_meeting(self, ctx):
        if ctx.channel.id not in self.meeting_buffer:
            await ctx.send("⚠️ 기록 중인 스레드가 아닙니다.")
            return

        data = self.meeting_buffer.pop(ctx.channel.id)
        raw = data['messages']
        if not raw: await ctx.send("📝 내용 없음"); return

        txt = "".join([f"[Speaker: {m['user']}] {m['content']}\n" for m in raw])
        waiting = await ctx.send("🤖 AI 분석 중...")

        full_result = await self.bot.ai.generate_meeting_summary(txt)
        lines = full_result.strip().split('\n')
        title = lines[0].replace("제목:", "").strip() if lines[0].startswith("제목:") else data['name']
        summary = "\n".join(lines[1:]).strip() if lines[0].startswith("제목:") else full_result
        m_id = self.bot.db.save_meeting(ctx.guild.id, title, ctx.channel.id, summary, data['jump_url'])

        projs = [r[1] for r in self.bot.db.get_project_tree(ctx.guild.id)]
        active = self.bot.db.get_active_tasks_simple(ctx.guild.id)
        roles = ", ".join([r.name for r in ctx.guild.roles if not r.is_default()])
        mems = ", ".join([m.display_name for m in ctx.guild.members if not m.bot])

        res = await self.bot.ai.extract_tasks_and_updates(txt, ", ".join(projs), active, roles, mems)
        
        await waiting.delete()
        
        e = discord.Embed(title=f"✅ 종료: {title}", color=0x2ecc71)
        e.add_field(name="요약", value=summary[:500]+"...", inline=False)
        await ctx.send(embed=e)

        # [NEW] 스레드 아카이브 (닫기)
        try:
            if isinstance(ctx.channel, discord.Thread):
                await ctx.channel.edit(archived=True, locked=False)
        except Exception as e:
            print(f"스레드 닫기 실패: {e}")

        # Flow 실행 (동일)
        async def step5():
            if not res.get('new_tasks'): await ctx.send("💡 할일 없음"); return
            await ctx.send("📝 **5. 할일 등록**", view=AutoAssignTaskView(res['new_tasks'], m_id, ctx.author, ctx.guild, self.bot.db))
        
        async def step4():
            if not res.get('assign_roles'): await step5(); return
            await ctx.send(f"👤 **4. 역할 부여**", view=RoleAssignmentView(res['assign_roles'], ctx.author, step5, ctx.guild))

        async def step3():
            if not res.get('create_roles'): await step4(); return
            await ctx.send(f"🛡️ **3. 역할 생성**", view=RoleCreationView(res['create_roles'], ctx.author, step4, ctx.guild))

        async def step2():
            new_p = {t['project']: t.get('suggested_parent') for t in res.get('new_tasks',[]) if t.get('is_new_project')}
            if new_p:
                desc = "\n".join([f"• {k} (상위:{v})" for k,v in new_p.items()])
                await ctx.send(f"🆕 **2. 프로젝트 생성**\n{desc}", view=NewProjectView(new_p, res['new_tasks'], ctx.author, step3, ctx.guild.id, self.bot.db))
            else: await step3()

        if res.get('updates'):
            await ctx.send("🔄 **1. 상태 변경**", view=StatusUpdateView(res['updates'], ctx.author, step2, self.bot.db))
        else: await step2()

    # 목록, 조회, 삭제 (기존 유지)
    @meeting_group.command(name="목록")
    @is_authorized()
    async def list(self, ctx):
        rows = self.bot.db.get_recent_meetings(ctx.guild.id)
        if not rows: await ctx.send("📭 없음"); return
        e = discord.Embed(title="📂 회의록", color=0xf1c40f)
        for r in rows: e.add_field(name=f"[{r[0]}] {r[1]}", value=f"📅 {r[2]} | [이동]({r[4]})", inline=False)
        await ctx.send(embed=e)

    @meeting_group.command(name="조회")
    @app_commands.describe(id="ID")
    @is_authorized()
    async def view(self, ctx, id: int):
        r = self.bot.db.get_meeting_detail(id, ctx.guild.id)
        if not r: await ctx.send("❌ 없음"); return
        chunks = smart_chunk_text(r[2])
        embeds = [discord.Embed(title=r[0], description=c, color=0xf1c40f) for c in chunks]
        if r[3]: embeds[0].add_field(name="링크", value=f"[이동]({r[3]})", inline=False)
        await ctx.send(embed=embeds[0], view=EmbedPaginator(embeds, ctx.author) if len(embeds)>1 else None)

    @meeting_group.command(name="삭제")
    @is_authorized()
    async def delete(self, ctx, id: int):
        if self.bot.db.delete_meeting(id, ctx.guild.id): await ctx.send("🗑️ 삭제됨")
        else: await ctx.send("❌ 실패")

async def setup(bot): await bot.add_cog(MeetingCog(bot))