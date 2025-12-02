import discord
from discord.ui import View, Button

class AssistantActionView(View):
    def __init__(self, action_data, author, execute_callback):
        super().__init__(timeout=60)
        self.action_data = action_data
        self.author = author
        self.execute_callback = execute_callback # 실행 로직이 담긴 비동기 함수
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("❌ 본인만 조작할 수 있습니다.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="실행", style=discord.ButtonStyle.green, emoji="🚀")
    async def confirm(self, interaction: discord.Interaction, button: Button):
        # 버튼 비활성화 (중복 클릭 방지)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="🔄 **처리 중...**", view=self)
        
        try:
            # 콜백 함수 실행 (여기에 실제 DB 작업 등이 들어감)
            await self.execute_callback(interaction, self.action_data)
        except Exception as e:
            await interaction.followup.send(f"❌ 실행 중 오류 발생: {e}", ephemeral=True)

    @discord.ui.button(label="취소", style=discord.ButtonStyle.grey, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: Button):
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content="❌ 사용자가 취소했습니다.", view=self)
        self.stop()