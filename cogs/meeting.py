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
        
        # [변경] 메시지가 온 채널(스레드) ID가 버퍼에 있는지 확인
        if message.channel.id in self.meeting_buffer and not message.content.startswith(('!', '/')):
            msg_obj = {'time': message.created_at.strftime("%H:%M"), 'user': message.author.display_name, 'content': message.content}
            self.meeting_buffer[message.channel.id]['messages'].append(msg_obj)

    @commands.hybrid_group(name="회의", description="회의 관리")
    async def meeting_group(self, ctx):
        if ctx.invoked_subcommand is None: await ctx.send_help(ctx.command)

    @meeting_group.command(name="시작", description="회의 스레드를 생성하고 기록을 시작합니다.")
    @app_commands.describe(name="회의 주제")
    @is_authorized()
    async def start_meeting(self, ctx, *, name: str = None):
        if not name: name = f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
        
        # [NEW] 스레드 생성
        try:
            # 명령어 친 채널에서 스레드 생성
            thread = await ctx.channel.create_thread(name=f"🎙️ {name}", type=discord.ChannelType.public_thread, auto_archive_duration=60)
            
            self.meeting_buffer[thread.id] = {'name': name, 'messages': [], 'jump_url': thread.jump_url}
            
            embed = discord.Embed(title="🎙️ 회의실 생성 완료", description=f"{thread.mention} 에서 회의를 진행해주세요.\n종료 시 해당 스레드에서 `/회의 종료`를 입력하세요.", color=0xe74c3c)
            await ctx.send(embed=embed)
            
            # 스레드 내부에 시작 메시지 전송
            await thread.send(f"🔴 **{name}** 기록이 시작되었습니다. 자유롭게 대화하세요.")
            
        except Exception as e:
            await ctx.send(f"❌ 스레드 생성 실패: {e}\n(봇에게 '공개 스레드 생성' 권한이 있는지 확인하세요)")

    @meeting_group.command(name="종료", description="회의를 종료하고 분석합니다.")
    @is_authorized()
    async def stop_meeting(self, ctx):
        # [변경] 명령어가 스레드 안에서 실행되었는지 확인
        if ctx.channel.id not in self.meeting_buffer:
            await ctx.send("⚠️ 현재 기록 중인 회의 스레드가 아닙니다.")
            return

        data = self.meeting_buffer.pop(ctx.channel.id)
        raw_messages = data['messages']
        
        if not raw_messages:
            await ctx.send("📝 대화 내용이 없어 저장하지 않습니다.")
            # 빈 스레드면 아카이브 할 수도 있음
            return

        txt = "".join([f"[Speaker: {m['user']}] {m['content']}\n" for m in raw_messages])
        waiting = await ctx.send("🤖 AI 분석 중... 잠시만 기다려주세요.")

        # 1. 요약
        full_result = await self.bot.ai.generate_meeting_summary(txt)
        lines = full_result.strip().split('\n')
        title = lines[0].replace("제목:", "").strip() if lines[0].startswith("제목:") else data['name']
        summary = "\n".join(lines[1:]).strip() if lines[0].startswith("제목:") else full_result
        
        # DB 저장 (스레드 링크 포함)
        m_id = self.bot.db.save_meeting(ctx.guild.id, title, ctx.channel.id, summary, data['jump_url'])

        # 2. 데이터 추출
        projs_list = [r[1] for r in self.bot.db.get_project_tree(ctx.guild.id)]
        projs_str = json.dumps(projs_list, ensure_ascii=False)
        active_tasks = self.bot.db.get_active_tasks_simple(ctx.guild.id)
        roles = ", ".join([r.name for r in ctx.guild.roles if not r.is_default()])
        mems = ", ".join([m.display_name for m in ctx.guild.members if not m.bot])

        res = await self.bot.ai.extract_tasks_and_updates(txt, projs_str, active_tasks, roles, mems)
        
        await waiting.delete()
        
        # 요약본 전송
        e = discord.Embed(title=f"✅ 종료: {title}", color=0x2ecc71)
        e.add_field(name="요약", value=summary[:500]+"...", inline=False)
        await ctx.send(embed=e)

        # 6-Step Flow Start
        async def step5_final():
            if not res.get('new_tasks'): await ctx.send("💡 할일 없음"); return
            await ctx.send("📝 **5. 할 일 등록 및 담당자 배정**", view=AutoAssignTaskView(res['new_tasks'], m_id, ctx.author, ctx.guild, self.bot.db))

        async def step4():
            if not res.get('assign_roles'): await step5_final(); return
            await ctx.send(f"👤 **4. 역할 부여 제안**", view=RoleAssignmentView(res['assign_roles'], ctx.author, step5_final, ctx.guild))

        async def step3():
            if not res.get('create_roles'): await step4(); return
            await ctx.send(f"🛡️ **3. 새 역할 생성 제안**", view=RoleCreationView(res['create_roles'], ctx.author, step4, ctx.guild))

        async def step2():
            new_p = {}
            for t in res.get('new_tasks', []):
                if t.get('is_new_project'):
                    new_p[t['project']] = t.get('suggested_parent')
            
            if new_p:
                desc = "\n".join([f"• **{k}** (상위: {v or '없음'})" for k, v in new_p.items()])
                await ctx.send(f"🆕 **2. 프로젝트 생성 제안**\n{desc}", view=NewProjectView(new_p, res['new_tasks'], ctx.author, step3, ctx.guild.id, self.bot.db))
            else: await step3()

        if res.get('updates'):
            await ctx.send("🔄 **1. 상태 변경 감지**", view=StatusUpdateView(res['updates'], ctx.author, step2, self.bot.db))
        else: await step2()

        # [Option] 스레드 아카이브 (선택사항)
        # await ctx.channel.edit(archived=True)

    # 목록, 조회, 삭제 명령어는 기존과 동일하게 유지
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