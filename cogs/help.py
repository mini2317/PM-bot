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
    @app_commands.describe(command="상세 내용을 볼 명령어 (예: 회의시작, 레포등록)")
    async def help_cmd(self, ctx, *, command: str = None):
        """
        봇의 도움말을 보여줍니다. 
        명령어를 입력하면 상세 도움말을, 입력하지 않으면 전체 목록을 보여줍니다.
        """
        # 1. 상세 도움말 요청
        if command:
            # 띄어쓰기 제거 후 검색 (예: "회의 시작" -> "회의시작")
            normalized_cmd = command.replace(" ", "")
            info = self.cmd_info.get(normalized_cmd)
            
            # 정확히 일치하는 키가 없으면 검색 시도
            if not info:
                for key in self.cmd_info:
                    if normalized_cmd in key: # 부분 일치 검색
                        info = self.cmd_info[key]
                        normalized_cmd = key # 발견된 키로 교체
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
            # 카테고리별 임베드 생성 함수
            def create_category_embed(title, commands_list, color):
                embed = discord.Embed(title=title, color=color)
                for cmd_name in commands_list:
                    # JSON에서 설명 가져오기, 없으면 기본값
                    info = self.cmd_info.get(cmd_name, {})
                    desc = info.get('desc', '설명 없음').split('\n')[0] # 첫 줄만 사용
                    # 표시할 때는 슬래시 커맨드 스타일로 (스페이스바 등은 info['usage'] 참고하거나 단순화)
                    embed.add_field(name=f"!{cmd_name}", value=desc, inline=False)
                return embed

            e1 = create_category_embed("📋 프로젝트 관리", ["프로젝트생성", "상위설정", "프로젝트구조", "할일등록", "현황판", "완료", "담당"], 0x3498db)
            e1.set_footer(text="Page 1/4")
            
            e2 = create_category_embed("🎙️ 회의 시스템", ["회의시작", "회의종료", "회의목록", "회의조회", "회의삭제"], 0xe74c3c)
            e2.set_footer(text="Page 2/4")
            
            e3 = create_category_embed("🐙 깃헙 & 관리", ["레포등록", "레포삭제", "레포목록", "초기설정", "권한추가", "권한삭제"], 0x9b59b6)
            e3.set_footer(text="Page 3/4")
            
            e4 = create_category_embed("🤖 AI 비서", ["비서설정"], 0x2ecc71)
            e4.set_footer(text="Page 4/4 | !도움말 [명령어] 로 상세 정보 확인")
            
            view = EmbedPaginator([e1, e2, e3, e4], ctx.author)
            await ctx.send(embed=e1, view=view)

async def setup(bot):
    await bot.add_cog(HelpCog(bot))