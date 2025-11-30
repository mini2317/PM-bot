import sqlite3
import datetime

class MeetingMixin:
    def save_meeting(self, gid, name, cid, smry, url):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("INSERT INTO meetings (guild_id,name,date,channel_id,summary,jump_url) VALUES (?,?,?,?,?,?)",
                  (gid, name, datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), cid, smry, url))
        mid = c.lastrowid; conn.commit(); conn.close(); return mid

    def delete_meeting(self, mid, gid):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("DELETE FROM meetings WHERE id=? AND guild_id=?", (mid, gid))
        res = c.rowcount > 0; conn.commit(); conn.close(); return res

    def get_recent_meetings(self, gid, lim=5):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT id, name, date, summary, jump_url FROM meetings WHERE guild_id=? ORDER BY id DESC LIMIT ?", (gid, lim))
        res = c.fetchall(); conn.close(); return res

    def get_meeting_detail(self, mid, gid):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT name, date, summary, jump_url FROM meetings WHERE id=? AND guild_id=?", (mid, gid))
        res = c.fetchone(); conn.close(); return res