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
        
        c.execute('''CREATE TABLE IF NOT EXISTS meetings
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      name TEXT, 
                      date TEXT, 
                      channel_id INTEGER, 
                      transcript TEXT, 
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
        
        # 마이그레이션 (기존 DB 호환용)
        try:
            c.execute("SELECT source_meeting_id FROM tasks LIMIT 1")
        except sqlite3.OperationalError:
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
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        finally:
            conn.close()

    def remove_user(self, user_id):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def is_authorized(self, user_id):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result is not None

    # --- Meetings ---
    def save_meeting(self, name, channel_id, transcript, summary, jump_url):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        c.execute("INSERT INTO meetings (name, date, channel_id, transcript, summary, jump_url) VALUES (?, ?, ?, ?, ?, ?)",
                  (name, date_str, channel_id, transcript, summary, jump_url))
        log_id = c.lastrowid
        conn.commit()
        conn.close()
        return log_id

    def delete_meeting(self, meeting_id):
        """[NEW] 회의록 삭제"""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def get_recent_meetings(self, limit=5):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT id, name, date, summary, jump_url FROM meetings ORDER BY id DESC LIMIT ?", (limit,))
        rows = c.fetchall()
        conn.close()
        return rows

    def get_meeting_detail(self, meeting_id):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT name, date, summary, transcript, jump_url FROM meetings WHERE id = ?", (meeting_id,))
        row = c.fetchone()
        conn.close()
        return row

    # --- Repositories ---
    def add_repo(self, repo_name, channel_id, added_by):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        try:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            c.execute("INSERT OR REPLACE INTO repositories VALUES (?, ?, ?, ?)",
                      (repo_name, channel_id, added_by, date_str))
            conn.commit()
            return True
        except:
            return False
        finally:
            conn.close()

    def remove_repo(self, repo_name):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("DELETE FROM repositories WHERE repo_name = ?", (repo_name,))
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def get_repo_channel(self, repo_name):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT channel_id FROM repositories WHERE repo_name = ?", (repo_name,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else None

    def get_all_repos(self):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT repo_name, channel_id FROM repositories")
        rows = c.fetchall()
        conn.close()
        return rows

    # --- Tasks ---
    def add_task(self, project_name, content, source_meeting_id=None):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        c.execute("INSERT INTO tasks (project_name, content, status, created_at, source_meeting_id) VALUES (?, ?, 'TODO', ?, ?)",
                  (project_name, content, date_str, source_meeting_id))
        task_id = c.lastrowid
        conn.commit()
        conn.close()
        return task_id

    def get_tasks(self, project_name=None):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        if project_name:
            c.execute("SELECT * FROM tasks WHERE project_name = ? ORDER BY task_id", (project_name,))
        else:
            c.execute("SELECT * FROM tasks ORDER BY task_id")
        rows = c.fetchall()
        conn.close()
        return rows

    def update_task_status(self, task_id, status):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT task_id FROM tasks WHERE task_id = ?", (task_id,))
        if not c.fetchone():
            conn.close()
            return False
        c.execute("UPDATE tasks SET status = ? WHERE task_id = ?", (status, task_id))
        conn.commit()
        conn.close()
        return True

    def assign_task(self, task_id, assignee_id, assignee_name):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("UPDATE tasks SET assignee_id = ?, assignee_name = ? WHERE task_id = ?", 
                  (assignee_id, assignee_name, task_id))
        updated = c.rowcount > 0
        conn.commit()
        conn.close()
        return updated