import discord
from discord.ui import View, Select

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
            
            # 포럼 스레드 생성 (이슈 보드)
            pid = self.db.get_project_id(self.guild.id, p_name)
            project_data = self.db.get_project(pid) if pid else None
            
            thread_id = None
            message_id = None
            forum_link = ""

            # 프로젝트에 연결된 포럼 채널이 있으면 게시글 생성
            if project_data and project_data.get('forum_channel_id'):
                forum = self.guild.get_channel(project_data['forum_channel_id'])
                if forum and isinstance(forum, discord.ForumChannel):
                    try:
                        todo_tag = next((tag for tag in forum.available_tags if tag.name == "TODO"), None)
                        tags = [todo_tag] if todo_tag else []
                        th = await forum.create_thread(
                            name=content[:100],
                            content=f"📝 **회의 도출 작업**\n{content}\n\n🔗 **출처**: 회의록 #{self.mid}\n👤 **생성자**: {self.author.mention}",
                            applied_tags=tags
                        )
                        thread_id = th.thread.id
                        message_id = th.message.id
                        forum_link = " 🔗"
                    except: pass

            # DB 저장
            tid = self.db.add_task(self.guild.id, p_name, content, self.mid, thread_id=thread_id, message_id=message_id)
            res_str = f"✅ **#{tid}** 등록{forum_link}"
            
            # 담당자 배정
            hint = t.get('assignee_hint')
            if hint:
                target = discord.utils.find(lambda m: hint in m.display_name or hint in m.name, self.guild.members)
                if target:
                    if self.db.assign_task(tid, target.id, target.display_name):
                        res_str += f" → 👤 {target.display_name}"
                        if thread_id:
                            try:
                                th_ch = self.guild.get_thread(thread_id) or await self.guild.fetch_channel(thread_id)
                                if th_ch: await th_ch.send(f"👤 **담당자 지정**: {target.mention}")
                            except: pass

            results.append(res_str)
            
        await interaction.message.edit(content="**[처리 결과]**\n" + "\n".join(results), view=None)
        self.stop()
        
        # 현황판 갱신 (Cog 접근이 어려우므로 생략하거나, cleanup 콜백에서 처리 유도)
        # 여기서는 단순히 뷰 종료만 처리
        if self.cleanup_callback: await self.cleanup_callback()

    @discord.ui.button(label="건너뛰기", style=discord.ButtonStyle.grey, emoji="⏭️")
    async def skip(self, interaction, button):
        await interaction.message.edit(content="➡️ 할 일 등록을 건너뛰었습니다.", view=None)
        self.stop()
        if self.cleanup_callback: await self.cleanup_callback()