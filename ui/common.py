import discord
from discord.ui import View, Button

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

    @discord.ui.button(label="◀️", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: Button):
        self.current_page -= 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="▶️", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        self.current_page += 1
        self.update_buttons()
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)