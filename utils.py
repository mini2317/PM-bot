import discord
from discord.ext import commands

def smart_chunk_text(text, limit=1500):
    chunks = []
    current_chunk = ""
    in_code_block = False
    code_block_lang = ""

    for line in text.split('\n'):
        if len(current_chunk) + len(line) + 20 > limit:
            if in_code_block:
                chunks.append(current_chunk + "\n```")
                current_chunk = f"```{code_block_lang}\n{line}"
            else:
                chunks.append(current_chunk)
                current_chunk = line
        else:
            if current_chunk: current_chunk += "\n" + line
            else: current_chunk = line
        
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code_block:
                in_code_block = False
                code_block_lang = ""
            else:
                in_code_block = True
                code_block_lang = stripped.replace("```", "").strip()
    
    if current_chunk: chunks.append(current_chunk)
    return chunks

# Cog 내부에서 self.bot.db에 접근하기 위한 커스텀 체크
def is_authorized():
    async def predicate(ctx):
        if ctx.bot.db.is_authorized(ctx.author.id):
            return True
        await ctx.send("🚫 권한이 없습니다. 관리자에게 문의하세요.")
        return False
    return commands.check(predicate)