import sqlite3
import datetime

class BaseDB:
    def __init__(self, db_name="pm_bot.db"):
        self.db_name = db_name
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        
        # 1. 유저
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, username TEXT, role TEXT, joined_at TEXT)''')
        
        # 2. 회의록
        c.execute('''CREATE TABLE IF NOT EXISTS meetings
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      guild_id INTEGER,
                      name TEXT, 
                      date TEXT, 
                      channel_id INTEGER, 
                      summary TEXT,
                      jump_url TEXT)''')
        
        # 3. 레포지토리
        c.execute('''CREATE TABLE IF NOT EXISTS repositories
                     (repo_name TEXT, channel_id INTEGER, added_by TEXT, date TEXT,
                      PRIMARY KEY (repo_name, channel_id))''')

        # 4. [UPDATE] 프로젝트 (실제 디스코드 ID 매핑 추가)
        c.execute('''CREATE TABLE IF NOT EXISTS projects
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      guild_id INTEGER,
                      name TEXT,
                      parent_id INTEGER, 
                      created_at TEXT,
                      category_id INTEGER,        -- 디스코드 카테고리 ID
                      forum_channel_id INTEGER,   -- 이슈 트래킹 포럼 채널 ID
                      meeting_channel_id INTEGER  -- 회의용 텍스트 채널 ID
                      )''')

        # 5. [UPDATE] 할 일 (포럼 스레드 매핑 추가)
        c.execute('''CREATE TABLE IF NOT EXISTS tasks
                     (task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      guild_id INTEGER,
                      project_id INTEGER,
                      content TEXT,
                      assignee_id INTEGER,
                      assignee_name TEXT,
                      status TEXT DEFAULT 'TODO',
                      created_at TEXT,
                      source_meeting_id INTEGER,
                      thread_id INTEGER,          -- 포럼 게시글(스레드) ID
                      message_id INTEGER          -- 상태 변경 추적용 메시지 ID
                      )''')
        
        # 6. 프로젝트-역할 매핑
        c.execute('''CREATE TABLE IF NOT EXISTS project_roles
                     (project_id INTEGER, role_id INTEGER, role_name TEXT,
                      PRIMARY KEY (project_id, role_id))''')

        # 7. 설정
        c.execute('''CREATE TABLE IF NOT EXISTS guild_settings 
                     (guild_id INTEGER PRIMARY KEY, dashboard_channel_id INTEGER, dashboard_message_id INTEGER, assistant_channel_id INTEGER)''')
        
        # 8. 웹 페이지
        c.execute('''CREATE TABLE IF NOT EXISTS pages
                     (page_id TEXT PRIMARY KEY, title TEXT, content TEXT, owner_id INTEGER, updated_at TEXT)''')

        # [마이그레이션] 기존 테이블에 새 컬럼 추가
        migrations = [
            "ALTER TABLE meetings ADD COLUMN guild_id INTEGER",
            "ALTER TABLE tasks ADD COLUMN source_meeting_id INTEGER",
            "ALTER TABLE guild_settings ADD COLUMN assistant_channel_id INTEGER",
            # [NEW] 프로젝트 테이블 컬럼 추가
            "ALTER TABLE projects ADD COLUMN category_id INTEGER",
            "ALTER TABLE projects ADD COLUMN forum_channel_id INTEGER",
            "ALTER TABLE projects ADD COLUMN meeting_channel_id INTEGER",
            # [NEW] 태스크 테이블 컬럼 추가
            "ALTER TABLE tasks ADD COLUMN thread_id INTEGER",
            "ALTER TABLE tasks ADD COLUMN message_id INTEGER"
        ]
        for mig in migrations:
            try: c.execute(mig)
            except: pass
        
        conn.commit()
        conn.close()