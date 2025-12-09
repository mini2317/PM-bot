import discord
from discord.ext import commands
from discord import app_commands
from discord.ui import View, Select
import datetime, asyncio
import json
import io
from ui import EmbedPaginator, TaskSelectionView, StatusUpdateView, NewProjectView, RoleCreationView, RoleAssignmentView, AutoAssignTaskView
from utils import is_authorized, smart_chunk_text
from services.pdf import generate_meeting_pdf

# [할 일 등록 View (기존 유지)]
class MeetingTaskView(View):
    def __init__(self, tasks, mid, author, guild, db, cleanup_callback=None):
        super().__init__(timeout=300)
        self.tasks = tasks; self.mid = mid; self.author = author; self.guild = guild; self.db = db; self.cleanup_callback = cleanup_callback; self.selected_indices = []
        options = []
        for i, t in enumerate(tasks):
            c = (t.get('content') or '내용 없음')[:40]
            p = (t.get('project') or '미정')[:15]
            a = (t.get('assignee_hint') or '미정')[:10]
            options.append(discord.SelectOption(label=f"[{p}] {c}", description=f"담당: {a}", value=str(i)))
        if len(options)>25: options=options[:25]
        self.select = Select(placeholder="등록할 업무 선택", options=options, min_values=0, max_values=len(options)); self.select.callback=self.cb; self.add_item(self.select)
    async def cb(self, i): self.selected_indices=[int(v) for v in self.select.values]; await i.response.defer()
    @discord.ui.button(label="등록 완료", style=discord.ButtonStyle.green, emoji="✅")
    async def save(self, i, b):
        if not self.selected_indices: await i.followup.send("⚠️ 선택항목 없음", ephemeral=True); return
        res = []
        for idx in self.selected_indices:
            t=self.tasks[idx]; pn=t.get('project','일반'); ct=t.get('content','')
            # 포럼 스레드 생성 (이슈보드)
            pid = self.db.get_project_id(self.guild.id, pn)
            pdata = self.db.get_project(pid) if pid else None
            tid, mid, flink = None, None, ""
            if pdata and pdata.get('forum_channel_id'):
                forum = self.guild.get_channel(pdata['forum_channel_id'])
                if forum and isinstance(forum, discord.ForumChannel):
                    try:
                        tag = next((x for x in forum.available_tags if x.name=="TODO"), None)
                        th = await forum.create_thread(name=ct[:100], content=f"📝 **작업**\n{ct}\n\n🔗 회의록 #{self.mid}\n👤 {self.author.mention}", applied_tags=[tag] if tag else [])
                        tid=th.thread.id; mid=th.message.id; flink=" 🔗"
                    except: pass
            db_tid = self.db.add_task(self.guild.id, pn, ct, self.mid, tid, mid)
            
            # 담당자 배정
            hint = t.get('assignee_hint')
            assign_str = ""
            if hint:
                target = discord.utils.find(lambda m: hint in m.display_name, self.guild.members)
                if target: 
                    self.db.assign_task(db_tid, target.id, target.display_name)
                    assign_str = f" → 👤 {target.display_name}"
                    if tid: # 스레드에도 알림
                         try: (await self.guild.fetch_channel(tid)).send(f"👤 담당: {target.mention}")
                         except: pass

            res.append(f"✅ **#{db_tid}** 등록{flink}{assign_str}")
        await i.message.edit(content="**[결과]**\n"+"\n".join(res), view=None); self.stop()
        if self.cleanup_callback: await self.cleanup_callback()
    @discord.ui.button(label="건너뛰기", style=discord.ButtonStyle.grey, emoji="⏭️")
    async def skip(self, i, b):
        await i.message.edit(content="➡️ 건너뜀", view=None);
        self.stop(); 
        if self.cleanup_callback: await self.cleanup_callback()


class MeetingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # meeting_buffer: {channel_id: {name, messages, jump_url, starter_msg_id}}
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

    @meeting_group.command(name="시작", description="회의 포럼 게시글을 생성하고 기록을 시작합니다.")
    @app_commands.describe(name="회의 주제")
    @is_authorized()
    async def start_meeting(self, ctx, *, name: str = None):
        if ctx.channel.id in self.meeting_buffer: 
            await ctx.send("🔴 이미 진행 중입니다.")
            return
        
        if not name: name = f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
        
        target_thread = None
        start_msg = None
        is_forum = False

        # 1. '회의-보드' 포럼 찾기
        if ctx.channel.category:
            meeting_forum = discord.utils.get(ctx.channel.category.channels, name="🎙️ 회의-보드")
            
            if meeting_forum and isinstance(meeting_forum, discord.ForumChannel):
                try:
                    wip_tag = next((t for t in meeting_forum.available_tags if t.name == "진행중"), None)
                    tags = [wip_tag] if wip_tag else []
                    
                    # [게시글 생성] 이것이 곧 회의실
                    thread_with_msg = await meeting_forum.create_thread(
                        name=f"🎙️ {name} (진행중...)",
                        content=f"**회의가 시작되었습니다.**\n\n- 주제: {name}\n- 주최자: {ctx.author.mention}\n- 일시: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n🔴 **녹음 중...** (종료하려면 `/회의 종료`를 입력하세요)",
                        applied_tags=tags
                    )
                    target_thread = thread_with_msg.thread
                    start_msg = thread_with_msg.message
                    is_forum = True
                except Exception as e:
                    print(f"포럼 회의 생성 실패: {e}")

        # 2. 포럼 실패 시 일반 스레드
        if not target_thread:
            try:
                target_thread = await ctx.channel.create_thread(name=f"🎙️ {name}", type=discord.ChannelType.public_thread, auto_archive_duration=60)
                start_msg = await target_thread.send("🔴 **기록 시작**")
            except Exception as e:
                await ctx.send(f"❌ 회의 생성 실패: {e}")
                return

        # 3. 버퍼 등록 (start_msg_id 필수)
        self.meeting_buffer[target_thread.id] = {
            'name': name, 
            'messages': [], 
            'jump_url': target_thread.jump_url,
            'start_msg_id': start_msg.id if start_msg else None
        }
        
        if is_forum:
            await ctx.send(f"✅ 회의실 생성됨: {target_thread.mention}")
        else:
            await ctx.send(embed=discord.Embed(title="🎙️ 회의 시작", description=f"{target_thread.mention}", color=0xe74c3c))

    @meeting_group.command(name="종료", description="회의를 종료하고 포럼 글을 업데이트합니다.")
    @is_authorized()
    async def stop_meeting(self, ctx):
        if ctx.channel.id not in self.meeting_buffer:
            await ctx.send("⚠️ 기록 중인 회의 공간이 아닙니다.")
            return

        data = self.meeting_buffer.pop(ctx.channel.id)
        raw = data['messages']
        start_msg_id = data.get('start_msg_id')

        if not raw: 
            await ctx.send("📝 대화 내용이 없어 종료합니다.")
            if isinstance(ctx.channel, discord.Thread): await ctx.channel.edit(archived=True)
            return

        txt = "".join([f"[Speaker: {m['user']}] {m['content']}\n" for m in raw])
        waiting = await ctx.send("🤖 AI 분석 및 정리 중...")

        # 1. AI 요약
        full_result = await self.bot.ai.generate_meeting_summary(txt)
        if not isinstance(full_result, dict):
            full_result = {"title": data['name'], "summary": str(full_result), "agenda": [], "decisions": []}

        title = full_result.get('title', data['name'])
        summary_text = full_result.get('summary', '요약 없음')
        
        # 2. DB 저장
        summary_dump = json.dumps(full_result, ensure_ascii=False)
        m_id = self.bot.db.save_meeting(ctx.guild.id, title, ctx.channel.id, summary_dump, data['jump_url'])

        # 3. PDF 생성
        try:
            pdf_buffer = await asyncio.to_thread(generate_meeting_pdf, full_result)
            pdf_file = discord.File(io.BytesIO(pdf_buffer.getvalue()), filename=f"Meeting_{m_id}.pdf")
        except: pdf_file = None

        # 4. 할 일 분석
        projs = [r[1] for r in self.bot.db.get_project_tree(ctx.guild.id)]
        active = self.bot.db.get_active_tasks_simple(ctx.guild.id)
        roles = ", ".join([r.name for r in ctx.guild.roles if not r.is_default()])
        mems = ", ".join([m.display_name for m in ctx.guild.members if not m.bot])

        # 5단계 프로세스 대신 -> 단순 할 일 추출만 수행
        res = await self.bot.ai.extract_tasks_and_updates(txt, ", ".join(projs), active, roles, mems)
        
        await waiting.delete()

        # 5. [핵심] 포럼 게시글 본문(Starter Message) 수정
        embed = discord.Embed(title=f"✅ {title}", description=summary_text[:3500], color=0x2ecc71)
        
        if full_result.get('decisions'):
            d_txt = "\n".join([f"• {d}" for d in full_result['decisions']])
            embed.add_field(name="☑ 결정 사항", value=d_txt[:1000], inline=False)
            
        embed.set_footer(text=f"Meeting ID: #{m_id} | 상세 내용은 첨부된 PDF 확인")

        # 본문 수정 시도
        msg_edited = False
        if start_msg_id:
            try:
                start_msg = await ctx.channel.fetch_message(start_msg_id)
                # 첨부파일과 Embed를 교체
                await start_msg.edit(content="", embed=embed, attachments=[pdf_file] if pdf_file else [])
                msg_edited = True
            except Exception as e:
                print(f"본문 수정 실패: {e}")
        
        # 본문 수정 실패 시 새 메시지로 전송
        if not msg_edited:
            await ctx.send(embed=embed, file=pdf_file)

        # 6. 스레드(게시글) 닫기 및 태그 변경
        async def close_thread_logic():
            try:
                # 제목 변경
                new_thread_name = f"✅ {title}"
                
                # 포럼인 경우 태그 변경
                if isinstance(ctx.channel.parent, discord.ForumChannel):
                    done_tag = next((t for t in ctx.channel.parent.available_tags if t.name == "종료"), None)
                    tags = [done_tag] if done_tag else []
                    await ctx.channel.edit(name=new_thread_name, applied_tags=tags, archived=True, locked=False)
                else:
                    # 일반 스레드
                    await ctx.channel.edit(name=new_thread_name, archived=True, locked=False)
            except Exception as e:
                print(f"스레드 닫기 실패: {e}")

        # 7. 할 일 등록 절차 (없으면 바로 닫기)
        new_tasks = res.get('new_tasks', [])
        if new_tasks:
            view = MeetingTaskView(new_tasks, m_id, ctx.author, ctx.guild, self.bot.db, cleanup_callback=close_thread_logic)
            await ctx.send("📝 **회의에서 도출된 할 일들을 등록할까요?**", view=view)
        else:
            await ctx.send("💡 추가된 할 일이 없습니다.")
            await close_thread_logic()

    # 목록, 조회, 삭제는 기존 유지
    @meeting_group.command(name="목록")
    @is_authorized()
    async def list(self, ctx):
        rows = self.bot.db.get_recent_meetings(ctx.guild.id)
        if not rows: await ctx.send("📭 없음"); return
        e = discord.Embed(title="📂 회의록", color=0xf1c40f)
        for r in rows: e.add_field(name=f"[{r[0]}] {r[1]}", value=f"📅 {r[2]} | [바로가기]({r[4]})", inline=False)
        await ctx.send(embed=e)

    @meeting_group.command(name="조회")
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
        except: await ctx.send("❌ 데이터 손상")

    @meeting_group.command(name="삭제")
    @is_authorized()
    async def delete(self, ctx, id: int):
        if self.bot.db.delete_meeting(id, ctx.guild.id): await ctx.send("🗑️ 삭제됨")
        else: await ctx.send("❌ 실패")

async def setup(bot): await bot.add_cog(MeetingCog(bot))