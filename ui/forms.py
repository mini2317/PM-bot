import discord
from discord.ui import Modal, TextInput

class ProjectCreateModal(Modal, title="새 프로젝트 생성"):
    name = TextInput(
        label="프로젝트 이름",
        placeholder="예: 모바일 앱 리뉴얼",
        max_length=50
    )

    def __init__(self, db, guild_id, callback=None):
        super().__init__()
        self.db = db
        self.guild_id = guild_id
        self.callback = callback 

    async def on_submit(self, interaction: discord.Interaction):
        project_name = self.name.value
        
        if self.callback:
            await self.callback(interaction, project_name)
        else:
            if self.db.create_project(self.guild_id, project_name):
                await interaction.response.send_message(f"🆕 프로젝트 **{project_name}** 생성 완료!", ephemeral=False)
            else:
                await interaction.response.send_message(f"⚠️ 이미 존재하는 프로젝트 이름입니다.", ephemeral=True)

class TaskCreateModal(Modal, title="새 할 일 등록"):
    project = TextInput(
        label="프로젝트 (비워두면 '일반')",
        placeholder="프로젝트 이름 입력",
        required=False,
        max_length=50
    )
    
    content = TextInput(
        label="할 일 내용",
        style=discord.TextStyle.paragraph,
        placeholder="예: 로그인 API 구현 및 테스트",
        max_length=500
    )

    def __init__(self, db, guild_id, view=None):
        super().__init__()
        self.db = db
        self.guild_id = guild_id
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        p_name = self.project.value or "일반"
        content_text = self.content.value
        
        # 1. 프로젝트 정보 조회 (포럼 채널 ID 확인용)
        pid = self.db.get_project_id(self.guild_id, p_name)
        project_data = self.db.get_project(pid) if pid else None
        
        thread_id = None
        message_id = None
        forum_link = ""

        # 2. 포럼 채널에 게시글 생성 시도
        if project_data and project_data.get('forum_channel_id'):
            forum_channel = interaction.guild.get_channel(project_data['forum_channel_id'])
            
            if forum_channel and isinstance(forum_channel, discord.ForumChannel):
                # 태그 찾기 (TODO 태그)
                todo_tag = next((tag for tag in forum_channel.available_tags if tag.name == "TODO"), None)
                applied_tags = [todo_tag] if todo_tag else []
                
                try:
                    # 포럼 스레드 생성
                    thread_with_message = await forum_channel.create_thread(
                        name=content_text[:100], # 제목 길이 제한
                        content=f"📝 **작업 상세**\n{content_text}\n\n👤 **생성자**: {interaction.user.mention}",
                        applied_tags=applied_tags
                    )
                    thread_id = thread_with_message.thread.id
                    message_id = thread_with_message.message.id
                    forum_link = f"\n🔗 [이슈 보드 바로가기]({thread_with_message.thread.jump_url})"
                except Exception as e:
                    print(f"포럼 글 생성 실패: {e}")

        # 3. DB 저장 (thread_id 포함)
        tid = self.db.add_task(self.guild_id, p_name, content_text, thread_id=thread_id, message_id=message_id)
        
        msg = f"✅ **[#{tid}] {content_text}** 등록됨 (📁 {p_name}){forum_link}"
        await interaction.response.send_message(msg, ephemeral=False)