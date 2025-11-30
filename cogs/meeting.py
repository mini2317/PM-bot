import discord
from discord.ext import commands
import datetime
from ui_components import EmbedPaginator, TaskSelectionView, StatusUpdateView, NewProjectView
from utils import is_authorized, smart_chunk_text

class MeetingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.meeting_buffer = {} # {channel_id: {name, messages, jump_url}}

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        # 회의 중일 때 메시지 기록
        if message.channel.id in self.meeting_buffer and not message.content.startswith('!'):
            msg_obj = {
                'time': message.created_at.strftime("%H:%M"),
                'user': message.author.display_name,
                'content': message.content
            }
            self.meeting_buffer[message.channel.id]['messages'].append(msg_obj)

    # 그룹 명령어 정의 (!회의)
    @commands.group(name="회의", invoke_without_command=True)
    async def meeting_group(self, ctx):
        """회의 관련 명령어 도움말을 보여줍니다."""
        embed = discord.Embed(title="🎙️ 회의 관리 시스템", description="아래 명령어를 사용하세요.", color=0xe74c3c)
        embed.add_field(name="!회의 시작 [주제]", value="회의 기록을 시작합니다.", inline=False)
        embed.add_field(name="!회의 종료", value="회의를 종료하고 AI 요약을 생성합니다.", inline=False)
        embed.add_field(name="!회의 목록", value="저장된 회의록 리스트를 봅니다.", inline=False)
        embed.add_field(name="!회의 조회 [ID]", value="특정 회의록 상세 내용을 봅니다.", inline=False)
        embed.add_field(name="!회의 삭제 [ID]", value="회의록을 삭제합니다.", inline=False)
        await ctx.send(embed=embed)

    @meeting_group.command(name="시작")
    @is_authorized()
    async def start_meeting(self, ctx, *, name: str = None):
        if ctx.channel.id in self.meeting_buffer:
            await ctx.send("🔴 이미 이 채널에서 회의가 진행 중입니다.")
            return
        
        if not name:
            name = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} 회의 (진행 중)"
        
        self.meeting_buffer[ctx.channel.id] = {'name': name, 'messages': [], 'jump_url': ctx.message.jump_url}
        
        embed = discord.Embed(title=f"🎙️ 회의 시작", color=0xe74c3c)
        embed.add_field(name="상태", value="🔴 녹음 중 (Recording...)", inline=True)
        embed.add_field(name="제목", value=name, inline=True)
        embed.set_footer(text="!회의 종료 입력 시 자동 저장됩니다.")
        await ctx.send(embed=embed)

    @meeting_group.command(name="종료")
    @is_authorized()
    async def stop_meeting(self, ctx):
        if ctx.channel.id not in self.meeting_buffer:
            await ctx.send("⚠️ 진행 중인 회의가 없습니다.")
            return

        data = self.meeting_buffer.pop(ctx.channel.id)
        raw_messages = data['messages']
        
        if not raw_messages:
            await ctx.send("📝 대화 내용이 없어 저장하지 않습니다.")
            return

        formatted_transcript = ""
        for msg in raw_messages:
            formatted_transcript += f"[Speaker: {msg['user']} | Time: {msg['time']}] {msg['content']}\n"

        waiting = await ctx.send("🤖 AI가 회의를 분석하고 있습니다... (제목 생성, 할일 추출, 상태 변경 감지)")

        # AI 요약
        full_result = await self.bot.ai.generate_meeting_summary(formatted_transcript)
        lines = full_result.strip().split('\n')
        title = lines[0].replace("제목:", "").strip() if lines[0].startswith("제목:") else data['name']
        summary = "\n".join(lines[1:]).strip() if lines[0].startswith("제목:") else full_result

        # DB 저장
        m_id = self.bot.db.save_meeting(ctx.guild.id, title, ctx.channel.id, summary, data['jump_url'])
        
        # Context 로드 및 AI 할일 추출
        existing_projects = self.bot.db.get_all_projects()
        active_tasks = self.bot.db.get_active_tasks_simple(ctx.guild.id)
        
        ai_data = await self.bot.ai.extract_tasks_and_updates(formatted_transcript, existing_projects, active_tasks)
        new_tasks = ai_data.get('new_tasks', [])
        updates = ai_data.get('updates', [])

        await waiting.delete()

        # 결과 전송
        embed = discord.Embed(title=f"✅ 회의 종료: {title}", color=0x2ecc71)
        embed.add_field(name="📄 요약본", value=summary[:500] + ("..." if len(summary)>500 else ""), inline=False)
        embed.add_field(name="AI 분석", value=f"할일: {len(new_tasks)}개 | 변경: {len(updates)}개", inline=False)
        embed.add_field(name="관리", value=f"ID: `{m_id}` | `!회의 조회 {m_id}`", inline=False)
        await ctx.send(embed=embed)

        # Interactive Flow Logic (UI Components 활용)
        async def step3_add_tasks(channel, final_tasks):
            if not final_tasks:
                await channel.send("💡 등록할 새로운 할 일이 없습니다.")
                return
            view = TaskSelectionView(final_tasks, m_id, ctx.author, ctx.guild.id, self.bot.db)
            await channel.send("📝 **최종적으로 등록할 할 일을 선택해주세요:**", view=view)

        async def step2_check_projects(channel, tasks):
            new_proj_info = {}
            for t in tasks:
                if t.get('is_new_project'):
                    new_proj_info[t['project']] = t.get('suggested_parent')
            
            if new_proj_info:
                desc = "\n".join([f"• **{k}** (상위: {v or '없음'})" for k, v in new_proj_info.items()])
                view = NewProjectView(new_proj_info, tasks, ctx.author, step3_add_tasks, ctx.guild.id, self.bot.db)
                await channel.send(f"🆕 **새 프로젝트 제안**\nAI가 다음 구조를 제안했습니다:\n{desc}", view=view)
            else:
                await step3_add_tasks(channel, tasks)

        if updates:
            view = StatusUpdateView(updates, ctx.author, lambda c: step2_check_projects(c, new_tasks), self.bot.db)
            await ctx.send("🔄 **기존 할 일의 상태 변경이 감지되었습니다.**", view=view)
        else:
            await step2_check_projects(ctx.channel, new_tasks)

    @meeting_group.command(name="목록")
    @is_authorized()
    async def list_meetings(self, ctx):
        rows = self.bot.db.get_recent_meetings(ctx.guild.id)
        if not rows:
            await ctx.send("📭 저장된 회의록이 없습니다.")
            return
        embed = discord.Embed(title=f"📂 {ctx.guild.name} 회의록 목록", color=0xf1c40f)
        for r in rows:
            val = f"📅 {r[2]} | 🔗 [이동]({r[4]})"
            embed.add_field(name=f"ID [{r[0]}] {r[1]}", value=val, inline=False)
        await ctx.send(embed=embed)

    @meeting_group.command(name="조회")
    @is_authorized()
    async def view_meeting(self, ctx, m_id: int):
        row = self.bot.db.get_meeting_detail(m_id, ctx.guild.id)
        if not row:
            await ctx.send("❌ 해당 ID의 회의록이 없습니다.")
            return
        name, date, summary, link = row
        
        chunks = smart_chunk_text(summary)
        embeds = []
        for i, chunk in enumerate(chunks):
            e = discord.Embed(title=f"📂 {name} ({date})", description=chunk, color=0xf1c40f)
            if link: e.add_field(name="링크", value=f"[이동]({link})", inline=False)
            if len(chunks)>1: e.set_footer(text=f"Page {i+1}/{len(chunks)}")
            embeds.append(e)
        
        if len(embeds)>1: await ctx.send(embed=embeds[0], view=EmbedPaginator(embeds, ctx.author))
        else: await ctx.send(embed=embeds[0])

    @meeting_group.command(name="삭제")
    @is_authorized()
    async def delete_meeting(self, ctx, m_id: int):
        if self.bot.db.delete_meeting(m_id, ctx.guild.id):
            await ctx.send(f"🗑️ 회의록 **#{m_id}** 삭제 완료.")
        else:
            await ctx.send("❌ 삭제 실패.")

async def setup(bot):
    await bot.add_cog(MeetingCog(bot))