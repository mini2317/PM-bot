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
        
        c.execute('''CREATE TABLE IF NOT EXISTS meetings
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      guild_id INTEGER,
                      name TEXT, 
                      date TEXT, 
                      channel_id INTEGER, 
                      summary TEXT,
                      jump_url TEXT)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS repositories
                     (repo_name TEXT, channel_id INTEGER, added_by TEXT, date TEXT,
                      PRIMARY KEY (repo_name, channel_id))''')

        c.execute('''CREATE TABLE IF NOT EXISTS projects
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      guild_id INTEGER,
                      name TEXT,
                      parent_id INTEGER, 
                      created_at TEXT)''')

        c.execute('''CREATE TABLE IF NOT EXISTS tasks
                     (task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      guild_id INTEGER,
                      project_id INTEGER,
                      content TEXT,
                      assignee_id INTEGER,
                      assignee_name TEXT,
                      status TEXT DEFAULT 'TODO',
                      created_at TEXT,
                      source_meeting_id INTEGER)''')
        
        try: c.execute("ALTER TABLE meetings ADD COLUMN guild_id INTEGER")
        except: pass
        try: c.execute("ALTER TABLE tasks ADD COLUMN source_meeting_id INTEGER")
        except: pass
        
        conn.commit()
        conn.close()

    # --- Users ---
    def add_user(self, user_id, username, role="user"):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        try: c.execute("INSERT INTO users VALUES (?,?,?,?)", (user_id, username, role, datetime.datetime.now().strftime("%Y-%m-%d"))); conn.commit(); return True
        except: return False
        finally: conn.close()
    
    def remove_user(self, uid): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("DELETE FROM users WHERE user_id=?",(uid,)); u=c.rowcount>0; conn.commit(); conn.close(); return u
    def is_authorized(self, uid): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("SELECT role FROM users WHERE user_id=?",(uid,)); r=c.fetchone(); conn.close(); return r is not None

    def ensure_admin(self, user_id, username):
        """[NEW] 봇 소유자를 관리자로 강제 등록"""
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT role FROM users WHERE user_id=?", (user_id,))
        row = c.fetchone()
        if not row:
            c.execute("INSERT INTO users VALUES (?,?,?,?)", (user_id, username, "admin", datetime.datetime.now().strftime("%Y-%m-%d")))
            conn.commit(); conn.close(); return True
        return False

    # --- Meetings ---
    def save_meeting(self, gid, name, cid, smry, url):
        conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("INSERT INTO meetings (guild_id,name,date,channel_id,summary,jump_url) VALUES (?,?,?,?,?,?)",(gid,name,datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),cid,smry,url)); mid=c.lastrowid; conn.commit(); conn.close(); return mid
    def delete_meeting(self, mid, gid): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("DELETE FROM meetings WHERE id=? AND guild_id=?",(mid,gid)); u=c.rowcount>0; conn.commit(); conn.close(); return u
    def get_recent_meetings(self, gid, lim=5): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("SELECT id,name,date,summary,jump_url FROM meetings WHERE guild_id=? ORDER BY id DESC LIMIT ?", (gid,lim)); r=c.fetchall(); conn.close(); return r
    def get_meeting_detail(self, mid, gid): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("SELECT name,date,summary,jump_url FROM meetings WHERE id=? AND guild_id=?",(mid,gid)); r=c.fetchone(); conn.close(); return r

    # --- Repositories ---
    def add_repo(self, r, c_id, by):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        try: c.execute("INSERT OR IGNORE INTO repositories VALUES (?,?,?,?)",(r,c_id,by,datetime.datetime.now().strftime("%Y-%m-%d"))); conn.commit(); return True
        except: return False
        finally: conn.close()
    def remove_repo(self, r, c_id): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("DELETE FROM repositories WHERE repo_name=? AND channel_id=?",(r,c_id)); u=c.rowcount>0; conn.commit(); conn.close(); return u
    def get_repo_channels(self, r): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("SELECT channel_id FROM repositories WHERE repo_name=?",(r,)); r=c.fetchall(); conn.close(); return [x[0] for x in r]
    def get_all_repos(self): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("SELECT repo_name, channel_id FROM repositories"); r=c.fetchall(); conn.close(); return r

    # --- Projects ---
    def create_project(self, guild_id, name, parent_id=None):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT id FROM projects WHERE guild_id=? AND name=?", (guild_id, name))
        if c.fetchone(): return None
        c.execute("INSERT INTO projects (guild_id, name, parent_id, created_at) VALUES (?, ?, ?, ?)",
                  (guild_id, name, parent_id, datetime.datetime.now().strftime("%Y-%m-%d")))
        pid = c.lastrowid; conn.commit(); conn.close(); return pid

    def get_project_id(self, guild_id, name):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT id FROM projects WHERE guild_id=? AND name=?", (guild_id, name))
        res = c.fetchone(); conn.close(); return res[0] if res else None

    def set_parent_project(self, guild_id, child_name, parent_name):
        child_id = self.get_project_id(guild_id, child_name)
        parent_id = self.get_project_id(guild_id, parent_name)
        if not child_id or not parent_id: return False
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("UPDATE projects SET parent_id=? WHERE id=?", (parent_id, child_id))
        conn.commit(); conn.close(); return True

    def get_project_tree(self, guild_id):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT id, name, parent_id FROM projects WHERE guild_id=?", (guild_id,))
        rows = c.fetchall(); conn.close(); return rows
    
    def get_all_projects(self):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT DISTINCT name FROM projects")
        rows = c.fetchall(); conn.close(); return [r[0] for r in rows]

    # --- Tasks ---
    def add_task(self, guild_id, project_name, content, source_meeting_id=None):
        pid = self.get_project_id(guild_id, project_name)
        if not pid: pid = self.create_project(guild_id, project_name)
        
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("INSERT INTO tasks (guild_id, project_id, content, status, created_at, source_meeting_id) VALUES (?,?,?, 'TODO',?,?)",
                  (guild_id, pid, content, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), source_meeting_id))
        tid = c.lastrowid; conn.commit(); conn.close(); return tid

    def get_tasks(self, guild_id, project_name=None):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        query = "SELECT t.task_id, p.name, t.content, t.assignee_id, t.assignee_name, t.status FROM tasks t LEFT JOIN projects p ON t.project_id = p.id WHERE t.guild_id = ?"
        params = [guild_id]
        if project_name: query += " AND p.name = ?"; params.append(project_name)
        query += " ORDER BY t.task_id"
        c.execute(query, tuple(params)); rows = c.fetchall(); conn.close(); return rows

    def get_active_tasks_simple(self, guild_id):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT task_id, content, status FROM tasks WHERE guild_id=? AND status != 'DONE'", (guild_id,))
        rows = c.fetchall(); conn.close()
        return [{'id': r[0], 'content': r[1], 'status': r[2]} for r in rows]

    def update_task_status(self, tid, s): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("UPDATE tasks SET status=? WHERE task_id=?",(s,tid)); u=c.rowcount>0; conn.commit(); conn.close(); return u
    def assign_task(self, tid, aid, an): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("UPDATE tasks SET assignee_id=?, assignee_name=? WHERE task_id=?",(aid,an,tid)); u=c.rowcount>0; conn.commit(); conn.close(); return u