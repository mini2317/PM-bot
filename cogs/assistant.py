import discord
from discord.ext import commands
import datetime
from utils import is_authorized
from ui import AssistantActionView

class AssistantCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 액션 문자열과 핸들러 메서드 매핑 (Dispatcher)
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
            'remove_repo': self.handle_remove_repo
        }

    # --- 유틸리티 메서드 ---
    async def _refresh_dashboard(self, guild_id):
        """현황판 갱신 헬퍼"""
        proj_cog = self.bot.get_cog('ProjectCog')
        if proj_cog:
            await proj_cog.refresh_dashboard(guild_id)

    # --- 액션 핸들러 (Action Handlers) ---
    
    async def handle_create_project(self, interaction, data):
        name = data.get('name')
        if not name:
            await interaction.message.edit(content="❌ 프로젝트 이름이 누락되었습니다.", view=None)
            return

        if self.bot.db.create_project(interaction.guild.id, name):
            await interaction.message.edit(content=f"✅ 프로젝트 **{name}** 생성 완료!", view=None)
        else:
            await interaction.message.edit(content=f"⚠️ 이미 존재하는 프로젝트입니다.", view=None)

    async def handle_set_parent(self, interaction, data):
        child = data.get('child')
        parent = data.get('parent')
        if not child or not parent:
             await interaction.message.edit(content="❌ 프로젝트 정보가 부족합니다.", view=None)
             return

        if self.bot.db.set_parent_project(interaction.guild.id, child, parent):
            await interaction.message.edit(content=f"✅ **{child}** ⊂ **{parent}** 설정 완료.", view=None)
        else:
            await interaction.message.edit(content=f"❌ 프로젝트를 찾을 수 없습니다.", view=None)

    async def handle_add_task(self, interaction, data):
        content = data.get('content')
        project = data.get('project', '일반')
        
        if not content:
            await interaction.message.edit(content="❌ 할 일 내용이 없습니다.", view=None)
            return

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
        m_name = data.get('member_name')
        
        if not tid or not m_name:
            await interaction.message.edit(content="❌ 작업 ID 또는 멤버 이름이 없습니다.", view=None)
            return

        target = discord.utils.find(lambda m: m_name in m.display_name or m_name in m.name, interaction.guild.members)
        
        if target:
            if self.bot.db.assign_task(tid, target.id, target.display_name):
                await interaction.message.edit(content=f"✅ **#{tid}** 담당자 → {target.mention}", view=None)
                await self._refresh_dashboard(interaction.guild.id)
            else:
                await interaction.message.edit(content="❌ DB 업데이트 실패", view=None)
        else:
            await interaction.message.edit(content=f"❌ 멤버 '{m_name}'를 찾을 수 없습니다.", view=None)

    async def handle_status(self, interaction, data):
        project = data.get('project')
        ts = self.bot.db.get_tasks(interaction.guild.id, project)
        
        if not ts:
            await interaction.message.edit(content="📭 할 일이 없습니다.", view=None)
            return

        todo = [f"#{t[0]} {t[2]}" for t in ts if t[5]=='TODO']
        prog = [f"#{t[0]} {t[2]}" for t in ts if t[5]=='IN_PROGRESS']
        
        e = discord.Embed(title="📊 요청하신 현황입니다", color=0xf1c40f)
        if project: e.title = f"📊 {project} 현황"
        
        e.add_field(name="대기", value="\n".join(todo) or "-", inline=False)
        e.add_field(name="진행", value="\n".join(prog) or "-", inline=False)
        
        await interaction.message.edit(content="", embed=e, view=None)

    async def handle_start_meeting(self, interaction, data):
        meeting_cog = self.bot.get_cog('MeetingCog')
        if not meeting_cog:
            await interaction.message.edit(content="❌ 회의 기능을 사용할 수 없습니다.", view=None)
            return

        if interaction.channel.id in meeting_cog.meeting_buffer:
             await interaction.message.edit(content="🔴 이미 이 채널에서 회의가 진행 중입니다.", view=None)
             return

        name = data.get('name') or f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
        
        try:
            # invoke 대신 직접 로직 수행
            thread = await interaction.channel.create_thread(name=f"🎙️ {name}", type=discord.ChannelType.public_thread, auto_archive_duration=60)
            meeting_cog.meeting_buffer[thread.id] = {'name': name, 'messages': [], 'jump_url': thread.jump_url}
            
            await interaction.message.edit(content=f"✅ 회의 스레드 생성: {thread.mention}", view=None)
            await thread.send("🔴 기록 시작")
        except Exception as e:
            await interaction.message.edit(content=f"❌ 스레드 생성 실패: {e}", view=None)

    async def handle_stop_meeting(self, interaction, data):
        # 회의 종료는 복잡한 Flow(View 연쇄)가 있으므로, 가이드만 제공하는 것이 안전함
        # 만약 강제로 종료하려면 MeetingCog의 stop_meeting 로직을 분리해서 호출해야 함
        meeting_cog = self.bot.get_cog('MeetingCog')
        
        # 현재 채널이 회의 중인지 확인
        is_meeting = False
        if meeting_cog:
             # 스레드 내부일 경우
             if interaction.channel.id in meeting_cog.meeting_buffer:
                 is_meeting = True
        
        if is_meeting:
             await interaction.message.edit(content="⚠️ 회의 종료는 해당 스레드 내부에서 `/회의 종료` 명령어를 직접 입력해주세요. (복잡한 보고서 생성 절차를 위해서입니다)", view=None)
        else:
             await interaction.message.edit(content="⚠️ 현재 채널은 기록 중인 회의실이 아닙니다.", view=None)

    async def handle_add_repo(self, interaction, data):
        repo_name = data.get('repo_name')
        if not repo_name:
             await interaction.message.edit(content="❌ 레포지토리 이름이 없습니다.", view=None)
             return

        if self.bot.db.add_repo(repo_name, interaction.channel.id, interaction.user.name):
            await interaction.message.edit(content=f"✅ Repo **{repo_name}** 연결 완료", view=None)
        else:
            await interaction.message.edit(content="❌ 등록 실패", view=None)

    async def handle_remove_repo(self, interaction, data):
        repo_name = data.get('repo_name')
        if not repo_name:
             await interaction.message.edit(content="❌ 레포지토리 이름이 없습니다.", view=None)
             return

        if self.bot.db.remove_repo(repo_name, interaction.channel.id):
            await interaction.message.edit(content=f"🗑️ Repo **{repo_name}** 해제 완료", view=None)
        else:
            await interaction.message.edit(content="❌ 미등록 Repo", view=None)


    # --- 메인 로직 ---

    @commands.hybrid_command(name="비서설정", description="이 채널을 AI 비서 채널로 설정합니다.")
    @is_authorized()
    async def set_assistant(self, ctx):
        self.bot.db.set_assistant_channel(ctx.guild.id, ctx.channel.id)
        await ctx.send(f"🤖 **AI 비서 활성화!**\n이제 이 채널({ctx.channel.mention})에서 말하는 내용은 제가 듣고 처리하겠습니다.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        # 1. 비서 채널 체크
        assist_channel_id = self.bot.db.get_assistant_channel(message.guild.id)
        if message.channel.id != assist_channel_id: return
        if message.content.startswith(('!', '/')): return

        # 2. AI 분석
        async with message.channel.typing():
            active_tasks = self.bot.db.get_active_tasks_simple(message.guild.id)
            projects = self.bot.db.get_all_projects()
            
            result = await self.bot.ai.analyze_assistant_input(message.content, active_tasks, projects)
            
            action = result.get('action', 'none')
            comment = result.get('comment', '이해하지 못했습니다.')

            if action == 'none':
                return # 잡담은 무시

            # 3. 실행 콜백 (Dispatcher 사용)
            async def execute_callback(interaction, data):
                handler = self.action_handlers.get(action)
                if handler:
                    await handler(interaction, data)
                else:
                    await interaction.response.send_message(f"❌ 알 수 없는 액션입니다: {action}", ephemeral=True)

            # 4. 확인 UI 전송
            view = AssistantActionView(result, message.author, execute_callback)
            await message.reply(f"🤖 **[비서 제안]**\n{comment}\n\n이대로 실행할까요?", view=view)

async def setup(bot):
    await bot.add_cog(AssistantCog(bot))