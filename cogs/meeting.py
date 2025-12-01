import discord
from discord.ext import commands
from discord import app_commands
import datetime
import json
from ui import EmbedPaginator, TaskSelectionView, StatusUpdateView, NewProjectView, RoleCreationView, RoleAssignmentView, AutoAssignTaskView
from utils import is_authorized, smart_chunk_text

# [NEW] 할 일 등록 및 담당자 자동 배정 뷰
class AutoAssignTaskView(discord.ui.View):
    def __init__(self, tasks, mid, author, guild, db):
        super().__init__(timeout=300)
        self.tasks = tasks
        self.mid = mid
        self.author = author
        self.guild = guild
        self.db = db
        self.selected_indices = []
        
        options = []
        for i, t in enumerate(tasks):
            # 글자수 제한 처리 및 라벨링
            # [Fix] JSON에서 값이 null로 올 경우를 대비해 or 연산자로 기본값 보장
            content = (t.get('content') or '내용 없음')[:40]
            project = (t.get('project') or '미정')[:15]
            assignee = (t.get('assignee_hint') or '미정')[:10]
            
            label = f"[{project}] {content}"
            description = f"담당 추천: {assignee}"
            
            options.append(discord.SelectOption(label=label, description=description, value=str(i)))
        
        if len(options) > 25: options = options[:25]
        
        self.select = discord.ui.Select(
            placeholder="등록 및 배정할 업무 선택",
            min_values=0,
            max_values=len(options),
            options=options
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction):
        self.selected_indices = [int(v) for v in self.select.values]
        await interaction.response.defer()

    @discord.ui.button(label="업무 등록 및 담당자 배정", style=discord.ButtonStyle.green, emoji="✅")
    async def save(self, interaction, button):
        if not self.selected_indices:
            await interaction.followup.send("⚠️ 선택된 항목이 없습니다.", ephemeral=True)
            return
            
        results = []
        for idx in self.selected_indices:
            t = self.tasks[idx]
            # 1. 태스크 등록
            tid = self.db.add_task(self.guild.id, t.get('project', '일반'), t['content'], self.mid)
            res_str = f"✅ **#{tid}** 등록"
            
            # 2. 담당자 매칭 (이름 유사도 검색)
            hint = t.get('assignee_hint')
            if hint:
                # 닉네임이나 이름에 힌트가 포함된 멤버 찾기
                target = discord.utils.find(lambda m: hint in m.display_name or hint in m.name, self.guild.members)
                if target:
                    if self.db.assign_task(tid, target.id, target.display_name):
                        res_str += f" → 👤 **{target.display_name}** 배정"
                else:
                    res_str += f" (담당 '{hint}' 미발견)"
            
            results.append(res_str)
            
        await interaction.message.edit(content="**[업무 처리 결과]**\n" + "\n".join(results), view=None)
        self.stop()

class MeetingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
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

    @meeting_group.command(name="시작", description="회의 기록 시작")
    @app_commands.describe(name="주제")
    @is_authorized()
    async def start_meeting(self, ctx, *, name: str = None):
        if ctx.channel.id in self.meeting_buffer: await ctx.send("🔴 진행 중"); return
        if not name: name = f"{datetime.datetime.now().strftime('%Y-%m-%d')} 회의"
        self.meeting_buffer[ctx.channel.id] = {'name': name, 'messages': [], 'jump_url': ctx.message.jump_url}
        await ctx.send(embed=discord.Embed(title="🎙️ 시작", description=name, color=0xe74c3c))

    @meeting_group.command(name="종료", description="회의 종료 및 분석")
    @is_authorized()
    async def stop_meeting(self, ctx):
        if ctx.channel.id not in self.meeting_buffer: await ctx.send("⚠️ 진행 중 아님"); return
        data = self.meeting_buffer.pop(ctx.channel.id)
        if not data['messages']: await ctx.send("📝 내용 없음"); return

        txt = "".join([f"[Speaker: {m['user']}] {m['content']}\n" for m in data['messages']])
        waiting = await ctx.send("🤖 AI 분석 중...")

        # 1. 요약
        full_result = await self.bot.ai.generate_meeting_summary(txt)
        lines = full_result.strip().split('\n')
        title = lines[0].replace("제목:", "").strip() if lines[0].startswith("제목:") else data['name']
        summary = "\n".join(lines[1:]).strip() if lines[0].startswith("제목:") else full_result
        m_id = self.bot.db.save_meeting(ctx.guild.id, title, ctx.channel.id, summary, data['jump_url'])

        # 2. 데이터 추출
        # [UPDATE] 프로젝트 목록을 JSON 리스트 문자열로 변환하여 명확하게 전달
        projs_list = [r[1] for r in self.bot.db.get_project_tree(ctx.guild.id)]
        projs_str = json.dumps(projs_list, ensure_ascii=False)
        
        active_tasks = self.bot.db.get_active_tasks_simple(ctx.guild.id)
        roles = ", ".join([r.name for r in ctx.guild.roles if not r.is_default()])
        mems = ", ".join([m.display_name for m in ctx.guild.members if not m.bot])

        res = await self.bot.ai.extract_tasks_and_updates(txt, projs_str, active_tasks, roles, mems)
        
        await waiting.delete()
        
        e = discord.Embed(title=f"✅ 종료: {title}", color=0x2ecc71)
        e.add_field(name="요약", value=summary[:500]+"...", inline=False)
        await ctx.send(embed=e)

        # 6-Step Flow
        async def step5_final():
            if not res.get('new_tasks'): await ctx.send("💡 할일 없음"); return
            # [변경] AutoAssignTaskView 사용
            await ctx.send("📝 **5. 할 일 등록 및 6. 담당자 배정**", view=AutoAssignTaskView(res['new_tasks'], m_id, ctx.author, ctx.guild, self.bot.db))

        async def step4():
            if not res.get('assign_roles'): await step5_final(); return
            await ctx.send(f"👤 **4. 역할 부여 제안**", view=RoleAssignmentView(res['assign_roles'], ctx.author, step5_final, ctx.guild))

        async def step3():
            if not res.get('create_roles'): await step4(); return
            await ctx.send(f"🛡️ **3. 새 역할 생성 제안**", view=RoleCreationView(res['create_roles'], ctx.author, step4, ctx.guild))

        async def step2():
            new_p = {}
            for t in res.get('new_tasks', []):
                if t.get('is_new_project'):
                    # suggest_parent가 있으면 사용, 없으면 None
                    new_p[t['project']] = t.get('suggested_parent')
            
            if new_p:
                desc = "\n".join([f"• **{k}** (상위: {v or '없음'})" for k, v in new_p.items()])
                await ctx.send(f"🆕 **2. 프로젝트 생성 제안**\n{desc}", view=NewProjectView(new_p, res['new_tasks'], ctx.author, step3, ctx.guild.id, self.bot.db))
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
        r = self.bot.db.get_meeting_detail(id, ctx.guild.id)
        if not r: await ctx.send("❌ 없음"); return
        chunks = smart_chunk_text(r[2])
        embeds = [discord.Embed(title=r[0], description=c, color=0xf1c40f) for c in chunks]
        if r[3]: embeds[0].add_field(name="링크", value=f"[이동]({r[3]})", inline=False)
        await ctx.send(embed=embeds[0], view=EmbedPaginator(embeds, ctx.author) if len(embeds)>1 else None)

    @meeting_group.command(name="삭제")
    @is_authorized()
    async def delete(self, ctx, id: int):
        if self.bot.db.delete_meeting(id, ctx.guild.id): await ctx.send("🗑️ 삭제됨")
        else: await ctx.send("❌ 실패")

async def setup(bot): await bot.add_cog(MeetingCog(bot))