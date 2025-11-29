import discord
from discord.ui import View, Button, Select

class EmbedPaginator(View):
    def __init__(self, embeds, author=None):
        super().__init__(timeout=120)
        self.embeds = embeds
        self.current_page = 0
        self.author = author
        self.update_buttons()

    def update_buttons(self):
        self.children[0].disabled = (self.current_page == 0)
        self.children[1].disabled = (self.current_page == len(self.embeds) - 1)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author and interaction.user != self.author:
            await interaction.response.send_message("🚫 권한이 없습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀️ 이전", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="다음 ▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

class StatusUpdateView(View):
    def __init__(self, updates, author, next_callback, db):
        super().__init__(timeout=180)
        self.updates = updates
        self.author = author
        self.next_callback = next_callback
        self.db = db
        self.selected_updates = []

        options = []
        for up in updates:
            label = f"#{up['task_id']} → {up['status']}"
            desc = up.get('reason', 'AI 제안')[:95]
            options.append(discord.SelectOption(label=label, description=desc, value=str(up['task_id'])))

        if len(options) > 25: options = options[:25]

        select = Select(placeholder="상태를 변경할 작업을 선택하세요", min_values=0, max_values=len(options), options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        select = [x for x in self.children if isinstance(x, Select)][0]
        self.selected_updates = select.values
        await interaction.response.defer()

    @discord.ui.button(label="적용 및 다음", style=discord.ButtonStyle.primary)
    async def apply_button(self, interaction: discord.Interaction, button: Button):
        applied_count = 0
        for tid_str in self.selected_updates:
            tid = int(tid_str)
            target_update = next((u for u in self.updates if u['task_id'] == tid), None)
            if target_update:
                self.db.update_task_status(tid, target_update['status'])
                applied_count += 1
        
        await interaction.response.send_message(f"✅ {applied_count}개의 작업 상태를 변경했습니다.", ephemeral=True)
        await interaction.message.edit(content="✅ 상태 변경 처리 완료.", view=None)
        self.stop()
        if self.next_callback: await self.next_callback(interaction.channel)

    @discord.ui.button(label="건너뛰기", style=discord.ButtonStyle.grey)
    async def skip_button(self, interaction: discord.Interaction, button: Button):
        await interaction.message.edit(content="➡️ 상태 변경 건너뜀.", view=None)
        self.stop()
        if self.next_callback: await self.next_callback(interaction.channel)

class NewProjectView(View):
    def __init__(self, new_proj_info, tasks_data, author, next_cb, guild_id, db):
        super().__init__(timeout=180)
        self.new_proj_info = new_proj_info
        self.tasks_data = tasks_data
        self.author = author
        self.next_cb = next_cb
        self.guild_id = guild_id
        self.db = db

    @discord.ui.button(label="생성 승인", style=discord.ButtonStyle.green)
    async def create_btn(self, interaction: discord.Interaction, button: Button):
        msg_log = []
        for name, parent in self.new_proj_info.items():
            if self.db.create_project(self.guild_id, name):
                log = f"🆕 **{name}** 생성됨"
                if parent:
                    if self.db.set_parent_project(self.guild_id, name, parent):
                        log += f" (상위: {parent})"
                msg_log.append(log)
            else:
                msg_log.append(f"⚠️ **{name}** (이미 존재)")
        
        await interaction.message.edit(content="\n".join(msg_log), view=None)
        self.stop()
        if self.next_cb: await self.next_cb(interaction.channel, self.tasks_data)

    @discord.ui.button(label="생성 안함 (기존 '회의도출' 사용)", style=discord.ButtonStyle.red)
    async def no_btn(self, interaction: discord.Interaction, button: Button):
        for t in self.tasks_data:
            if t.get('is_new_project'): t['project'] = "회의도출"
        await interaction.message.edit(content="🚫 생성 거절 -> '회의도출'로 분류", view=None)
        self.stop()
        if self.next_cb: await self.next_cb(interaction.channel, self.tasks_data)

class TaskSelectionView(View):
    def __init__(self, tasks_data, meeting_id, author, guild_id, db):
        super().__init__(timeout=300)
        self.tasks_data = tasks_data
        self.meeting_id = meeting_id
        self.author = author
        self.guild_id = guild_id
        self.db = db
        self.selected_indices = []

        options = []
        for i, task in enumerate(tasks_data):
            label = f"[{task.get('project','미정')}] {task['content']}"
            if len(label) > 100: label = label[:97] + "..."
            options.append(discord.SelectOption(label=label, value=str(i)))

        if len(options) > 25: options = options[:25]

        select = Select(placeholder="등록할 할 일을 선택하세요", min_values=0, max_values=len(options), options=options)
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        select = [x for x in self.children if isinstance(x, Select)][0]
        self.selected_indices = [int(v) for v in select.values]
        await interaction.response.defer()

    @discord.ui.button(label="저장", style=discord.ButtonStyle.green, emoji="💾")
    async def save_button(self, interaction: discord.Interaction, button: Button):
        if not self.selected_indices:
            return await interaction.response.send_message("⚠️ 선택된 항목이 없습니다.", ephemeral=True)

        count = 0
        for idx in self.selected_indices:
            t = self.tasks_data[idx]
            self.db.add_task(self.guild_id, t.get('project', '회의도출'), t['content'], self.meeting_id)
            count += 1
        
        await interaction.response.edit_message(content=f"✅ **{count}개**의 할 일이 등록되었습니다!", view=None)
        self.stop()

    @discord.ui.button(label="취소", style=discord.ButtonStyle.grey)
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(content="❌ 취소됨.", view=None)
        self.stop()