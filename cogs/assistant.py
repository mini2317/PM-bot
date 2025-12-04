import discord
from discord.ext import commands
import datetime
from utils import is_authorized
from ui import AssistantActionView

class AssistantCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.action_handlers = {
            'create_project': self.handle_create_project,
            'set_parent': self.handle_set_parent,
            'add_task': self.handle_add_task,
            'complete_task': self.handle_complete_task,
            'assign_task': self.handle_assign_task,
            'status': self.handle_status,
            'start_meeting': self.handle_start_meeting,
            'stop_meeting': self.handle_stop_meeting,
            'add_repo': self.handle_add_repo,
            'remove_repo': self.handle_remove_repo,
            'ask_user': self.handle_ask_user
        }

    async def _refresh_dashboard(self, guild_id):
        proj_cog = self.bot.get_cog('ProjectCog')
        if proj_cog: await proj_cog.refresh_dashboard(guild_id)

    # --- Action Handlers ---
    async def handle_ask_user(self, interaction, data):
        q = data.get('question', '정보가 더 필요합니다.')
        await interaction.channel.send(f"🤖 {q}") 
        try: await interaction.message.delete()
        except: pass

    async def handle_create_project(self, interaction, data):
        name = data.get('name')
        if not name:
            await interaction.message.edit(content="❌ 프로젝트 이름 누락", view=None); return
        if self.bot.db.create_project(interaction.guild.id, name):
            await interaction.message.edit(content=f"✅ 프로젝트 **{name}** 생성 완료!", view=None)
        else:
            await interaction.message.edit(content=f"⚠️ 이미 존재하는 프로젝트입니다.", view=None)

    async def handle_set_parent(self, interaction, data):
        child, parent = data.get('child'), data.get('parent')
        if not child or not parent:
             await interaction.message.edit(content="❌ 정보 부족", view=None); return
        if self.bot.db.set_parent_project(interaction.guild.id, child, parent):
            await interaction.message.edit(content=f"✅ **{child}** ⊂ **{parent}** 설정 완료.", view=None)
        else:
            await interaction.message.edit(content=f"❌ 프로젝트를 찾을 수 없습니다.", view=None)

    async def handle_add_task(self, interaction, data):
        content, project = data.get('content'), data.get('project', '일반')
        if not content:
            await interaction.message.edit(content="❌ 내용 없음", view=None); return
        tid = self.bot.db.add_task(interaction.guild.id, project, content)
        await interaction.message.edit(content=f"✅ 할 일 등록 완료 (ID: **{tid}**)", view=None)
        await self._refresh_dashboard(interaction.guild.id)

    async def handle_complete_task(self, interaction, data):
        tid = data.get('task_id')
        if tid and self.bot.db.update_task_status(tid, "DONE"):
            await interaction.message.edit(content=f"✅ 작업 **#{tid}** 완료 처리됨.", view=None)
            await self._refresh_dashboard(interaction.guild.id)
        else:
            await interaction.message.edit(content=f"❌ 작업을 찾을 수 없습니다.", view=None)

    async def handle_assign_task(self, interaction, data):
        tid = data.get('task_id')
        m_name = data.get('member_name') or data.get('member') or data.get('user_name')
        if not tid or not m_name:
            await interaction.message.edit(content="❌ 정보 부족", view=None); return
        
        target = discord.utils.find(lambda m: m_name in m.display_name or m_name in m.name, interaction.guild.members)
        if target and self.bot.db.assign_task(tid, target.id, target.display_name):
            await interaction.message.edit(content=f"✅ **#{tid}** 담당자 → {target.mention}", view=None)
            await self._refresh_dashboard(interaction.guild.id)
        else:
            await interaction.message.edit(content=f"❌ 실패 (멤버/ID 확인)", view=None)

    async def handle_status(self, interaction, data):
        project = data.get('project')
        ts = self.bot.db.get_tasks(interaction.guild.id, project)
        if not ts: await interaction.message.edit(content="📭 할 일이 없습니다.", view=None); return
        todo = [f"#{t[0]} {t[2]}" for t in ts if t[5]=='TODO']
        prog = [f"#{t[0]} {t[2]}" for t in ts if t[5]=='IN_PROGRESS']
        e = discord.Embed(title="📊 현황", color=0xf1c40f)
        e.add_field(name="대기", value="\n".join(todo) or "-", inline=False)
        e.add_field(name="진행", value="\n".join(prog) or "-", inline=False)
        await interaction.message.edit(content="", embed=e, view=None)

    async def handle_start_meeting(self, interaction, data):
        meeting_cog = self.bot.get_cog('MeetingCog')
        if not meeting_cog: return
        if interaction.channel.id in meeting_cog.meeting_buffer:
             await interaction.message.edit(content="🔴 이미 회의 중", view=None); return
        name = data.get('name') or f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
        try:
            thread = await interaction.channel.create_thread(name=f"🎙️ {name}", type=discord.ChannelType.public_thread, auto_archive_duration=60)
            meeting_cog.meeting_buffer[thread.id] = {'name': name, 'messages': [], 'jump_url': thread.jump_url}
            await interaction.message.edit(content=f"✅ 회의 스레드 생성: {thread.mention}", view=None)
            await thread.send("🔴 기록 시작")
        except: await interaction.message.edit(content="❌ 실패", view=None)

    async def handle_stop_meeting(self, interaction, data):
        await interaction.message.edit(content="⚠️ 회의 종료는 해당 스레드에서 `/회의 종료`를 입력하세요.", view=None)

    async def handle_add_repo(self, interaction, data):
        if self.bot.db.add_repo(data.get('repo_name'), interaction.channel.id, interaction.user.name):
            await interaction.message.edit(content=f"✅ 연결 완료", view=None)
        else: await interaction.message.edit(content="❌ 실패", view=None)

    async def handle_remove_repo(self, interaction, data):
        if self.bot.db.remove_repo(data.get('repo_name'), interaction.channel.id):
            await interaction.message.edit(content=f"🗑️ 해제 완료", view=None)
        else: await interaction.message.edit(content="❌ 실패", view=None)

    # --- 메인 리스너 ---
    @commands.hybrid_command(name="비서설정", description="이 채널을 AI 비서 채널로 설정합니다.")
    @is_authorized()
    async def set_assistant(self, ctx):
        self.bot.db.set_assistant_channel(ctx.guild.id, ctx.channel.id)
        await ctx.send(f"🤖 **AI 비서 활성화!**\n이제 저를 멘션(@{self.bot.user.name})하고 말씀하시면 도와드릴게요.")

    @commands.hybrid_command(name="비서해제", description="AI 비서 설정을 해제합니다.")
    @is_authorized()
    async def unset_assistant(self, ctx):
        self.bot.db.set_assistant_channel(ctx.guild.id, None)
        await ctx.send("🤖 **AI 비서가 비활성화되었습니다.**")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        # [FIX] 봇이 멘션되었는지 확인
        if self.bot.user not in message.mentions:
            return

        # 명령어 실행은 무시 (!, /)
        if message.content.startswith(('!', '/')): return

        # 비서 채널인지 확인 (비서 채널이 설정되어 있지 않거나, 다른 채널이면 무시)
        assist_channel_id = self.bot.db.get_assistant_channel(message.guild.id)
        if not assist_channel_id or message.channel.id != assist_channel_id: 
            return

        # 멘션 제거 및 내용 추출
        user_msg = message.content.replace(self.bot.user.mention, "").strip()
        if not user_msg: return # 멘션만 하고 내용 없으면 무시

        # 히스토리 가져오기 (최근 10개) - 문맥 파악용
        history = [msg async for msg in message.channel.history(limit=10)]
        chat_context = []
        for msg in reversed(history):
            role = "Assistant" if msg.author.bot else "User"
            # 봇 호출 명령어는 제외하고 자연어 흐름만
            clean_content = msg.content.replace(self.bot.user.mention, "@Bot").strip()
            chat_context.append(f"[{role}] {clean_content}")

        async with message.channel.typing():
            active_tasks = self.bot.db.get_active_tasks_simple(message.guild.id)
            projects = self.bot.db.get_all_projects()
            guild_id = message.guild.id

            result = await self.bot.ai.analyze_assistant_input(chat_context, active_tasks, projects, guild_id)
            
            action = result.get('action', 'none')
            comment = result.get('comment', '...')
            question = result.get('question')

            if action == 'none':
                if comment and comment != '...':
                    await message.reply(f"🤖 {comment}")
                return

            async def execute_callback(interaction, data):
                if action == 'ask_user':
                    await self.handle_ask_user(interaction, data)
                else:
                    handler = self.action_handlers.get(action)
                    if handler: await handler(interaction, data)
                    else: await interaction.response.send_message(f"❌ 알 수 없는 액션: {action}", ephemeral=True)

            if action == 'ask_user':
                await message.reply(f"🤖 {question}")
            else:
                details = ""
                if action == 'add_task': details = f"📌 **할일**: {result.get('content')}\n📁 **프로젝트**: {result.get('project', '일반')}"
                elif action == 'create_project': details = f"🆕 **프로젝트**: {result.get('name')}"
                elif action == 'complete_task': details = f"✅ **완료**: #{result.get('task_id')}"
                elif action == 'assign_task': details = f"👤 **배정**: #{result.get('task_id')} → {result.get('member_name')}"
                elif action == 'start_meeting': details = f"🎙️ **회의**: {result.get('name')}"
                elif action == 'add_repo': details = f"🐙 **Github**: {result.get('repo_name')}"
                elif action == 'status': details = "📊 **현황판 조회**"
                
                display_msg = f"🤖 **[비서 제안]**\n{comment}\n\n{details}" if details else f"🤖 **[비서 제안]**\n{comment}"
                
                view = AssistantActionView(result, message.author, execute_callback)
                await message.reply(f"{display_msg}\n\n실행할까요?", view=view)

async def setup(bot):
    await bot.add_cog(AssistantCog(bot))