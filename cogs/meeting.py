import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Select
import datetime, asyncio
import json
import io
from ui import EmbedPaginator, StatusUpdateView, NewProjectView, RoleCreationView, RoleAssignmentView
from utils import is_authorized, smart_chunk_text
from services.pdf import generate_meeting_pdf

# [NEW] 회의 전용 할 일 등록 View (포럼 스레드 생성 기능 포함)
class MeetingTaskView(View):
    def __init__(self, tasks, mid, author, guild, db, cleanup_callback=None):
        super().__init__(timeout=300)
        self.tasks = tasks
        self.mid = mid
        self.author = author
        self.guild = guild
        self.db = db
        self.cleanup_callback = cleanup_callback
        self.selected_indices = []
        
        options = []
        for i, t in enumerate(tasks):
            content = (t.get('content') or '내용 없음')[:40]
            project = (t.get('project') or '미정')[:15]
            assignee = (t.get('assignee_hint') or '미정')[:10]
            label = f"[{project}] {content}"
            options.append(discord.SelectOption(label=label, description=f"담당: {assignee}", value=str(i)))
        
        if len(options) > 25: options = options[:25]
        
        self.select = Select(placeholder="등록할 업무 선택", min_values=0, max_values=len(options), options=options)
        self.select.callback = self.cb
        self.add_item(self.select)

    async def cb(self, interaction):
        self.selected_indices = [int(v) for v in self.select.values]
        await interaction.response.defer()

    @discord.ui.button(label="등록 및 배정 완료", style=discord.ButtonStyle.green, emoji="✅")
    async def save(self, interaction, button):
        if not self.selected_indices:
            await interaction.followup.send("⚠️ 항목을 선택해주세요.", ephemeral=True)
            return
            
        results = []
        for idx in self.selected_indices:
            t = self.tasks[idx]
            p_name = t.get('project', '일반')
            content = t.get('content', '내용 없음')
            
            # 1. 포럼 스레드 생성 로직
            pid = self.db.get_project_id(self.guild.id, p_name)
            project_data = self.db.get_project(pid) if pid else None
            
            thread_id = None
            message_id = None
            forum_link = ""

            # 프로젝트에 연결된 포럼 채널이 있으면 게시글 생성
            if project_data and project_data.get('forum_channel_id'):
                forum = self.guild.get_channel(project_data['forum_channel_id'])
                if forum and isinstance(forum, discord.ForumChannel):
                    todo_tag = next((tag for tag in forum.available_tags if tag.name == "TODO"), None)
                    tags = [todo_tag] if todo_tag else []
                    try:
                        th = await forum.create_thread(
                            name=content[:100],
                            content=f"📝 **회의 도출 작업**\n{content}\n\n🔗 **출처**: 회의록 #{self.mid}\n👤 **생성자**: {self.author.mention}",
                            applied_tags=tags
                        )
                        thread_id = th.thread.id
                        message_id = th.message.id
                        forum_link = " 🔗"
                    except Exception as e:
                        print(f"포럼 생성 실패: {e}")

            # 2. DB 저장
            tid = self.db.add_task(self.guild.id, p_name, content, self.mid, thread_id=thread_id, message_id=message_id)
            res_str = f"✅ **#{tid}** 등록{forum_link}"
            
            # 3. 담당자 배정
            hint = t.get('assignee_hint')
            if hint:
                target = discord.utils.find(lambda m: hint in m.display_name or hint in m.name, self.guild.members)
                if target:
                    if self.db.assign_task(tid, target.id, target.display_name):
                        res_str += f" → 👤 {target.display_name}"
                        # 스레드에도 멘션
                        if thread_id:
                            try:
                                th_ch = self.guild.get_thread(thread_id)
                                if th_ch: await th_ch.send(f"👤 **담당자 지정**: {target.mention}")
                            except: pass

            results.append(res_str)
            
        await interaction.message.edit(content="**[처리 결과]**\n" + "\n".join(results), view=None)
        self.stop()
        
        # 현황판 갱신
        proj_cog = interaction.client.get_cog('ProjectCog')
        if proj_cog: await proj_cog.refresh_dashboard(self.guild.id)

        if self.cleanup_callback: await self.cleanup_callback()


class MeetingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # meeting_buffer: {channel_id: {name, messages, jump_url}}
        # 포럼 스레드인 경우 channel_id가 스레드 ID가 됨
        self.meeting_buffer = {} 

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if message.channel.id in self.meeting_buffer and not message.content.startswith(('!', '/')):
            msg_obj = {'time': message.created_at.strftime("%H:%M"), 'user': message.author.display_name, 'content': message.content}
            self.meeting_buffer[message.channel.id]['messages'].append(msg_obj)

    @commands.hybrid_group(name="회의", description="회의 관리")
    async def meeting_group(self, ctx):
        if ctx.invoked_subcommand is None: await ctx.send_help(ctx.command)

    @meeting_group.command(name="시작", description="회의를 시작합니다. (포럼이 있으면 게시글 생성)")
    @app_commands.describe(name="회의 주제")
    @is_authorized()
    async def start_meeting(self, ctx, *, name: str = None):
        if ctx.channel.id in self.meeting_buffer: 
            await ctx.send("🔴 이미 진행 중입니다.")
            return
        
        if not name: name = f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
        
        target_thread = None
        is_forum_post = False

        # [NEW] 현재 카테고리 내 '회의-보드' 포럼 찾기
        if ctx.channel.category:
            meeting_forum = discord.utils.get(ctx.channel.category.channels, name="🎙️ 회의-보드")
            if meeting_forum and isinstance(meeting_forum, discord.ForumChannel):
                try:
                    # 진행중 태그 찾기
                    wip_tag = next((t for t in meeting_forum.available_tags if t.name == "진행중"), None)
                    tags = [wip_tag] if wip_tag else []
                    
                    # 포럼 게시글 생성
                    thread_with_msg = await meeting_forum.create_thread(
                        name=f"🎙️ {name}",
                        content=f"회의가 시작되었습니다.\n주최자: {ctx.author.mention}",
                        applied_tags=tags
                    )
                    target_thread = thread_with_msg.thread
                    is_forum_post = True
                except Exception as e:
                    print(f"포럼 회의 생성 실패: {e}")

        # 포럼이 없거나 실패하면 현재 채널에서 스레드 생성 (기존 방식)
        if not target_thread:
            try:
                target_thread = await ctx.channel.create_thread(name=f"🎙️ {name}", type=discord.ChannelType.public_thread, auto_archive_duration=60)
            except Exception as e:
                await ctx.send(f"❌ 회의 생성 실패: {e}")
                return

        # 버퍼 등록
        self.meeting_buffer[target_thread.id] = {'name': name, 'messages': [], 'jump_url': target_thread.jump_url}
        
        embed = discord.Embed(title="🎙️ 회의 시작", description=f"{target_thread.mention} 에서 진행합니다.", color=0xe74c3c)
        if is_forum_post:
            await ctx.send(embed=embed) # 명령어 친 곳에 알림
            await target_thread.send("🔴 **기록 시작** (종료 시 `/회의 종료`)")
        else:
            await ctx.send(embed=embed)
            await target_thread.send("🔴 **기록 시작**")

    @meeting_group.command(name="종료", description="회의 종료 및 분석")
    @is_authorized()
    async def stop_meeting(self, ctx):
        if ctx.channel.id not in self.meeting_buffer:
            await ctx.send("⚠️ 기록 중인 회의 공간이 아닙니다.")
            return

        data = self.meeting_buffer.pop(ctx.channel.id)
        raw = data['messages']
        if not raw: await ctx.send("📝 내용 없음"); return

        txt = "".join([f"[Speaker: {m['user']}] {m['content']}\n" for m in raw])
        waiting = await ctx.send("🤖 AI 분석 중...")

        # 1. 요약
        full_result = await self.bot.ai.generate_meeting_summary(txt)
        if not isinstance(full_result, dict):
            full_result = {"title": data['name'], "summary": str(full_result), "agenda": [], "decisions": []}

        title = full_result.get('title', data['name'])
        summary_text = full_result.get('summary', '요약 없음')
        
        summary_dump = json.dumps(full_result, ensure_ascii=False)
        m_id = self.bot.db.save_meeting(ctx.guild.id, title, ctx.channel.id, summary_dump, data['jump_url'])

        # 2. PDF 생성
        try:
            pdf_buffer = await asyncio.to_thread(generate_meeting_pdf, full_result)
            pdf_file = discord.File(io.BytesIO(pdf_buffer.getvalue()), filename=f"Meeting_{m_id}.pdf")
        except: pdf_file = None

        # 3. 분석
        projs = [r[1] for r in self.bot.db.get_project_tree(ctx.guild.id)]
        active = self.bot.db.get_active_tasks_simple(ctx.guild.id)
        roles = ", ".join([r.name for r in ctx.guild.roles if not r.is_default()])
        mems = ", ".join([m.display_name for m in ctx.guild.members if not m.bot])

        res = await self.bot.ai.extract_tasks_and_updates(txt, ", ".join(projs), active, roles, mems)
        
        await waiting.delete()
        
        e = discord.Embed(title=f"✅ 종료: {title}", color=0x2ecc71)
        e.add_field(name="요약", value=summary_text[:500]+"...", inline=False)
        decisions = full_result.get('decisions', [])
        if decisions:
            e.add_field(name="결정 사항", value="\n".join([f"• {d}" for d in decisions[:3]]), inline=False)
        
        await ctx.send(embed=e, file=pdf_file)

        # 스레드/포스트 정리 함수
        async def close_thread():
            try:
                if isinstance(ctx.channel, discord.Thread):
                    # 포럼 게시글인 경우 태그 변경 (진행중 -> 종료)
                    if isinstance(ctx.channel.parent, discord.ForumChannel):
                        done_tag = next((t for t in ctx.channel.parent.available_tags if t.name == "종료"), None)
                        if done_tag: await ctx.channel.edit(applied_tags=[done_tag], archived=True, locked=False)
                        else: await ctx.channel.edit(archived=True, locked=False)
                    else:
                        # 일반 스레드
                        await ctx.channel.edit(archived=True, locked=False)
            except: pass

        # 5-Step Flow
        async def step5_final():
            new_tasks = res.get('new_tasks', [])
            if not new_tasks:
                await ctx.send("💡 추가된 할 일이 없습니다.")
                await close_thread()
                return
            # [변경] MeetingTaskView 사용 (포럼 게시글 생성 로직 포함)
            view = MeetingTaskView(new_tasks, m_id, ctx.author, ctx.guild, self.bot.db, cleanup_callback=close_thread)
            await ctx.send("📝 **5. 할 일 등록 및 담당자 배정**", view=view)

        async def step4():
            assigns = res.get('assign_roles', [])
            if not assigns: await step5_final(); return
            await ctx.send(f"👤 **4. 역할 부여 제안 ({len(assigns)}건)**", view=RoleAssignmentView(assigns, ctx.author, step5_final, ctx.guild))

        async def step3():
            creates = res.get('create_roles', [])
            if not creates: await step4(); return
            await ctx.send(f"🛡️ **3. 새 역할 생성 제안: {', '.join(creates)}**", view=RoleCreationView(creates, ctx.author, step4, ctx.guild))

        async def step2():
            new_tasks = res.get('new_tasks', [])
            new_p = {}
            for t in new_tasks:
                if t.get('is_new_project'): new_p[t['project']] = t.get('suggested_parent')
            
            if new_p:
                desc = "\n".join([f"• **{k}** (상위: {v or '없음'})" for k, v in new_p.items()])
                await ctx.send(f"🆕 **2. 프로젝트 생성 제안**\n{desc}", view=NewProjectView(new_p, new_tasks, ctx.author, step3, ctx.guild.id, self.bot.db))
            else: await step3()

        if res.get('updates'):
            await ctx.send("🔄 **1. 상태 변경 감지**", view=StatusUpdateView(res['updates'], ctx.author, step2, self.bot.db))
        else: await step2()

    @meeting_group.command(name="목록")
    @is_authorized()
    async def list(self, ctx):
        rows = self.bot.db.get_recent_meetings(ctx.guild.id)
        if not rows: await ctx.send("📭 없음"); return
        e = discord.Embed(title="📂 회의록", color=0xf1c40f)
        for r in rows: e.add_field(name=f"[{r[0]}] {r[1]}", value=f"📅 {r[2]} | [이동]({r[4]})", inline=False)
        await ctx.send(embed=e)

    @meeting_group.command(name="조회")
    @app_commands.describe(id="ID")
    @is_authorized()
    async def view(self, ctx, id: int):
        row = self.bot.db.get_meeting_detail(id, ctx.guild.id)
        if not row: await ctx.send("❌ 없음"); return
        
        try:
            meeting_data = json.loads(row[2])
            summary = meeting_data.get('summary', '')
            pdf_buffer = await asyncio.to_thread(generate_meeting_pdf, meeting_data)
            pdf_file = discord.File(io.BytesIO(pdf_buffer.getvalue()), filename=f"Meeting_{id}.pdf")
            
            e = discord.Embed(title=f"📂 {row[0]}", description=summary[:500], color=0xf1c40f)
            if row[3]: e.add_field(name="링크", value=f"[이동]({row[3]})", inline=False)
            await ctx.send(embed=e, file=pdf_file)
        except:
            await ctx.send("❌ 데이터 손상")

    @meeting_group.command(name="삭제")
    @is_authorized()
    async def delete(self, ctx, id: int):
        if self.bot.db.delete_meeting(id, ctx.guild.id): await ctx.send("🗑️ 삭제됨")
        else: await ctx.send("❌ 실패")

async def setup(bot): await bot.add_cog(MeetingCog(bot))