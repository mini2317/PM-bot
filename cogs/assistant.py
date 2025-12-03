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

    # ... (핸들러 함수들은 기존과 100% 동일하므로 그대로 두시면 됩니다) ...
    # ... (handle_create_project, handle_add_task 등등...) ...
    # 편의상 여기에는 핵심 로직인 on_message와 핸들러 연결부만 작성합니다.
    
    async def handle_ask_user(self, i, d): await i.channel.send(f"🤖 {d.get('question')}"); await i.message.delete()
    async def handle_create_project(self, i, d): 
        if self.bot.db.create_project(i.guild.id, d['name']): await i.message.edit(content=f"✅ 프로젝트 **{d['name']}** 생성", view=None)
        else: await i.message.edit(content="⚠️ 중복", view=None)
    async def handle_set_parent(self, i, d): 
        if self.bot.db.set_parent_project(i.guild.id, d['child'], d['parent']): await i.message.edit(content="✅ 설정 완료", view=None)
        else: await i.message.edit(content="❌ 실패", view=None)
    async def handle_add_task(self, i, d):
        tid=self.bot.db.add_task(i.guild.id, d.get('project','일반'), d.get('content'))
        await i.message.edit(content=f"✅ 할일 등록 (#{tid})", view=None); await self._refresh_dashboard(i.guild.id)
    async def handle_complete_task(self, i, d):
        if self.bot.db.update_task_status(d['task_id'], "DONE"): await i.message.edit(content="✅ 완료 처리", view=None); await self._refresh_dashboard(i.guild.id)
        else: await i.message.edit(content="❌ 실패", view=None)
    async def handle_assign_task(self, i, d):
        mn=d.get('member_name') or d.get('member')
        t=discord.utils.find(lambda m: mn in m.display_name, i.guild.members)
        if t and self.bot.db.assign_task(d['task_id'], t.id, t.display_name): await i.message.edit(content=f"✅ 담당: {t.mention}", view=None); await self._refresh_dashboard(i.guild.id)
        else: await i.message.edit(content="❌ 실패", view=None)
    async def handle_status(self, i, d):
        ts=self.bot.db.get_tasks(i.guild.id, d.get('project'))
        if not ts: await i.message.edit(content="📭 없음", view=None); return
        todo=[f"#{t[0]} {t[2]}" for t in ts if t[5]=='TODO']; prog=[f"#{t[0]} {t[2]}" for t in ts if t[5]=='IN_PROGRESS']
        e=discord.Embed(title="📊 현황", color=0xf1c40f); e.add_field(name="대기", value="\n".join(todo) or "-", inline=False); e.add_field(name="진행", value="\n".join(prog) or "-", inline=False)
        await i.message.edit(content="", embed=e, view=None)
    async def handle_start_meeting(self, i, d):
        mc=self.bot.get_cog('MeetingCog')
        if i.channel.id in mc.meeting_buffer: await i.message.edit(content="🔴 이미 진행중", view=None); return
        nm=d.get('name') or f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
        th=await i.channel.create_thread(name=f"🎙️ {nm}", type=discord.ChannelType.public_thread)
        mc.meeting_buffer[th.id]={'name':nm,'messages':[],'jump_url':th.jump_url}
        await i.message.edit(content=f"✅ 스레드 생성: {th.mention}", view=None)
    async def handle_stop_meeting(self, i, d): await i.message.edit(content="⚠️ 스레드 내에서 `/회의 종료` 하세요", view=None)
    async def handle_add_repo(self, i, d): 
        if self.bot.db.add_repo(d['repo_name'], i.channel.id, i.user.name): await i.message.edit(content="✅ 연결됨", view=None)
    async def handle_remove_repo(self, i, d): 
        if self.bot.db.remove_repo(d['repo_name'], i.channel.id): await i.message.edit(content="🗑️ 해제됨", view=None)

    # --- [핵심 변경] Listener ---
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        # [변경] 봇이 멘션되었을 때만 반응 (Trigger)
        if self.bot.user not in message.mentions:
            return

        # 멘션된 부분 제거하고 순수 텍스트만 추출
        user_msg = message.content.replace(self.bot.user.mention, "").strip()
        if not user_msg: return # 멘션만 하고 아무 말 없으면 무시

        # [변경] 최근 대화 문맥(Context) 가져오기 (최근 10개)
        # 이걸 가져오기 때문에 봇이 내내 듣고 있지 않아도 흐름을 압니다.
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
            
            # AI 분석 (Gatekeeper 없이 바로 Gemini/Groq 호출)
            result = await self.bot.ai.analyze_assistant_input(chat_context, active_tasks, projects, message.guild.id)
            
            action = result.get('action', 'none')
            comment = result.get('comment', '...')
            question = result.get('question')

            # 단순 질문/잡담이면 바로 답변
            if action == 'none':
                if comment: await message.reply(f"🤖 {comment}")
                return

            async def execute_callback(interaction, data):
                if action == 'ask_user':
                    await self.handle_ask_user(interaction, data)
                else:
                    handler = self.action_handlers.get(action)
                    if handler: await handler(interaction, data)
                    else: await interaction.response.send_message("❌ 알 수 없는 액션", ephemeral=True)

            if action == 'ask_user':
                await message.reply(f"🤖 {question}")
            else:
                # 상세 정보 포맷팅 (기존과 동일)
                details = ""
                if action == 'add_task': details = f"📌 **할일**: {result.get('content')}\n📁 **프로젝트**: {result.get('project')}"
                elif action == 'create_project': details = f"🆕 **프로젝트**: {result.get('name')}"
                elif action == 'complete_task': details = f"✅ **완료**: #{result.get('task_id')}"
                elif action == 'assign_task': details = f"👤 **배정**: #{result.get('task_id')} → {result.get('member_name')}"
                elif action == 'start_meeting': details = f"🎙️ **회의**: {result.get('name')}"
                elif action == 'add_repo': details = f"🐙 **Github**: {result.get('repo_name')}"
                elif action == 'status': details = "📊 **현황판 조회**"

                msg_txt = f"🤖 **[비서 제안]**\n{comment}\n\n{details}" if details else f"🤖 **[비서 제안]**\n{comment}"
                
                view = AssistantActionView(result, message.author, execute_callback)
                await message.reply(f"{msg_txt}\n\n실행할까요?", view=view)

async def setup(bot):
    await bot.add_cog(AssistantCog(bot))