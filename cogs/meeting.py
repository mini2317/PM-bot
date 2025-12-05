import discord
from discord.ext import commands
from discord import app_commands
import datetime
import json
import io, asyncio
from ui import EmbedPaginator, TaskSelectionView, StatusUpdateView, NewProjectView, RoleCreationView, RoleAssignmentView, AutoAssignTaskView
from utils import is_authorized, smart_chunk_text
from services.pdf import generate_meeting_pdf

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
        
        if not isinstance(ai_summary_json, dict):
            ai_summary_json = {"title": data['name'], "summary": str(ai_summary_json), "agenda": [], "decisions": []}
        
        # [FIX] 날짜 유효성 검사 및 강제 보정
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        date_str = ai_summary_json.get('date', today_str)
        # 날짜 형식이 이상하면(길이가 다르거나 등) 오늘 날짜로 대체
        if len(date_str) != 10 or not date_str[0].isdigit():
            ai_summary_json['date'] = today_str
            date_str = today_str

        title = ai_summary_json.get('title', data['name'])
        summary_text = ai_summary_json.get('summary', '요약 없음')
        
        summary_dump = json.dumps(ai_summary_json, ensure_ascii=False)
        m_id = self.bot.db.save_meeting(ctx.guild.id, title, ctx.channel.id, summary_dump, data['jump_url'])

        # 2. PDF 생성
        try:
            pdf_buffer = await asyncio.to_thread(generate_meeting_pdf, ai_summary_json)
            pdf_file = discord.File(io.BytesIO(pdf_buffer.getvalue()), filename=f"Meeting_{m_id}.pdf")
        except Exception as e:
            print(f"PDF Error: {e}")
            pdf_file = None

        # 3. 태스크 분석
        projs = [r[1] for r in self.bot.db.get_project_tree(ctx.guild.id)]
        active = self.bot.db.get_active_tasks_simple(ctx.guild.id)
        roles = ", ".join([r.name for r in ctx.guild.roles if not r.is_default()])
        mems = ", ".join([m.display_name for m in ctx.guild.members if not m.bot])

        res = await self.bot.ai.extract_tasks_and_updates(txt, ", ".join(projs), active, roles, mems)
        
        await waiting.delete()
        
        # 4. 결과 전송
        e = discord.Embed(title=f"✅ 종료: {title}", color=0x2ecc71)
        e.add_field(name="📄 요약", value=summary_text[:500]+"..." if len(summary_text)>500 else summary_text, inline=False)
        decisions = ai_summary_json.get('decisions', [])
        if decisions:
            dec_text = "\n".join([f"• {d}" for d in decisions[:3]])
            if len(decisions) > 3: dec_text += "\n..."
            e.add_field(name="결정 사항", value=dec_text, inline=False)

        await ctx.send(embed=e, file=pdf_file if pdf_file else None)

        async def close_thread():
            try:
                await ctx.send("🔒 스레드를 보관합니다.")
                if isinstance(ctx.channel, discord.Thread): await ctx.channel.edit(archived=True, locked=False)
            except: pass

        # 5-Step Flow
        async def step5_final():
            new_tasks = res.get('new_tasks', [])
            if not new_tasks:
                await ctx.send("💡 추가된 할 일이 없습니다.")
                await close_thread()
                return
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
        name, date, summary_str, link = row
        
        try:
            meeting_data = json.loads(summary_str)
            summary_text = meeting_data.get('summary', '요약 없음')
            pdf_buffer = await asyncio.to_thread(generate_meeting_pdf, meeting_data)
            pdf_file = discord.File(io.BytesIO(pdf_buffer.getvalue()), filename=f"Meeting_{id}.pdf")
            
            e = discord.Embed(title=f"📂 {name} ({date})", description=summary_text, color=0xf1c40f)
            if link: e.add_field(name="링크", value=f"[이동]({link})", inline=False)
            if meeting_data.get('decisions'):
                e.add_field(name="결정 사항", value="\n".join([f"• {d}" for d in meeting_data['decisions'][:5]]), inline=False)
            await ctx.send(embed=e, file=pdf_file)
        except json.JSONDecodeError:
            await ctx.send(f"📂 **{name}**\n{summary_str}")

    @meeting_group.command(name="삭제")
    @is_authorized()
    async def delete(self, ctx, id: int):
        if self.bot.db.delete_meeting(id, ctx.guild.id): await ctx.send("🗑️ 삭제됨")
        else: await ctx.send("❌ 실패")

async def setup(bot): await bot.add_cog(MeetingCog(bot))