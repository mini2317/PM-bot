import sqlite3
import datetime

class ProjectMixin:
    # --- Projects ---
    def create_project(self, guild_id, name, parent_id=None):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT id FROM projects WHERE guild_id=? AND name=?", (guild_id, name))
        if c.fetchone(): conn.close(); return None
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
        res = c.fetchall(); conn.close(); return res
    
    def get_all_projects(self):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT DISTINCT name FROM projects")
        res = c.fetchall(); conn.close(); return [x[0] for x in res]

    # --- Roles ---
    def link_project_role(self, pid, rid, rname):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO project_roles VALUES (?, ?, ?)", (pid, rid, rname))
        conn.commit(); conn.close(); return True

    def get_project_roles(self, pid):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT role_id, role_name FROM project_roles WHERE project_id=?", (pid,))
        res = c.fetchall(); conn.close(); return res

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
        c.execute(query, tuple(params)); res = c.fetchall(); conn.close(); return res

    def get_active_tasks_simple(self, guild_id):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT task_id, content, status FROM tasks WHERE guild_id=? AND status != 'DONE'", (guild_id,))
        res = c.fetchall(); conn.close()
        return [{'id': r[0], 'content': r[1], 'status': r[2]} for r in res]

    def update_task_status(self, tid, s):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("UPDATE tasks SET status=? WHERE task_id=?", (s, tid))
        res = c.rowcount > 0; conn.commit(); conn.close(); return res
    
    def assign_task(self, tid, aid, an):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("UPDATE tasks SET assignee_id=?, assignee_name=? WHERE task_id=?", (aid, an, tid))
        res = c.rowcount > 0; conn.commit(); conn.close(); return res