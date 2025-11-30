import discord
from discord.ext import commands
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

    @commands.command(name="도움말")
    async def help_cmd(self, ctx, cmd: str = None):
        if cmd:
            info = self.cmd_info.get(cmd)
            if info:
                e = discord.Embed(title=f"❓ !{cmd}", color=0x00ff00)
                e.add_field(name="설명", value=info['desc'], inline=False)
                e.add_field(name="사용법", value=f"`{info['usage']}`", inline=False)
                await ctx.send(embed=e)
            else:
                await ctx.send("❌ 해당 명령어 도움말이 없습니다.")
        else:
            e1 = discord.Embed(title="📋 프로젝트 관리", description="`!프로젝트` 또는 `!할일`\n생성, 구조, 할일등록, 현황, 완료, 담당", color=0x3498db)
            e2 = discord.Embed(title="🎙️ 회의 시스템", description="`!회의` 로 시작\n시작, 종료, 목록, 조회, 삭제", color=0xe74c3c)
            e3 = discord.Embed(title="🐙 깃헙 & 관리", description="레포등록, 레포삭제, 권한추가", color=0x9b59b6)
            e3.set_footer(text="Page 1/3 | 상세: !도움말 [명령어]")
            
            view = EmbedPaginator([e1, e2, e3], ctx.author)
            await ctx.send(embed=e1, view=view)

async def setup(bot):
    await bot.add_cog(HelpCog(bot))