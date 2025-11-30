import discord
from discord.ext import commands
from discord import app_commands
import json
# [변경] ui 패키지 사용
from ui import EmbedPaginator

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        try:
            with open("help_data.json", "r", encoding="utf-8") as f: self.cmd_info = json.load(f)
        except: self.cmd_info = {}

    @commands.hybrid_command(name="도움말", description="사용법 확인")
    async def help_cmd(self, ctx, command: str = None):
        if command:
            info = self.cmd_info.get(command)
            if info:
                e = discord.Embed(title=f"❓ !{command}", color=0x00ff00)
                e.add_field(name="설명", value=info['desc'], inline=False)
                e.add_field(name="예시", value=f"`{info['ex']}`", inline=False)
                await ctx.send(embed=e)
            else: await ctx.send("❌ 없음")
        else:
            def mk_emb(t, cmds, c):
                e = discord.Embed(title=t, color=c)
                for cmd in cmds:
                    desc = self.cmd_info.get(cmd, {}).get('desc', '').split('\n')[0]
                    e.add_field(name=f"!{cmd}", value=desc, inline=False)
                return e
            
            e1 = mk_emb("📋 프로젝트", ["프로젝트생성", "상위설정", "할일등록", "현황판", "완료", "담당"], 0x3498db)
            e2 = mk_emb("🎙️ 회의", ["회의시작", "회의종료", "회의목록", "회의조회"], 0xe74c3c)
            e3 = mk_emb("🐙 기타", ["레포등록", "권한추가"], 0x9b59b6)
            
            await ctx.send(embed=e1, view=EmbedPaginator([e1,e2,e3], ctx.author))

async def setup(bot): await bot.add_cog(HelpCog(bot))