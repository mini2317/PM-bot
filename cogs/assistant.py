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
        
        # 1. 멘션 체크
        if self.bot.user not in message.mentions: return
        
        # 2. 비서 채널 체크
        assist_channel_id = self.bot.db.get_assistant_channel(message.guild.id)
        if assist_channel_id and message.channel.id != assist_channel_id:
             return 

        content = message.content.replace(self.bot.user.mention, "").strip()
        if not content: return

        # 3. 컨텍스트 로드
        history = [msg async for msg in message.channel.history(limit=8)]
        chat_ctx = []
        for msg in reversed(history):
            role = "Assistant" if msg.author.bot else "User"
            clean = msg.content.replace(self.bot.user.mention, "@Bot").strip()
            # 봇의 이전 답변 중 디버그용 스크립트 등은 컨텍스트에서 제외하거나 정제하면 더 좋음
            if clean: chat_ctx.append(f"[{role}] {clean}")

        async with message.channel.typing():
            tasks = self.bot.db.get_active_tasks_simple(message.guild.id)
            projs = self.bot.db.get_all_projects()
            
            # 4. AI에게 PML 스크립트 요청
            script = await self.bot.ai.analyze_assistant_input(chat_ctx, tasks, projs, message.guild.id)
            
            # 5. 스크립트 파싱
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
            
            # 6. 응답 처리
            
            # Case A: 질문(ASK)
            if ask_msg:
                await message.reply(f"🤖 {ask_msg}")
                return

            # Case B: 실행할 명령이 있는 경우 (UI 수정됨)
            if commands_to_run:
                clean_script = "\n".join(commands_to_run)
                # SAY 메시지가 없으면 기본 멘트 사용
                display_text = say_msg if say_msg else "요청하신 작업을 수행할까요?"
                
                async def execute_callback(interaction, _):
                    # 인터프리터 실행
                    log = await self.interpreter.execute(clean_script, message)
                    
                    # 현황판 갱신
                    proj_cog = self.bot.get_cog('ProjectCog')
                    if proj_cog: await proj_cog.refresh_dashboard(message.guild.id)
                    
                    # 결과 로그도 너무 길면 보기 싫으니 성공 여부만 깔끔하게 표시하거나
                    # 상세 로그는 3초 뒤 사라지게 하는 등의 UX 개선 가능. 
                    # 일단은 결과 로그를 간략히 보여줍니다.
                    await interaction.message.edit(content=f"✅ **처리 완료!**\n(상세: {log[:100]}...)", view=None)

                view = AssistantActionView(None, message.author, execute_callback)
                
                # [변경] 스크립트(preview) 노출 제거 -> 깔끔한 자연어 제안만 표시
                await message.reply(f"🤖 {display_text}", view=view)
            
            # Case C: 명령 없이 대답(SAY)만 있는 경우
            elif say_msg:
                await message.reply(f"🤖 {say_msg}")

async def setup(bot):
    await bot.add_cog(AssistantCog(bot))