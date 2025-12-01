import discord
from discord.ext import commands
from discord import app_commands
import json
from ui import EmbedPaginator

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        try:
            with open("help_data.json", "r", encoding="utf-8") as f:
                self.cmd_info = json.load(f)
        except Exception as e:
            print(f"⚠️ 도움말 데이터 로드 실패: {e}")
            self.cmd_info = {}

    @commands.hybrid_command(name="도움말", description="봇 사용법과 명령어 설명을 확인합니다.")
    @app_commands.describe(command="상세 내용을 볼 명령어 (예: 회의 시작, 레포등록)")
    async def help_cmd(self, ctx, *, command: str = None):
        """
        봇의 도움말을 보여줍니다. 
        명령어를 입력하면 상세 도움말을, 입력하지 않으면 전체 목록을 보여줍니다.
        """
        # 1. 상세 도움말 요청
        if command:
            # 띄어쓰기 등 입력 정규화 (필요시)
            info = self.cmd_info.get(command)
            
            # 정확히 일치하는 키가 없으면 검색 시도
            if not info:
                for key in self.cmd_info:
                    if command in key: # 부분 일치 검색
                        info = self.cmd_info[key]
                        command = key # 발견된 키로 교체
                        break
            
            if info:
                e = discord.Embed(title=f"❓ 도움말: {command}", color=0x00ff00)
                e.add_field(name="설명", value=info['desc'], inline=False)
                e.add_field(name="사용법", value=f"`{info['usage']}`", inline=False)
                e.add_field(name="예시", value=f"`{info['ex']}`", inline=False)
                await ctx.send(embed=e)
            else:
                await ctx.send(f"❌ `{command}` 명령어를 찾을 수 없습니다.")
        
        # 2. 전체 도움말 목록 (카테고리별)
        else:
            # 카테고리별로 명령어 분류
            categories = {}
            for cmd_name, data in self.cmd_info.items():
                cat = data.get('cat', '기타')
                if cat not in categories:
                    categories[cat] = []
                categories[cat].append((cmd_name, data.get('desc', '').split('\n')[0]))

            embeds = []
            # 카테고리 순서 정의 (원하는 순서대로)
            ordered_cats = ["📋 프로젝트", "🎙️ 회의", "🐙 깃헙", "👑 관리"]
            
            # 정의된 순서대로 Embed 생성
            for cat_name in ordered_cats:
                if cat_name in categories:
                    e = discord.Embed(title=f"{cat_name} 명령어", color=0x3498db)
                    for cmd_name, short_desc in categories[cat_name]:
                        e.add_field(name=f"/{cmd_name}", value=short_desc, inline=False)
                    e.set_footer(text="!도움말 [명령어] 로 상세 설명 확인 | 페이지를 넘겨보세요")
                    embeds.append(e)
            
            # 기타 카테고리 처리
            for cat_name, items in categories.items():
                if cat_name not in ordered_cats:
                    e = discord.Embed(title=f"{cat_name} 명령어", color=0x95a5a6)
                    for cmd_name, short_desc in items:
                        e.add_field(name=f"/{cmd_name}", value=short_desc, inline=False)
                    embeds.append(e)

            if embeds:
                view = EmbedPaginator(embeds, ctx.author)
                await ctx.send(embed=embeds[0], view=view)
            else:
                await ctx.send("표시할 도움말이 없습니다.")

async def setup(bot):
    await bot.add_cog(HelpCog(bot))