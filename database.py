import sqlite3
import datetime

class DBManager:
    def __init__(self, db_name="pm_bot.db"):
        self.db_name = db_name
        self.init_db()

    def init_db(self):
        """테이블 초기화"""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, username TEXT, role TEXT, joined_at TEXT)''')
        
        # [변경] transcript 컬럼 제거 (요약본만 저장)
        c.execute('''CREATE TABLE IF NOT EXISTS meetings
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      guild_id INTEGER,
                      name TEXT, 
                      date TEXT, 
                      channel_id INTEGER, 
                      summary TEXT,
                      jump_url TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS repositories
                     (repo_name TEXT PRIMARY KEY, channel_id INTEGER, added_by TEXT, date TEXT)''')

        c.execute('''CREATE TABLE IF NOT EXISTS tasks
                     (task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      project_name TEXT,
                      content TEXT,
                      assignee_id INTEGER,
                      assignee_name TEXT,
                      status TEXT DEFAULT 'TODO',
                      created_at TEXT,
                      source_meeting_id INTEGER)''')

        # 마이그레이션: 기존 DB 호환성 처리 (컬럼 추가 등)
        try: c.execute("ALTER TABLE meetings ADD COLUMN guild_id INTEGER")
        except: pass
        try: c.execute("ALTER TABLE tasks ADD COLUMN source_meeting_id INTEGER")
        except: pass
        
        conn.commit()
        conn.close()

    # --- Users ---
    def add_user(self, user_id, username, role="user"):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users VALUES (?, ?, ?, ?)",
                      (user_id, username, role, datetime.datetime.now().strftime("%Y-%m-%d")))
            conn.commit(); return True
        except: return False
        finally: conn.close()

    def remove_user(self, user_id):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        deleted = c.rowcount > 0
        conn.commit(); conn.close(); return deleted

    def is_authorized(self, user_id):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
        res = c.fetchone()
        conn.close(); return res is not None

    # --- Meetings (Transcript 제거됨) ---
    def save_meeting(self, guild_id, name, channel_id, summary, jump_url):
        """[변경] 원본(transcript) 제외하고 저장"""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        c.execute("INSERT INTO meetings (guild_id, name, date, channel_id, summary, jump_url) VALUES (?, ?, ?, ?, ?, ?)",
                  (guild_id, name, date_str, channel_id, summary, jump_url))
        log_id = c.lastrowid
        conn.commit(); conn.close(); return log_id

    def delete_meeting(self, meeting_id, guild_id):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("DELETE FROM meetings WHERE id = ? AND guild_id = ?", (meeting_id, guild_id))
        deleted = c.rowcount > 0
        conn.commit(); conn.close(); return deleted

    def get_recent_meetings(self, guild_id, limit=5):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT id, name, date, summary, jump_url FROM meetings WHERE guild_id = ? ORDER BY id DESC LIMIT ?", (guild_id, limit))
        rows = c.fetchall()
        conn.close(); return rows

    def get_meeting_detail(self, meeting_id, guild_id):
        """[변경] 원본 조회 제거"""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT name, date, summary, jump_url FROM meetings WHERE id = ? AND guild_id = ?", (meeting_id, guild_id))
        row = c.fetchone()
        conn.close(); return row

    # --- Repositories ---
    def add_repo(self, repo_name, channel_id, added_by):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        try:
            c.execute("INSERT OR REPLACE INTO repositories VALUES (?, ?, ?, ?)", 
                      (repo_name, channel_id, added_by, datetime.datetime.now().strftime("%Y-%m-%d")))
            conn.commit(); return True
        except: return False
        finally: conn.close()

    def remove_repo(self, repo_name):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("DELETE FROM repositories WHERE repo_name = ?", (repo_name,))
        deleted = c.rowcount > 0
        conn.commit(); conn.close(); return deleted

    def get_repo_channel(self, repo_name):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT channel_id FROM repositories WHERE repo_name = ?", (repo_name,))
        res = c.fetchone(); conn.close(); return res[0] if res else None

    def get_all_repos(self):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT repo_name, channel_id FROM repositories")
        rows = c.fetchall(); conn.close(); return rows

    # --- Tasks ---
    def add_task(self, project_name, content, source_meeting_id=None):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("INSERT INTO tasks (project_name, content, status, created_at, source_meeting_id) VALUES (?, ?, 'TODO', ?, ?)",
                  (project_name, content, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), source_meeting_id))
        tid = c.lastrowid; conn.commit(); conn.close(); return tid

    def get_tasks(self, project_name=None):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        if project_name: c.execute("SELECT * FROM tasks WHERE project_name = ? ORDER BY task_id", (project_name,))
        else: c.execute("SELECT * FROM tasks ORDER BY task_id")
        rows = c.fetchall(); conn.close(); return rows

    def update_task_status(self, task_id, status):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("UPDATE tasks SET status = ? WHERE task_id = ?", (status, task_id))
        u = c.rowcount > 0; conn.commit(); conn.close(); return u

    def assign_task(self, task_id, assignee_id, assignee_name):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("UPDATE tasks SET assignee_id = ?, assignee_name = ? WHERE task_id = ?", (assignee_id, assignee_name, task_id))
        u = c.rowcount > 0; conn.commit(); conn.close(); return u