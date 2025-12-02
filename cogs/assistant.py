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

    # --- Action Handlers (로직은 그대로 유지) ---
    async def handle_ask_user(self, interaction, data):
        q = data.get('question', '정보가 더 필요합니다.')
        await interaction.channel.send(f"🤖 {q}")
        try: await interaction.message.delete() # 확인 메시지 삭제
        except: pass

    async def handle_create_project(self, interaction, data):
        if self.bot.db.create_project(interaction.guild.id, data.get('name')):
            await interaction.edit_original_response(content=f"✅ 프로젝트 **{data.get('name')}** 생성 완료!", view=None)
        else:
            await interaction.edit_original_response(content=f"⚠️ 이미 존재하는 프로젝트입니다.", view=None)

    async def handle_set_parent(self, interaction, data):
        if self.bot.db.set_parent_project(interaction.guild.id, data.get('child'), data.get('parent')):
            await interaction.edit_original_response(content=f"✅ 구조 설정 완료", view=None)
        else:
            await interaction.edit_original_response(content="❌ 실패 (프로젝트명 확인 필요)", view=None)

    async def handle_add_task(self, interaction, data):
        tid = self.bot.db.add_task(interaction.guild.id, data.get('project', '일반'), data.get('content'))
        await interaction.edit_original_response(content=f"✅ 할 일 등록 완료 (ID: **{tid}**)", view=None)
        await self._refresh_dashboard(interaction.guild.id)

    async def handle_complete_task(self, interaction, data):
        if self.bot.db.update_task_status(data.get('task_id'), "DONE"):
            await interaction.edit_original_response(content=f"✅ 작업 완료 처리됨.", view=None)
            await self._refresh_dashboard(interaction.guild.id)
        else:
            await interaction.edit_original_response(content=f"❌ 작업을 찾을 수 없습니다.", view=None)

    async def handle_assign_task(self, interaction, data):
        mn = data.get('member_name') or data.get('member') or data.get('user_name')
        target = discord.utils.find(lambda m: mn in m.display_name or mn in m.name, interaction.guild.members)
        if target and self.bot.db.assign_task(data.get('task_id'), target.id, target.display_name):
            await interaction.edit_original_response(content=f"✅ 담당자 배정 완료: {target.mention}", view=None)
            await self._refresh_dashboard(interaction.guild.id)
        else:
            await interaction.edit_original_response(content=f"❌ 실패 (멤버 '{mn}' 또는 ID 확인)", view=None)

    async def handle_status(self, interaction, data):
        ts = self.bot.db.get_tasks(interaction.guild.id, data.get('project'))
        if not ts:
            await interaction.edit_original_response(content="📭 할 일이 없습니다.", view=None)
            return
        
        todo = [f"#{t[0]} {t[2]}" for t in ts if t[5]=='TODO']
        prog = [f"#{t[0]} {t[2]}" for t in ts if t[5]=='IN_PROGRESS']
        e = discord.Embed(title="📊 현황", color=0xf1c40f)
        e.add_field(name="대기", value="\n".join(todo) or "-", inline=False)
        e.add_field(name="진행", value="\n".join(prog) or "-", inline=False)
        await interaction.edit_original_response(content="", embed=e, view=None)

    async def handle_start_meeting(self, interaction, data):
        meeting_cog = self.bot.get_cog('MeetingCog')
        if not meeting_cog: return
        if interaction.channel.id in meeting_cog.meeting_buffer:
             await interaction.edit_original_response(content="🔴 이미 이 채널에서 회의 중입니다.", view=None); return
        
        name = data.get('name') or f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
        try:
            thread = await interaction.channel.create_thread(name=f"🎙️ {name}", type=discord.ChannelType.public_thread, auto_archive_duration=60)
            meeting_cog.meeting_buffer[thread.id] = {'name': name, 'messages': [], 'jump_url': thread.jump_url}
            await interaction.edit_original_response(content=f"✅ 회의 스레드 생성: {thread.mention}", view=None)
            await thread.send("🔴 기록 시작")
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ 실패: {e}", view=None)

    async def handle_stop_meeting(self, interaction, data):
        await interaction.edit_original_response(content="⚠️ 회의 종료는 해당 스레드 안에서 `/회의 종료`를 입력해주세요.", view=None)

    async def handle_add_repo(self, interaction, data):
        if self.bot.db.add_repo(data.get('repo_name'), interaction.channel.id, interaction.user.name):
            await interaction.edit_original_response(content=f"✅ Repo 연결 완료", view=None)
        else:
            await interaction.edit_original_response(content="❌ 실패", view=None)

    async def handle_remove_repo(self, interaction, data):
        if self.bot.db.remove_repo(data.get('repo_name'), interaction.channel.id):
            await interaction.edit_original_response(content=f"🗑️ 해제 완료", view=None)
        else:
            await interaction.edit_original_response(content="❌ 실패", view=None)

    # --- Listener ---
    @commands.hybrid_command(name="비서설정", description="이 채널을 AI 비서 채널로 설정합니다.")
    @is_authorized()
    async def set_assistant(self, ctx):
        self.bot.db.set_assistant_channel(ctx.guild.id, ctx.channel.id)
        await ctx.send(f"🤖 **AI 비서 활성화!**\n이제 이 채널의 대화를 듣고 업무를 처리합니다.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        assist_channel_id = self.bot.db.get_assistant_channel(message.guild.id)
        if message.channel.id != assist_channel_id: return
        if message.content.startswith(('!', '/')): return

        history = [msg async for msg in message.channel.history(limit=6)]
        chat_context = []
        for msg in reversed(history):
            role = "Assistant" if msg.author.bot else "User"
            chat_context.append(f"[{role}] {msg.content}")

        async with message.channel.typing():
            active_tasks = self.bot.db.get_active_tasks_simple(message.guild.id)
            projects = self.bot.db.get_all_projects()
            
            result = await self.bot.ai.analyze_assistant_input(chat_context, active_tasks, projects, message.guild.id)
            
            action = result.get('action', 'none')
            comment = result.get('comment', '...')
            question = result.get('question')

            if action == 'none': return

            # 콜백 실행기 (interaction.message.edit 사용)
            async def execute_callback(interaction, data):
                if action == 'ask_user':
                    await self.handle_ask_user(interaction, data)
                else:
                    handler = self.action_handlers.get(action)
                    if handler: await handler(interaction, data)
                    else: await interaction.response.send_message(f"❌ 알 수 없는 액션", ephemeral=True)

            if action == 'ask_user':
                await message.reply(f"🤖 {question}")
            else:
                # 상세 정보 포맷팅
                details = ""
                if action == 'add_task': details = f"📌 **할일**: {result.get('content')}\n📁 **프로젝트**: {result.get('project')}"
                elif action == 'create_project': details = f"🆕 **프로젝트**: {result.get('name')}"
                elif action == 'complete_task': details = f"✅ **완료**: #{result.get('task_id')}"
                elif action == 'assign_task': details = f"👤 **배정**: #{result.get('task_id')} → {result.get('member_name')}"
                elif action == 'start_meeting': details = f"🎙️ **회의**: {result.get('name')}"
                elif action == 'add_repo': details = f"🐙 **Github**: {result.get('repo_name')}"

                msg_txt = f"🤖 **[비서 제안]**\n{comment}\n\n{details}" if details else f"🤖 **[비서 제안]**\n{comment}"
                
                view = AssistantActionView(result, message.author, execute_callback)
                await message.reply(f"{msg_txt}\n\n실행할까요?", view=view)

async def setup(bot):
    await bot.add_cog(AssistantCog(bot))