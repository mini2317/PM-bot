import discord
from discord.ext import commands
from discord import app_commands
from utils import is_authorized

class AssistantCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="비서설정", description="이 채널을 AI 비서 채널로 설정합니다. (모든 대화를 듣고 업무를 처리함)")
    @is_authorized()
    async def set_assistant(self, ctx):
        self.bot.db.set_assistant_channel(ctx.guild.id, ctx.channel.id)
        await ctx.send(f"🤖 **AI 비서 활성화!**\n이제 이 채널({ctx.channel.mention})에서 말하는 내용은 제가 듣고 프로젝트에 반영하겠습니다.\n예: *'로그인 기능 다 만들었어'*, *'디자인 수정사항 할 일로 등록해줘'*")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        # 1. 비서 채널인지 확인
        assist_channel_id = self.bot.db.get_assistant_channel(message.guild.id)
        if message.channel.id != assist_channel_id:
            return

        # 2. 명령어인 경우 무시 (!, /)
        if message.content.startswith(('!', '/')):
            return

        # 3. AI 분석 요청
        async with message.channel.typing():
            active_tasks = self.bot.db.get_active_tasks_simple(message.guild.id)
            result = await self.bot.ai.analyze_assistant_input(message.content, active_tasks)
            
            action = result.get('action')
            comment = result.get('comment', '')

            # 4. 액션 실행
            if action == 'complete_task':
                tid = result.get('task_id')
                if tid and self.bot.db.update_task_status(tid, "DONE"):
                    await message.reply(f"✅ {comment} (Task #{tid})")
                    # 현황판 갱신 시도 (ProjectCog가 로드되어 있다면)
                    proj_cog = self.bot.get_cog('ProjectCog')
                    if proj_cog: await proj_cog.refresh_dashboard(message.guild.id)
                else:
                    await message.reply("⚠️ 해당 작업을 찾을 수 없습니다.")

            elif action == 'add_task':
                content = result.get('content')
                project = result.get('project', '일반')
                if content:
                    tid = self.bot.db.add_task(message.guild.id, project, content)
                    await message.reply(f"✅ {comment} (ID: #{tid})")
                    proj_cog = self.bot.get_cog('ProjectCog')
                    if proj_cog: await proj_cog.refresh_dashboard(message.guild.id)

            elif action == 'assign_task':
                # 담당자 배정 로직은 멤버 검색이 필요하므로 복잡할 수 있음 (여기선 생략하거나 간단히 처리)
                await message.reply(f"🤖 {comment} (담당자 변경은 아직 수동으로 해주세요!)")

            else:
                # 잡담이거나 액션이 없을 때 (너무 시끄러우면 이 부분 주석 처리)
                # await message.reply(comment) 
                pass

async def setup(bot):
    await bot.add_cog(AssistantCog(bot))