import sqlite3
import datetime

class DBManager:
    def __init__(self, db_name="pm_bot.db"):
        self.db_name = db_name
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, username TEXT, role TEXT, joined_at TEXT)''')
        
        # [변경] guild_id 컬럼 추가 (서버 구분용)
        c.execute('''CREATE TABLE IF NOT EXISTS meetings
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      guild_id INTEGER,
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
        
        # 마이그레이션: 기존 DB에 guild_id가 없으면 추가
        try:
            c.execute("ALTER TABLE meetings ADD COLUMN guild_id INTEGER")
        except sqlite3.OperationalError:
            pass # 이미 존재함

        # 마이그레이션: tasks 테이블 보완
        try:
            c.execute("ALTER TABLE tasks ADD COLUMN source_meeting_id INTEGER")
        except sqlite3.OperationalError:
            pass

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
    def save_meeting(self, guild_id, name, channel_id, transcript, summary, jump_url):
        """[변경] guild_id를 함께 저장"""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        c.execute("INSERT INTO meetings (guild_id, name, date, channel_id, transcript, summary, jump_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (guild_id, name, date_str, channel_id, transcript, summary, jump_url))
        log_id = c.lastrowid
        conn.commit()
        conn.close()
        return log_id

    def delete_meeting(self, meeting_id, guild_id):
        """[변경] 해당 서버의 회의록만 삭제 가능"""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("DELETE FROM meetings WHERE id = ? AND guild_id = ?", (meeting_id, guild_id))
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def get_recent_meetings(self, guild_id, limit=5):
        """[변경] 요청한 서버(guild_id)의 회의록만 조회"""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT id, name, date, summary, jump_url FROM meetings WHERE guild_id = ? ORDER BY id DESC LIMIT ?", (guild_id, limit))
        rows = c.fetchall()
        conn.close()
        return rows

    def get_meeting_detail(self, meeting_id, guild_id):
        """[변경] 해당 서버의 회의록인지 확인 후 조회"""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT name, date, summary, transcript, jump_url FROM meetings WHERE id = ? AND guild_id = ?", (meeting_id, guild_id))
        row = c.fetchone()
        conn.close()
        return row

    # --- Repositories ---
    def add_user(self, u_id, name, role="user"):
        # (기존 코드와 동일)
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (u_id, name, role, datetime.datetime.now().strftime("%Y-%m-%d")))
            conn.commit(); return True
        except: return False
    def remove_user(self, u_id):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("DELETE FROM users WHERE user_id=?",(u_id,)); deleted=c.rowcount>0; conn.commit(); return deleted
    def is_authorized(self, u_id):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT role FROM users WHERE user_id=?",(u_id,)); res=c.fetchone(); return res is not None
    def add_repo(self, r, c_id, by):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        try: c.execute("INSERT OR REPLACE INTO repositories VALUES (?,?,?,?)",(r,c_id,by,datetime.datetime.now().strftime("%Y-%m-%d"))); conn.commit(); return True
        except: return False
    def remove_repo(self, r):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("DELETE FROM repositories WHERE repo_name=?",(r,)); deleted=c.rowcount>0; conn.commit(); return deleted
    def get_repo_channel(self, r):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT channel_id FROM repositories WHERE repo_name=?",(r,)); res=c.fetchone(); return res[0] if res else None
    def get_all_repos(self):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT repo_name, channel_id FROM repositories"); return c.fetchall()
    def add_task(self, p, ct, sm_id=None):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("INSERT INTO tasks (project_name, content, status, created_at, source_meeting_id) VALUES (?,?,'TODO',?,?)",(p,ct,datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), sm_id)); tid=c.lastrowid; conn.commit(); return tid
    def get_tasks(self, p=None):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        if p: c.execute("SELECT * FROM tasks WHERE project_name=? ORDER BY task_id",(p,))
        else: c.execute("SELECT * FROM tasks ORDER BY task_id")
        return c.fetchall()
    def update_task_status(self, t_id, s):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("UPDATE tasks SET status=? WHERE task_id=?",(s,t_id)); u=c.rowcount>0; conn.commit(); return u
    def assign_task(self, t_id, a_id, a_name):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("UPDATE tasks SET assignee_id=?, assignee_name=? WHERE task_id=?",(a_id,a_name,t_id)); u=c.rowcount>0; conn.commit(); return u