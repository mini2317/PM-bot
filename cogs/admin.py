import discord
from discord.ext import commands
from utils import is_authorized

class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="권한추가")
    @is_authorized()
    async def add_auth(self, ctx, m: discord.Member):
        if self.bot.db.add_user(m.id, m.name): await ctx.send(f"✅ {m.mention} 권한 부여")
        else: await ctx.send("이미 있음")

    @commands.command(name="권한삭제")
    @is_authorized()
    async def rem_auth(self, ctx, m: discord.Member):
        if self.bot.db.remove_user(m.id): await ctx.send(f"🗑️ {m.mention} 권한 회수")
        else: await ctx.send("미등록 유저")

async def setup(bot):
    await bot.add_cog(AdminCog(bot))