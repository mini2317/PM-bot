import sqlite3
import datetime
import uuid

class PageMixin:
    def create_page(self, title, content, owner_id):
        page_id = str(uuid.uuid4())[:8] # 짧은 ID 사용
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("INSERT INTO pages VALUES (?, ?, ?, ?, ?)", 
                  (page_id, title, content, owner_id, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit(); conn.close()
        return page_id

    def get_page(self, page_id):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT * FROM pages WHERE page_id=?", (page_id,))
        res = c.fetchone()
        conn.close()
        if res:
            return {"id": res[0], "title": res[1], "content": res[2], "owner": res[3], "updated": res[4]}
        return None

    def update_page(self, page_id, content):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("UPDATE pages SET content=?, updated_at=? WHERE page_id=?", 
                  (content, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), page_id))
        conn.commit(); conn.close()