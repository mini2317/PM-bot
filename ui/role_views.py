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
        # 봇 권한 체크
        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ 봇에게 '역할 관리' 권한이 없어 실행할 수 없습니다.", ephemeral=True)
            return

        log = []
        for name in self.roles:
            # 이미 존재하는지 확인
            existing = discord.utils.get(self.guild.roles, name=name)
            if existing:
                log.append(f"{name}(이미 있음)")
                continue
                
            try:
                await self.guild.create_role(name=name, reason="AI PM Bot: 회의 결과 자동 생성")
                log.append(name)
            except Exception as e:
                # 봇보다 상위 역할이거나 기타 권한 문제
                await interaction.channel.send(f"⚠️ 역할 '{name}' 생성 실패: {e}")
        
        await interaction.message.edit(content=f"✅ 역할 처리 완료: {', '.join(log)}", view=None)
        self.stop()
        if self.next_cb: await self.next_cb()

    @discord.ui.button(label="건너뛰기", style=discord.ButtonStyle.grey)
    async def skip(self, interaction, button):
        await interaction.message.edit(content="➡️ 역할 생성 건너뜀", view=None)
        self.stop()
        if self.next_cb: await self.next_cb()

class RoleAssignmentView(View):
    def __init__(self, assignments, author, next_cb, guild):
        super().__init__(timeout=180)
        self.assigns = assignments # [{'member_name': '...', 'role_name': '...'}]
        self.author = author
        self.next_cb = next_cb
        self.guild = guild

    @discord.ui.button(label="역할 부여 승인", style=discord.ButtonStyle.green)
    async def assign(self, interaction, button):
        if not interaction.guild.me.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ 봇에게 '역할 관리' 권한이 없습니다.", ephemeral=True)
            return

        log = []
        for a in self.assigns:
            # [Fix] KeyError 방지를 위해 .get() 사용 및 대체 키 확인
            m_name = a.get('member_name') or a.get('member') or a.get('user_name')
            r_name = a.get('role_name') or a.get('role')

            if not m_name or not r_name:
                log.append(f"⚠️ 데이터 오류 (이름/역할 누락): {a}")
                continue
            
            # 멤버, 역할 객체 찾기 (이름으로 매칭)
            # 1. 멤버 찾기 (닉네임 or 사용자명 포함 여부)
            member = discord.utils.find(lambda m: m_name in m.display_name or m_name in m.name, self.guild.members)
            # 2. 역할 찾기 (정확한 이름)
            role = discord.utils.get(self.guild.roles, name=r_name)

            if member and role:
                try:
                    await member.add_roles(role, reason="AI PM Bot 자동 부여")
                    log.append(f"{member.display_name} -> {role.name}")
                except Exception as e:
                    log.append(f"⚠️ {m_name} 부여 실패 (권한 부족 등)")
            else:
                reason = []
                if not member: reason.append(f"멤버 '{m_name}' 미발견")
                if not role: reason.append(f"역할 '{r_name}' 미발견")
                log.append(f"⚠️ 실패: {', '.join(reason)}")

        result_msg = f"✅ 역할 부여 결과:\n" + "\n".join(log)
        # 메시지가 너무 길 경우를 대비해 잘라서 전송
        if len(result_msg) > 2000:
            result_msg = result_msg[:1990] + "..."
            
        await interaction.message.edit(content=result_msg, view=None)
        self.stop()
        if self.next_cb: await self.next_cb()

    @discord.ui.button(label="건너뛰기", style=discord.ButtonStyle.grey)
    async def skip(self, interaction, button):
        await interaction.message.edit(content="➡️ 역할 부여 건너뜀", view=None)
        self.stop()
        if self.next_cb: await self.next_cb()