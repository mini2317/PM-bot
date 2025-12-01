import discord
from discord.ext import commands
from discord import app_commands
from utils import is_authorized

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="권한추가", description="특정 멤버에게 봇 사용 권한을 부여합니다.")
    @app_commands.describe(member="권한을 줄 멤버")
    @is_authorized()
    async def add_auth(self, ctx, member: discord.Member):
        if self.bot.db.add_user(member.id, member.name):
            await ctx.send(f"✅ {member.mention} 님에게 봇 사용 권한 부여.")
        else:
            await ctx.send(f"⚠️ {member.mention} 님은 이미 권한 보유.")

    @commands.hybrid_command(name="권한삭제", description="특정 멤버의 봇 사용 권한을 회수합니다.")
    @app_commands.describe(member="권한을 뺏을 멤버")
    @is_authorized()
    async def rem_auth(self, ctx, member: discord.Member):
        if self.bot.db.remove_user(member.id):
            await ctx.send(f"🗑️ {member.mention} 권한 회수.")
        else:
            await ctx.send("❌ 미등록 유저.")

async def setup(bot):
    await bot.add_cog(AdminCog(bot))