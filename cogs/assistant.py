import discord
from discord.ext import commands
import datetime
from utils import is_authorized
from ui import AssistantActionView

class AssistantCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name="비서설정", description="이 채널을 AI 비서 채널로 설정합니다.")
    @is_authorized()
    async def set_assistant(self, ctx):
        self.bot.db.set_assistant_channel(ctx.guild.id, ctx.channel.id)
        await ctx.send(f"🤖 **AI 비서가 이 채널을 주시합니다.**\n명령어 없이 자연어로 말하면 제가 알아서 처리할게요!")

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
            comment = result.get('comment', '처리할 수 없습니다.')

            if action == 'none':
                # 단순 잡담이면 그냥 답변 (또는 무시)
                # await message.reply(comment) 
                return

            # 3. 실행 콜백 정의
            async def execute_action(interaction, data):
                act = data.get('action')
                
                # --- 프로젝트 관련 ---
                if act == 'create_project':
                    if self.bot.db.create_project(interaction.guild.id, data['name']):
                        await interaction.message.edit(content=f"✅ 프로젝트 **{data['name']}** 생성 완료!", view=None)
                    else:
                        await interaction.message.edit(content=f"⚠️ 이미 존재하는 프로젝트입니다.", view=None)

                elif act == 'set_parent':
                    if self.bot.db.set_parent_project(interaction.guild.id, data['child'], data['parent']):
                        await interaction.message.edit(content=f"✅ **{data['child']}** ⊂ **{data['parent']}** 설정 완료.", view=None)
                    else:
                        await interaction.message.edit(content=f"❌ 프로젝트를 찾을 수 없습니다.", view=None)

                # --- 할 일 관련 ---
                elif act == 'add_task':
                    tid = self.bot.db.add_task(interaction.guild.id, data.get('project', '일반'), data['content'])
                    await interaction.message.edit(content=f"✅ 할 일 등록 완료 (ID: **{tid}**)", view=None)
                    await self._refresh_dashboard(interaction.guild)

                elif act == 'complete_task':
                    tid = data.get('task_id')
                    if tid and self.bot.db.update_task_status(tid, "DONE"):
                        await interaction.message.edit(content=f"✅ 작업 **#{tid}** 완료 처리됨.", view=None)
                        await self._refresh_dashboard(interaction.guild)
                    else:
                        await interaction.message.edit(content=f"❌ 작업을 찾을 수 없습니다.", view=None)

                elif act == 'assign_task':
                    tid = data.get('task_id')
                    m_name = data.get('member_name')
                    # 이름으로 멤버 찾기
                    target = discord.utils.find(lambda m: m_name in m.display_name or m_name in m.name, interaction.guild.members)
                    if target and tid:
                        if self.bot.db.assign_task(tid, target.id, target.display_name):
                            await interaction.message.edit(content=f"✅ **#{tid}** 담당자 → {target.mention}", view=None)
                            await self._refresh_dashboard(interaction.guild)
                        else:
                            await interaction.message.edit(content="❌ DB 업데이트 실패", view=None)
                    else:
                        await interaction.message.edit(content=f"❌ 멤버 '{m_name}' 또는 작업 ID를 찾을 수 없음", view=None)

                elif act == 'status':
                    # ProjectCog의 status 커맨드 로직 재사용이 어렵다면 직접 구현
                    # 여기서는 간단히 텍스트로 보여주거나, ProjectCog 함수 호출 시도
                    proj_cog = self.bot.get_cog('ProjectCog')
                    if proj_cog:
                        # Context 없이 함수 호출은 어려움. 직접 DB 조회 후 Embed 전송
                        ts = self.bot.db.get_tasks(interaction.guild.id, data.get('project'))
                        if not ts:
                            await interaction.message.edit(content="📭 할 일이 없습니다.", view=None)
                        else:
                            # 간소화된 현황판
                            todo = [f"#{t[0]} {t[2]}" for t in ts if t[5]=='TODO']
                            prog = [f"#{t[0]} {t[2]}" for t in ts if t[5]=='IN_PROGRESS']
                            e = discord.Embed(title="📊 요청하신 현황입니다", color=0xf1c40f)
                            e.add_field(name="대기", value="\n".join(todo) or "-", inline=False)
                            e.add_field(name="진행", value="\n".join(prog) or "-", inline=False)
                            await interaction.message.edit(content="", embed=e, view=None)

                # --- 회의 관련 ---
                elif act == 'start_meeting':
                    meeting_cog = self.bot.get_cog('MeetingCog')
                    if meeting_cog:
                        # MeetingCog의 start_meeting 호출 (Context 필요)
                        # 여기서는 간단히 스레드 생성 로직 직접 수행 (Context Mocking이 복잡하므로)
                        name = data.get('name') or f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
                        try:
                            thread = await interaction.channel.create_thread(name=f"🎙️ {name}", type=discord.ChannelType.public_thread)
                            meeting_cog.meeting_buffer[thread.id] = {'name': name, 'messages': [], 'jump_url': thread.jump_url}
                            await interaction.message.edit(content=f"✅ 회의 스레드 생성: {thread.mention}", view=None)
                            await thread.send("🔴 기록 시작")
                        except Exception as e:
                            await interaction.message.edit(content=f"❌ 실패: {e}", view=None)

                elif act == 'stop_meeting':
                    # stop_meeting은 현재 채널(스레드)에서 해야 하므로 비서 채널에서 직접 호출은 애매함
                    # 하지만 비서가 스레드 안에 있다면 가능
                    meeting_cog = self.bot.get_cog('MeetingCog')
                    if meeting_cog and interaction.channel.id in meeting_cog.meeting_buffer:
                        # Context를 억지로 만들거나 로직 분리 필요. 여기서는 안내만
                        await interaction.message.edit(content="⚠️ 회의 종료는 해당 스레드에서 `/회의 종료`를 입력해주세요.", view=None)
                    else:
                        await interaction.message.edit(content="⚠️ 현재 채널은 기록 중인 회의실이 아닙니다.", view=None)

                # --- 깃허브 관련 ---
                elif act == 'add_repo':
                    if self.bot.db.add_repo(data['repo_name'], interaction.channel.id, interaction.user.name):
                        await interaction.message.edit(content=f"✅ Repo **{data['repo_name']}** 연결 완료", view=None)
                    else:
                        await interaction.message.edit(content="❌ 등록 실패", view=None)

                elif act == 'remove_repo':
                    if self.bot.db.remove_repo(data['repo_name'], interaction.channel.id):
                        await interaction.message.edit(content=f"🗑️ Repo **{data['repo_name']}** 해제 완료", view=None)
                    else:
                        await interaction.message.edit(content="❌ 미등록 Repo", view=None)

            # 4. 확인 UI 전송
            view = AssistantActionView(result, message.author, execute_action)
            await message.reply(f"🤖 **[비서 제안]**\n{comment}\n\n이대로 실행할까요?", view=view)

    async def _refresh_dashboard(self, guild):
        proj_cog = self.bot.get_cog('ProjectCog')
        if proj_cog: await proj_cog.refresh_dashboard(guild.id)

async def setup(bot):
    await bot.add_cog(AssistantCog(bot))