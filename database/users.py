import sqlite3
import datetime

class UserMixin:
    def add_user(self, user_id, username, role="user"):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        try: 
            c.execute("INSERT OR IGNORE INTO users VALUES (?,?,?,?)", (user_id, username, role, datetime.datetime.now().strftime("%Y-%m-%d")))
            conn.commit(); return True
        except: return False
        finally: conn.close()

    def remove_user(self, uid):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("DELETE FROM users WHERE user_id=?", (uid,))
        res = c.rowcount > 0; conn.commit(); conn.close(); return res

    def is_authorized(self, uid):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT role FROM users WHERE user_id=?", (uid,))
        res = c.fetchone(); conn.close(); return res is not None

    def ensure_admin(self, user_id, username):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT role FROM users WHERE user_id=?", (user_id,))
        if not c.fetchone():
            c.execute("INSERT INTO users VALUES (?,?,?,?)", (user_id, username, "admin", datetime.datetime.now().strftime("%Y-%m-%d")))
            conn.commit(); conn.close(); return True
        conn.close(); return False