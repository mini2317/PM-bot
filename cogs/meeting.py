import discord
from discord.ext import commands
from discord import app_commands
import datetime, json, io, asyncio
from ui import EmbedPaginator, TaskSelectionView, StatusUpdateView, NewProjectView, RoleCreationView, RoleAssignmentView, AutoAssignTaskView
from utils import is_authorized, smart_chunk_text
from services.pdf import generate_meeting_pdf # [NEW] PDF 생성 함수 임포트

class MeetingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.meeting_buffer = {} 

    # ... (on_message, start_meeting 등 기존 코드 유지) ...
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
        except Exception as e: await ctx.send(f"❌ 실패: {e}")

    @meeting_group.command(name="종료", description="회의 종료 및 분석")
    @is_authorized()
    async def stop_meeting(self, ctx):
        if ctx.channel.id not in self.meeting_buffer: await ctx.send("⚠️ 스레드 아님"); return
        data = self.meeting_buffer.pop(ctx.channel.id)
        if not data['messages']: await ctx.send("📝 내용 없음"); return

        txt = "".join([f"[Speaker: {m['user']}] {m['content']}\n" for m in data['messages']])
        waiting = await ctx.send("🤖 AI 분석 중...")

        # 1. AI 요약 (JSON 반환)
        ai_summary_json = await self.bot.ai.generate_meeting_summary(txt)
        
        # JSON 파싱 실패 대비 (기본값 설정)
        if not isinstance(ai_summary_json, dict):
            ai_summary_json = {
                "title": data['name'], 
                "summary": str(ai_summary_json), 
                "agenda": [], 
                "decisions": []
            }
        
        title = ai_summary_json.get('title', data['name'])
        summary_text = ai_summary_json.get('summary', '요약 없음')
        
        # DB 저장 (JSON을 문자열로 변환하여 저장)
        summary_dump = json.dumps(ai_summary_json, ensure_ascii=False)
        m_id = self.bot.db.save_meeting(ctx.guild.id, title, ctx.channel.id, summary_dump, data['jump_url'])

        # 2. PDF 생성
        pdf_buffer = await asyncio.to_thread(generate_meeting_pdf, ai_summary_json)
        pdf_file = discord.File(io.BytesIO(pdf_buffer.getvalue()), filename=f"Meeting_{m_id}.pdf")

        # 3. 태스크 분석
        projs = [r[1] for r in self.bot.db.get_project_tree(ctx.guild.id)]
        active = self.bot.db.get_active_tasks_simple(ctx.guild.id)
        roles = ", ".join([r.name for r in ctx.guild.roles if not r.is_default()])
        mems = ", ".join([m.display_name for m in ctx.guild.members if not m.bot])

        res = await self.bot.ai.extract_tasks_and_updates(txt, ", ".join(projs), active, roles, mems)
        
        await waiting.delete()
        
        # 4. 결과 전송 (Embed + PDF)
        e = discord.Embed(title=f"✅ 종료: {title}", color=0x2ecc71)
        e.add_field(name="📄 요약", value=summary_text[:500]+"..." if len(summary_text)>500 else summary_text, inline=False)
        
        # 결정 사항이 있으면 Embed에도 표시
        decisions = ai_summary_json.get('decisions', [])
        if decisions:
            dec_text = "\n".join([f"• {d}" for d in decisions[:3]])
            if len(decisions) > 3: dec_text += "\n..."
            e.add_field(name="결정 사항", value=dec_text, inline=False)

        await ctx.send(embed=e, file=pdf_file)

        try:
            if isinstance(ctx.channel, discord.Thread): await ctx.channel.edit(archived=True, locked=False)
        except: pass

        # 5-Step Flow (기존 동일)
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
            if new_p: await ctx.send(f"🆕 **2. 프로젝트 생성**", view=NewProjectView(new_p, res['new_tasks'], ctx.author, step3, ctx.guild.id, self.bot.db))
            else: await step3()
        
        if res.get('updates'): await ctx.send("🔄 **1. 상태 변경**", view=StatusUpdateView(res['updates'], ctx.author, step2, self.bot.db))
        else: await step2()

    # 목록 (기존 유지)
    @meeting_group.command(name="목록")
    @is_authorized()
    async def list(self, ctx):
        rows = self.bot.db.get_recent_meetings(ctx.guild.id)
        if not rows: await ctx.send("📭 없음"); return
        e = discord.Embed(title="📂 회의록", color=0xf1c40f)
        for r in rows: e.add_field(name=f"ID [{r[0]}] {r[1]}", value=f"📅 {r[2]} | [이동]({r[4]})", inline=False)
        await ctx.send(embed=e)

    @meeting_group.command(name="조회")
    @app_commands.describe(id="ID")
    @is_authorized()
    async def view(self, ctx, id: int):
        row = self.bot.db.get_meeting_detail(id, ctx.guild.id)
        if not row: await ctx.send("❌ 없음"); return
        
        # row: (name, date, summary_str, jump_url)
        name, date, summary_str, link = row
        
        # JSON 파싱 시도
        try:
            meeting_data = json.loads(summary_str)
            summary_text = meeting_data.get('summary', '요약 없음')
            
            # PDF 재생성
            pdf_buffer = await asyncio.to_thread(generate_meeting_pdf, meeting_data)
            pdf_file = discord.File(io.BytesIO(pdf_buffer.getvalue()), filename=f"Meeting_{id}.pdf")
            
            e = discord.Embed(title=f"📂 {name} ({date})", description=summary_text, color=0xf1c40f)
            if link: e.add_field(name="링크", value=f"[이동]({link})", inline=False)
            
            decisions = meeting_data.get('decisions', [])
            if decisions:
                e.add_field(name="결정 사항", value="\n".join([f"• {d}" for d in decisions[:5]]), inline=False)
                
            await ctx.send(embed=e, file=pdf_file)
            
        except json.JSONDecodeError:
            # 구버전 데이터(텍스트만 있는 경우) 처리
            await ctx.send(f"📂 **{name}**\n{summary_str}")

    @meeting_group.command(name="삭제")
    @is_authorized()
    async def delete(self, ctx, id: int):
        if self.bot.db.delete_meeting(id, ctx.guild.id): await ctx.send("🗑️ 삭제됨")
        else: await ctx.send("❌ 실패")

async def setup(bot): await bot.add_cog(MeetingCog(bot))