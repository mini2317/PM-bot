import discord
from discord.ext import commands
from discord import app_commands
import datetime
# [변경] ui 패키지에서 필요한 View 가져오기 (AutoAssignTaskView 포함)
from ui import EmbedPaginator, TaskSelectionView, StatusUpdateView, NewProjectView, RoleCreationView, RoleAssignmentView, AutoAssignTaskView
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

    @commands.hybrid_group(name="회의", description="회의 관리")
    async def meeting_group(self, ctx):
        if ctx.invoked_subcommand is None: await ctx.send_help(ctx.command)

    @meeting_group.command(name="시작", description="회의 기록 시작")
    @app_commands.describe(name="주제")
    @is_authorized()
    async def start_meeting(self, ctx, *, name: str = None):
        if ctx.channel.id in self.meeting_buffer: await ctx.send("🔴 진행 중"); return
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
        # 스레드 체크
        if ctx.channel.id not in self.meeting_buffer:
            await ctx.send("⚠️ 기록 중인 회의 스레드가 아닙니다.")
            return

        data = self.meeting_buffer.pop(ctx.channel.id)
        raw = data['messages']
        if not raw: await ctx.send("📝 내용 없음"); return

        txt = "".join([f"[Speaker: {m['user']}] {m['content']}\n" for m in raw])
        waiting = await ctx.send("🤖 AI 분석 중... (상호작용 후 스레드가 닫힙니다)")

        # 1. 요약 & 저장
        full_result = await self.bot.ai.generate_meeting_summary(txt)
        lines = full_result.strip().split('\n')
        title = lines[0].replace("제목:", "").strip() if lines[0].startswith("제목:") else data['name']
        summary = "\n".join(lines[1:]).strip() if lines[0].startswith("제목:") else full_result
        m_id = self.bot.db.save_meeting(ctx.guild.id, title, ctx.channel.id, summary, data['jump_url'])

        # 2. 분석 데이터 추출
        projs = [r[1] for r in self.bot.db.get_project_tree(ctx.guild.id)]
        active = self.bot.db.get_active_tasks_simple(ctx.guild.id)
        roles = ", ".join([r.name for r in ctx.guild.roles if not r.is_default()])
        mems = ", ".join([m.display_name for m in ctx.guild.members if not m.bot])

        res = await self.bot.ai.extract_tasks_and_updates(txt, ", ".join(projs), active, roles, mems)
        
        await waiting.delete()
        
        e = discord.Embed(title=f"✅ 종료: {title}", color=0x2ecc71)
        e.add_field(name="요약", value=summary[:500]+"...", inline=False)
        await ctx.send(embed=e)

        # [NEW] 스레드 닫기 콜백 함수 정의
        async def close_thread():
            try:
                await ctx.send("🔒 모든 처리가 완료되어 스레드를 닫습니다.")
                if isinstance(ctx.channel, discord.Thread):
                    await ctx.channel.edit(archived=True, locked=False)
            except Exception as e:
                print(f"스레드 닫기 실패: {e}")

        # 5-Step Flow (콜백 전달)
        async def step5_final():
            new_tasks = res.get('new_tasks', [])
            if not new_tasks:
                await ctx.send("💡 등록할 할일이 없습니다.")
                await close_thread() # 할 일 없으면 바로 닫기
                return
            
            # [변경] AutoAssignTaskView에 close_thread 콜백 전달
            view = AutoAssignTaskView(new_tasks, m_id, ctx.author, ctx.guild, self.bot.db, cleanup_callback=close_thread)
            await ctx.send("📝 **5. 할 일 등록 및 담당자 배정**", view=view)

        async def step4():
            assigns = res.get('assign_roles', [])
            if not assigns: await step5_final(); return
            await ctx.send(f"👤 **4. 역할 부여 제안 ({len(assigns)}건)**", view=RoleAssignmentView(assigns, ctx.author, step5_final, ctx.guild))

        async def step3():
            creates = res.get('create_roles', [])
            if not creates: await step4(); return
            await ctx.send(f"🛡️ **3. 새 역할 생성 제안: {', '.join(creates)}**", view=RoleCreationView(creates, ctx.author, step4, ctx.guild))

        async def step2():
            new_tasks = res.get('new_tasks', [])
            new_p = {}
            for t in new_tasks:
                if t.get('is_new_project'): new_p[t['project']] = t.get('suggested_parent')
            
            if new_p:
                desc = "\n".join([f"• **{k}** (상위: {v or '없음'})" for k, v in new_p.items()])
                await ctx.send(f"🆕 **2. 프로젝트 생성 제안**\n{desc}", view=NewProjectView(new_p, new_tasks, ctx.author, step3, ctx.guild.id, self.bot.db))
            else: await step3()

        if res.get('updates'):
            await ctx.send("🔄 **1. 상태 변경 감지**", view=StatusUpdateView(res['updates'], ctx.author, step2, self.bot.db))
        else: await step2()

    # (목록, 조회, 삭제 명령어는 그대로 유지)
    @meeting_group.command(name="목록")
    @is_authorized()
    async def list(self, ctx):
        rows = self.bot.db.get_recent_meetings(ctx.guild.id)
        if not rows: await ctx.send("📭 없음"); return
        e = discord.Embed(title="📂 회의록", color=0xf1c40f)
        for r in rows: e.add_field(name=f"[{r[0]}] {r[1]}", value=f"📅 {r[2]} | [이동]({r[4]})", inline=False)
        await ctx.send(embed=e)

    @meeting_group.command(name="조회")
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