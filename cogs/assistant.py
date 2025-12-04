import discord
from discord.ext import commands
from utils import is_authorized
from services.interpreter import PynapseInterpreter
from ui import AssistantActionView

class AssistantCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.interpreter = PynapseInterpreter(bot)

    @commands.hybrid_command(name="비서설정", description="이 채널을 AI 비서 채널로 설정합니다.")
    @is_authorized()
    async def set_assistant(self, ctx):
        self.bot.db.set_assistant_channel(ctx.guild.id, ctx.channel.id)
        await ctx.send(f"🤖 **AI 비서 활성화!**\n이제 멘션(@{self.bot.user.name})으로 작업을 지시하세요.")

    @commands.hybrid_command(name="비서해제", description="AI 비서 설정을 해제합니다.")
    @is_authorized()
    async def unset_assistant(self, ctx):
        self.bot.db.set_assistant_channel(ctx.guild.id, None)
        await ctx.send("🤖 비서 비활성화 완료.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        # 1. 멘션 체크 (핑 날렸을 때만 반응)
        if self.bot.user not in message.mentions: return
        
        # 2. 비서 채널 체크 (설정된 채널이 있다면 거기서만 반응, 아니면 어디서든)
        assist_channel_id = self.bot.db.get_assistant_channel(message.guild.id)
        if assist_channel_id and message.channel.id != assist_channel_id:
             return # 설정된 채널이 있으면 그곳 외에는 무시

        content = message.content.replace(self.bot.user.mention, "").strip()
        if not content: return

        # 3. 컨텍스트 로드
        history = [msg async for msg in message.channel.history(limit=8)]
        chat_ctx = []
        for msg in reversed(history):
            role = "Assistant" if msg.author.bot else "User"
            clean = msg.content.replace(self.bot.user.mention, "@Bot").strip()
            if clean: chat_ctx.append(f"[{role}] {clean}")

        async with message.channel.typing():
            tasks = self.bot.db.get_active_tasks_simple(message.guild.id)
            projs = self.bot.db.get_all_projects()
            
            # 4. AI에게 PML 스크립트 요청
            script = await self.bot.ai.analyze_assistant_input(chat_ctx, tasks, projs, message.guild.id)
            
            # [DEBUG] 비서의 생각(생성된 스크립트) 노출
            await message.channel.send(f"🐛 **[DEBUG] AI Thought (PML Script):**\n```bash\n{script}\n```")

            # 5. 스크립트 파싱 (SAY, ASK, 그 외 명령)
            lines = script.split('\n')
            commands_to_run = []
            say_msg = ""
            ask_msg = ""
            
            for line in lines:
                line = line.strip()
                if not line: continue
                
                if line.startswith("SAY"):
                    # SAY "내용" 파싱
                    parts = line.split(' ', 1)
                    if len(parts) > 1: say_msg = parts[1].strip('"')
                elif line.startswith("ASK"):
                    parts = line.split(' ', 1)
                    if len(parts) > 1: ask_msg = parts[1].strip('"')
                else:
                    commands_to_run.append(line)
            
            # 6. 응답 처리
            
            # Case A: 질문(ASK)이 있는 경우 - 바로 물어봄
            if ask_msg:
                await message.reply(f"🤖 {ask_msg}")
                return

            # Case B: 실행할 명령이 있는 경우 - 확인 UI
            if commands_to_run:
                clean_script = "\n".join(commands_to_run)
                display_text = say_msg if say_msg else "다음 작업을 수행할까요?"
                
                async def execute_callback(interaction, _):
                    # 인터프리터 실행
                    log = await self.interpreter.execute(clean_script, message)
                    
                    # 현황판 갱신
                    proj_cog = self.bot.get_cog('ProjectCog')
                    if proj_cog: await proj_cog.refresh_dashboard(message.guild.id)
                    
                    await interaction.message.edit(content=f"✅ **실행 완료**\n```{log}```", view=None)

                # 미리보기 제공
                preview = f"```bash\n{clean_script}\n```"
                view = AssistantActionView(None, message.author, execute_callback)
                await message.reply(f"🤖 **[제안]** {display_text}\n\n다음 명령을 실행할까요?\n{preview}", view=view)
            
            # Case C: 명령 없이 대답(SAY)만 있는 경우
            elif say_msg:
                await message.reply(f"🤖 {say_msg}")

async def setup(bot):
    await bot.add_cog(AssistantCog(bot))