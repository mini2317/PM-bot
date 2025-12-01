import discord
from discord.ext import commands
from discord import app_commands
from utils import is_authorized

class GithubCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="레포등록", description="Github 레포지토리 알림을 연결합니다.")
    @app_commands.describe(repo_name="Github Owner/Repo 형식 (예: google/guava)")
    @is_authorized()
    async def add_repo(self, ctx, repo_name: str):
        if self.bot.db.add_repo(repo_name, ctx.channel.id, ctx.author.name):
            await ctx.send(f"✅ **{repo_name}** → <#{ctx.channel.id}> 연결 성공.\n(이미 등록된 레포라면 이 채널에도 추가되었습니다)")
        else:
            await ctx.send("❌ 등록 실패.")

    @commands.hybrid_command(name="레포삭제", description="Github 레포지토리 연결을 해제합니다.")
    @app_commands.describe(repo_name="해제할 레포지토리 이름")
    @is_authorized()
    async def remove_repo(self, ctx, repo_name: str):
        if self.bot.db.remove_repo(repo_name, ctx.channel.id):
            await ctx.send(f"🗑️ **{repo_name}** 이 채널에서의 연결 해제.")
        else:
            await ctx.send("❌ 이 채널에 등록되지 않은 레포입니다.")

    @commands.hybrid_command(name="레포목록", description="현재 채널에 연결된 레포지토리 목록을 봅니다.")
    @is_authorized()
    async def list_repos(self, ctx):
        rows = self.bot.db.get_all_repos()
        # 현재 채널과 관련된 것만 필터링하거나 전체 보여주기 (여기선 전체)
        if not rows:
            await ctx.send("📭 연결된 레포지토리가 없습니다.")
            return
        
        embed = discord.Embed(title="🐙 연동된 레포지토리", color=0x6e5494)
        count = 0
        for repo, channel_id in rows:
            # 현재 채널에 등록된 것만 강조하거나 전체 표시
            embed.add_field(name=repo, value=f"📢 <#{channel_id}>", inline=False)
            count += 1
            
        if count == 0:
             await ctx.send("📭 연결된 레포지토리가 없습니다.")
        else:
            await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(GithubCog(bot))