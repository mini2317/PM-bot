import discord
from discord.ext import commands
from discord import app_commands
import datetime
import json
import io
from ui import EmbedPaginator, MeetingTaskView
from utils import is_authorized, smart_chunk_text
from services.meeting_service import process_meeting_result

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

    @meeting_group.command(name="시작", description="회의-보드 포럼에 회의실을 생성합니다.")
    @app_commands.describe(name="회의 주제")
    @is_authorized()
    async def start_meeting(self, ctx, *, name: str = None):
        if ctx.channel.id in self.meeting_buffer: 
            await ctx.send("🔴 이미 진행 중입니다.")
            return
        if not name: name = f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
        
        meeting_forum = None
        project_name = "일반"

        if ctx.channel.category:
            try:
                p_data = self.bot.db.get_project_by_category(ctx.channel.category.id)
                if p_data:
                    project_name = p_data['name']
                    if p_data.get('meeting_channel_id'):
                        meeting_forum = ctx.guild.get_channel(p_data['meeting_channel_id'])
            except: pass

        if not meeting_forum and ctx.channel.category:
            meeting_forum = discord.utils.get(ctx.channel.category.channels, name="🎙️ 회의-보드")

        if not meeting_forum or not isinstance(meeting_forum, discord.ForumChannel):
            await ctx.send("❌ **오류**: '🎙️ 회의-보드' 포럼 채널을 찾을 수 없습니다.")
            return

        try:
            wip_tag = next((t for t in meeting_forum.available_tags if t.name == "진행중"), None)
            tags = [wip_tag] if wip_tag else []
            thread_with_msg = await meeting_forum.create_thread(
                name=f"🎙️ {name} (진행중...)",
                content=f"**[{project_name}] 회의가 시작되었습니다.**\n\n- 주제: {name}\n- 주최자: {ctx.author.mention}\n- 일시: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n🔴 **녹음 중...**\n(회의가 끝나면 **이 게시글 안에서** `/회의 종료`를 입력하세요)",
                applied_tags=tags
            )
            target_thread = thread_with_msg.thread
            start_msg = thread_with_msg.message
            
            self.meeting_buffer[target_thread.id] = {
                'name': name, 'messages': [], 'jump_url': target_thread.jump_url,
                'start_msg_id': start_msg.id, 'project_name': project_name
            }
            await ctx.send(f"✅ **회의실이 생성되었습니다!**\n여기로 이동하세요: {target_thread.mention}")
        except Exception as e: await ctx.send(f"❌ 회의 생성 실패: {e}")

    @meeting_group.command(name="종료", description="회의를 종료하고 분석합니다.")
    @is_authorized()
    async def stop_meeting(self, ctx):
        if ctx.channel.id not in self.meeting_buffer:
            await ctx.send("⚠️ 기록 중인 회의 공간이 아닙니다.")
            return
        data = self.meeting_buffer.pop(ctx.channel.id)
        raw = data['messages']
        if not raw: 
            await ctx.send("📝 대화 내용이 없어 종료합니다.")
            if isinstance(ctx.channel, discord.Thread): await ctx.channel.edit(archived=True)
            return
        # 로직 호출
        await process_meeting_result(ctx, self.bot, data, raw)

    @meeting_group.command(name="목록")
    @is_authorized()
    async def list(self, ctx):
        rows = self.bot.db.get_recent_meetings(ctx.guild.id)
        if not rows: await ctx.send("📭 없음"); return
        e = discord.Embed(title="📂 회의록", color=0xf1c40f)
        for r in rows: e.add_field(name=f"[{r[0]}] {r[1]}", value=f"📅 {r[2]} | [바로가기]({r[4]})", inline=False)
        await ctx.send(embed=e)

    @meeting_group.command(name="조회")
    @app_commands.describe(id="ID")
    @is_authorized()
    async def view(self, ctx, id: int):
        row = self.bot.db.get_meeting_detail(id, ctx.guild.id)
        if not row: await ctx.send("❌ 없음"); return
        try:
            meeting_data = json.loads(row[2])
            summary = meeting_data.get('summary', '')
            
            # [FIX] PDF 생성 제거, JSON만 첨부
            json_bytes = json.dumps(meeting_data, ensure_ascii=False, indent=2).encode('utf-8')
            json_file = discord.File(io.BytesIO(json_bytes), filename=f"Meeting_{id}_context.json")

            e = discord.Embed(title=f"📂 {row[0]}", description=summary[:3500], color=0xf1c40f)
            if row[3]: e.add_field(name="링크", value=f"[이동]({row[3]})", inline=False)
            
            # 결정사항 표시
            decisions = meeting_data.get('decisions', [])
            if decisions:
                e.add_field(name="결정 사항", value="\n".join([f"• {d}" for d in decisions]), inline=False)

            await ctx.send(embed=e, file=json_file)
        except: await ctx.send("❌ 데이터 손상")

    @meeting_group.command(name="삭제")
    @is_authorized()
    async def delete(self, ctx, id: int):
        if self.bot.db.delete_meeting(id, ctx.guild.id): await ctx.send("🗑️ 삭제됨")
        else: await ctx.send("❌ 실패")

async def setup(bot): await bot.add_cog(MeetingCog(bot))