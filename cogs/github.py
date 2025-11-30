import discord
from discord.ext import commands
from utils import is_authorized

class GithubCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="레포등록")
    @is_authorized()
    async def add_repo(self, ctx, repo_name: str):
        if self.bot.db.add_repo(repo_name, ctx.channel.id, ctx.author.name):
            await ctx.send(f"✅ **{repo_name}** → <#{ctx.channel.id}> 연결 성공.")
        else:
            await ctx.send("❌ 등록 실패.")

    @commands.command(name="레포삭제")
    @is_authorized()
    async def remove_repo(self, ctx, repo_name: str):
        if self.bot.db.remove_repo(repo_name, ctx.channel.id):
            await ctx.send(f"🗑️ **{repo_name}** 연결 해제.")
        else:
            await ctx.send("❌ 이 채널에 등록되지 않은 레포입니다.")

    @commands.command(name="레포목록")
    @is_authorized()
    async def list_repos(self, ctx):
        rows = self.bot.db.get_all_repos()
        if not rows:
            await ctx.send("📭 연결된 레포지토리가 없습니다.")
            return
        embed = discord.Embed(title="🐙 연동된 레포지토리", color=0x6e5494)
        for repo, channel_id in rows:
            embed.add_field(name=repo, value=f"📢 <#{channel_id}>", inline=False)
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(GithubCog(bot))