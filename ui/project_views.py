import discord
from discord.ui import View, Button, Select

class StatusUpdateView(View):
    def __init__(self, updates, author, next_callback, db):
        super().__init__(timeout=180)
        self.updates = updates
        self.author = author
        self.next_callback = next_callback
        self.db = db
        
        options = []
        for up in updates:
            label = f"#{up['task_id']} → {up['status']}"
            desc = up.get('reason', 'AI 제안')[:95]
            options.append(discord.SelectOption(label=label, description=desc, value=str(up['task_id'])))
        
        if len(options) > 25: options = options[:25]
        
        self.select = Select(placeholder="상태 변경 선택", options=options, min_values=0, max_values=len(options))
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction):
        self.vals = [int(v) for v in self.select.values]
        await interaction.response.defer()

    @discord.ui.button(label="적용", style=discord.ButtonStyle.primary)
    async def apply(self, interaction, button):
        if hasattr(self, 'vals'):
            for tid in self.vals:
                st = next((u['status'] for u in self.updates if u['task_id'] == tid), None)
                if st: self.db.update_task_status(tid, st)
        await interaction.message.edit(content="✅ 상태 변경 완료", view=None)
        self.stop()
        if self.next_callback: await self.next_callback()

    @discord.ui.button(label="건너뛰기", style=discord.ButtonStyle.grey)
    async def skip(self, interaction, button):
        await interaction.message.edit(content="➡️ 건너뜀", view=None)
        self.stop()
        if self.next_callback: await self.next_callback()

class NewProjectView(View):
    def __init__(self, new_proj_info, tasks, author, next_cb, guild_id, db):
        super().__init__(timeout=180)
        self.info = new_proj_info
        self.tasks = tasks
        self.author = author
        self.next_cb = next_cb
        self.gid = guild_id
        self.db = db

    @discord.ui.button(label="생성 승인", style=discord.ButtonStyle.green)
    async def ok(self, interaction, button):
        msg = []
        for n, p in self.info.items():
            if self.db.create_project(self.gid, n):
                log = f"🆕 **{n}**"
                if p and self.db.set_parent_project(self.gid, n, p): log += f" (상위:{p})"
                msg.append(log)
        await interaction.message.edit(content="\n".join(msg) or "생성된 프로젝트 없음", view=None)
        self.stop()
        if self.next_cb: await self.next_cb()

    @discord.ui.button(label="거절", style=discord.ButtonStyle.red)
    async def no(self, interaction, button):
        for t in self.tasks:
            if t.get('is_new_project'): t['project'] = "회의도출"
        await interaction.message.edit(content="🚫 생성 거절", view=None)
        self.stop()
        if self.next_cb: await self.next_cb()

class TaskSelectionView(View):
    def __init__(self, tasks, mid, author, guild_id, db):
        super().__init__(timeout=300)
        self.tasks = tasks
        self.mid = mid
        self.author = author
        self.gid = guild_id
        self.db = db
        
        options = []
        for i, t in enumerate(tasks):
            label = f"[{t.get('project','미정')}] {t['content'][:80]}"
            options.append(discord.SelectOption(label=label, value=str(i)))
        
        if len(options) > 25: options = options[:25]
        
        self.select = Select(placeholder="등록할 할일 선택", options=options, min_values=0, max_values=len(options))
        self.select.callback = self.cb
        self.add_item(self.select)

    async def cb(self, interaction):
        self.vals = [int(v) for v in self.select.values]
        await interaction.response.defer()

    @discord.ui.button(label="저장", style=discord.ButtonStyle.green)
    async def save(self, interaction, button):
        if not hasattr(self, 'vals'): return
        c = 0
        for idx in self.vals:
            t = self.tasks[idx]
            self.db.add_task(self.gid, t.get('project', '일반'), t['content'], self.mid)
            c += 1
        await interaction.message.edit(content=f"✅ {c}개 등록됨", view=None)
        self.stop()

    @discord.ui.button(label="취소", style=discord.ButtonStyle.grey)
    async def cancel(self, interaction, button):
        await interaction.message.edit(content="❌ 취소", view=None)
        self.stop()