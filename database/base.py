import sqlite3
import datetime

class BaseDB:
    def __init__(self, db_name="pm_bot.db"):
        self.db_name = db_name
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        
        tables = [
            '''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, role TEXT, joined_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS meetings (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, name TEXT, date TEXT, channel_id INTEGER, summary TEXT, jump_url TEXT)''',
            '''CREATE TABLE IF NOT EXISTS repositories (repo_name TEXT, channel_id INTEGER, added_by TEXT, date TEXT, PRIMARY KEY (repo_name, channel_id))''',
            '''CREATE TABLE IF NOT EXISTS projects (id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, name TEXT, parent_id INTEGER, created_at TEXT)''',
            '''CREATE TABLE IF NOT EXISTS tasks (task_id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, project_id INTEGER, content TEXT, assignee_id INTEGER, assignee_name TEXT, status TEXT DEFAULT 'TODO', created_at TEXT, source_meeting_id INTEGER)''',
            '''CREATE TABLE IF NOT EXISTS project_roles (project_id INTEGER, role_id INTEGER, role_name TEXT, PRIMARY KEY (project_id, role_id))''',
            # [Update] assistant_channel_id 컬럼 추가 (기존 테이블 호환을 위해 아래 마이그레이션에서 처리하거나 재생성)
            '''CREATE TABLE IF NOT EXISTS guild_settings (guild_id INTEGER PRIMARY KEY, dashboard_channel_id INTEGER, dashboard_message_id INTEGER, assistant_channel_id INTEGER)'''
        ]
        
        for table in tables:
            c.execute(table)

        # 마이그레이션
        migrations = [
            "ALTER TABLE meetings ADD COLUMN guild_id INTEGER",
            "ALTER TABLE tasks ADD COLUMN source_meeting_id INTEGER",
            "ALTER TABLE guild_settings ADD COLUMN assistant_channel_id INTEGER" # [New] 비서 채널 컬럼 추가
        ]
        for mig in migrations:
            try: c.execute(mig)
            except: pass
        
        conn.commit()
        conn.close()