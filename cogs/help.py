import discord
from discord.ext import commands
from discord import app_commands
import json
from ui_components import EmbedPaginator

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        try:
            with open("help_data.json", "r", encoding="utf-8") as f:
                self.cmd_info = json.load(f)
        except:
            self.cmd_info = {}

    @commands.hybrid_command(name="도움말", description="봇 사용법을 확인합니다.")
    @app_commands.describe(command="상세 설명을 볼 명령어 (선택)")
    async def help_cmd(self, ctx, command: str = None):
        if command:
            info = self.cmd_info.get(command)
            if info:
                e = discord.Embed(title=f"❓ !{command}", color=0x00ff00)
                e.add_field(name="설명", value=info['desc'], inline=False)
                e.add_field(name="사용법", value=f"`{info['usage']}`", inline=False)
                await ctx.send(embed=e)
            else:
                await ctx.send("❌ 해당 명령어 도움말이 없습니다.")
        else:
            # 카테고리별 임베드 생성 함수
            def create_category_embed(title, commands_list, color):
                embed = discord.Embed(title=title, color=color)
                for cmd_name in commands_list:
                    # JSON에서 설명 가져오기, 없으면 기본값
                    info = self.cmd_info.get(cmd_name, {})
                    desc = info.get('desc', '설명 없음').split('\n')[0] # 첫 줄만 사용
                    embed.add_field(name=f"!{cmd_name}", value=desc, inline=False)
                return embed

            e1 = create_category_embed("📋 프로젝트 관리", ["프로젝트생성", "상위설정", "프로젝트구조", "할일등록", "현황판", "완료", "담당"], 0x3498db)
            e2 = create_category_embed("🎙️ 회의 시스템", ["회의시작", "회의종료", "회의목록", "회의조회", "회의삭제"], 0xe74c3c)
            e3 = create_category_embed("🐙 깃헙 & 관리", ["레포등록", "레포삭제", "레포목록", "초기설정", "권한추가", "권한삭제"], 0x9b59b6)
            e3.set_footer(text="!도움말 [명령어] 로 상세 정보 확인")
            
            view = EmbedPaginator([e1, e2, e3], ctx.author)
            await ctx.send(embed=e1, view=view)

async def setup(bot):
    await bot.add_cog(HelpCog(bot))