import sqlite3
import datetime

class RepoMixin:
    def add_repo(self, r, c_id, by):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        try:
            c.execute("INSERT OR IGNORE INTO repositories VALUES (?,?,?,?)", (r, c_id, by, datetime.datetime.now().strftime("%Y-%m-%d")))
            conn.commit(); return True
        except: return False
        finally: conn.close()

    def remove_repo(self, r, c_id):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("DELETE FROM repositories WHERE repo_name=? AND channel_id=?", (r, c_id))
        res = c.rowcount > 0; conn.commit(); conn.close(); return res

    def get_repo_channels(self, r):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT channel_id FROM repositories WHERE repo_name=?", (r,))
        res = c.fetchall(); conn.close(); return [x[0] for x in res]

    def get_all_repos(self):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT repo_name, channel_id FROM repositories")
        res = c.fetchall(); conn.close(); return res