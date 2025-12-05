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
        if self.bot.user not in message.mentions: return
        
        assist_channel_id = self.bot.db.get_assistant_channel(message.guild.id)
        if assist_channel_id and message.channel.id != assist_channel_id: return

        content = message.content.replace(self.bot.user.mention, "").strip()
        if not content: return

        # Context Load
        history = [msg async for msg in message.channel.history(limit=8)]
        chat_ctx = []
        for msg in reversed(history):
            name = msg.author.display_name
            clean = msg.content.replace(self.bot.user.mention, "@Bot").strip()
            if clean: chat_ctx.append(f"[{name}] {clean}")

        async with message.channel.typing():
            tasks = self.bot.db.get_active_tasks_simple(message.guild.id)
            projs = self.bot.db.get_all_projects()
            
            # 1. AI로부터 PML 스크립트 생성
            script = await self.bot.ai.analyze_assistant_input(chat_ctx, tasks, projs, message.guild.id)
            
            if "SAY NONE" in script: return # 무시

            # 2. 스크립트 파싱
            lines = script.split('\n')
            commands_to_run = []
            say_msg = ""
            ask_msg = ""
            
            for line in lines:
                line = line.strip()
                if not line: continue
                
                if line.startswith("SAY"):
                    parts = line.split(' ', 1)
                    if len(parts) > 1: say_msg = parts[1].strip('"')
                elif line.startswith("ASK"):
                    parts = line.split(' ', 1)
                    if len(parts) > 1: ask_msg = parts[1].strip('"')
                else:
                    commands_to_run.append(line)
            
            # 3. 실행 분기
            
            # 질문이 있으면 바로 물어봄
            if ask_msg:
                await message.reply(f"🤖 {ask_msg}")
                return

            # 명령어가 있으면 확인 후 실행
            if commands_to_run:
                clean_script = "\n".join(commands_to_run)
                display_text = say_msg if say_msg else "다음 작업을 수행할까요?"
                
                async def execute_callback(interaction, _):
                    # 인터프리터 실행
                    log = await self.interpreter.execute(clean_script, message)
                    
                    # 현황판 갱신
                    proj_cog = self.bot.get_cog('ProjectCog')
                    if proj_cog: await proj_cog.refresh_dashboard(message.guild.id)
                    
                    # 로그가 너무 길면 파일로, 짧으면 텍스트로
                    if len(log) > 1900:
                        import io
                        f = discord.File(io.BytesIO(log.encode()), filename="result.txt")
                        await interaction.message.edit(content=f"✅ **처리 완료**", attachments=[f], view=None)
                    else:
                        await interaction.message.edit(content=f"✅ **처리 완료**\n```{log}```", view=None)

                preview = f"```bash\n{clean_script}\n```"
                view = AssistantActionView(None, message.author, execute_callback)
                await message.reply(f"🤖 {display_text}\n{preview}", view=view)
            
            # 명령어 없이 말만 있으면 대답
            elif say_msg:
                await message.reply(f"🤖 {say_msg}")

async def setup(bot):
    await bot.add_cog(AssistantCog(bot))