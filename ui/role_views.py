import discord
from discord.ui import View, Button

class RoleCreationView(View):
    def __init__(self, role_names, author, next_cb, guild):
        super().__init__(timeout=180)
        self.roles = role_names
        self.author = author
        self.next_cb = next_cb
        self.guild = guild

    @discord.ui.button(label="역할 생성 승인", style=discord.ButtonStyle.green)
    async def create(self, interaction, button):
        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ 봇 권한 부족 (역할 관리)", ephemeral=True)
            return
        
        log = []
        for name in self.roles:
            try:
                await self.guild.create_role(name=name, reason="AI PM Bot")
                log.append(name)
            except: pass
        
        await interaction.message.edit(content=f"✅ 생성됨: {', '.join(log)}", view=None)
        self.stop()
        if self.next_cb: await self.next_cb()

    @discord.ui.button(label="건너뛰기", style=discord.ButtonStyle.grey)
    async def skip(self, interaction, button):
        await interaction.message.edit(content="➡️ 건너뜀", view=None)
        self.stop()
        if self.next_cb: await self.next_cb()

class RoleAssignmentView(View):
    def __init__(self, assignments, author, next_cb, guild):
        super().__init__(timeout=180)
        self.assigns = assignments
        self.author = author
        self.next_cb = next_cb
        self.guild = guild

    @discord.ui.button(label="역할 부여 승인", style=discord.ButtonStyle.green)
    async def assign(self, interaction, button):
        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ 봇 권한 부족", ephemeral=True)
            return

        log = []
        for a in self.assigns:
            m_name = a['member_name']
            r_name = a['role_name']
            member = discord.utils.find(lambda m: m_name in m.display_name, self.guild.members)
            role = discord.utils.get(self.guild.roles, name=r_name)
            
            if member and role:
                try:
                    await member.add_roles(role)
                    log.append(f"{member.display_name}->{role.name}")
                except: pass
        
        await interaction.message.edit(content=f"✅ 부여됨:\n"+"\n".join(log), view=None)
        self.stop()
        if self.next_cb: await self.next_cb()

    @discord.ui.button(label="건너뛰기", style=discord.ButtonStyle.grey)
    async def skip(self, interaction, button):
        await interaction.message.edit(content="➡️ 건너뜀", view=None)
        self.stop()
        if self.next_cb: await self.next_cb()