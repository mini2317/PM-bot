import sqlite3
import datetime

class DBManager:
    def __init__(self, db_name="pm_bot.db"):
        self.db_name = db_name
        self.init_db()

    def init_db(self):
        """테이블 초기화 및 마이그레이션"""
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
        
        c.execute('''CREATE TABLE IF NOT EXISTS tasks
                     (task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      project_name TEXT,
                      content TEXT,
                      assignee_id INTEGER,
                      assignee_name TEXT,
                      status TEXT DEFAULT 'TODO',
                      created_at TEXT,
                      source_meeting_id INTEGER)''')

        # [변경] 레포지토리 테이블 마이그레이션 (Single PK -> Composite PK)
        # 기존 테이블이 있고, 스키마가 구버전(repo_name만 PK)일 수 있으므로 안전하게 마이그레이션 진행
        try:
            # 1. 새 구조의 임시 테이블 생성 (repo_name + channel_id 복합키)
            c.execute('''CREATE TABLE IF NOT EXISTS repositories_new
                         (repo_name TEXT, channel_id INTEGER, added_by TEXT, date TEXT,
                          PRIMARY KEY (repo_name, channel_id))''')
            
            # 2. 기존 데이터가 있다면 확인
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='repositories'")
            if c.fetchone():
                # 3. 기존 데이터 복사 (충돌 시 무시)
                c.execute("INSERT OR IGNORE INTO repositories_new SELECT * FROM repositories")
                # 4. 기존 테이블 삭제 후 이름 변경 (필요시)
                # 안전을 위해 기존 테이블을 바로 지우진 않고, 사용자가 수동 관리하거나
                # 코드가 repositories_new를 쓰도록 할 수도 있지만, 
                # 여기서는 'repositories'라는 이름을 유지하기 위해 교체합니다.
                
                # 기존 스키마 확인 (간단히 PK 정보로 체크하거나, 무조건 교체 시도)
                # 여기서는 간단히 기존 데이터를 보존하며 테이블을 교체하는 로직을 수행합니다.
                c.execute("DROP TABLE repositories")
                c.execute("ALTER TABLE repositories_new RENAME TO repositories")
        except Exception as e:
            # 이미 테이블이 변경되었거나 오류 발생 시 무시 (새 테이블 사용)
            pass

        # 만약 위 과정 없이 처음 실행이라면 바로 생성
        c.execute('''CREATE TABLE IF NOT EXISTS repositories
                     (repo_name TEXT, channel_id INTEGER, added_by TEXT, date TEXT,
                      PRIMARY KEY (repo_name, channel_id))''')

        # 마이그레이션 (다른 테이블 컬럼 추가)
        try: c.execute("ALTER TABLE meetings ADD COLUMN guild_id INTEGER")
        except: pass
        try: c.execute("ALTER TABLE tasks ADD COLUMN source_meeting_id INTEGER")
        except: pass
        
        conn.commit()
        conn.close()

    # --- Users (기존 동일) ---
    def add_user(self, user_id, username, role="user"):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        try: c.execute("INSERT INTO users VALUES (?,?,?,?)", (user_id, username, role, datetime.datetime.now().strftime("%Y-%m-%d"))); conn.commit(); return True
        except: return False
        finally: conn.close()
    def remove_user(self, uid): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("DELETE FROM users WHERE user_id=?",(uid,)); u=c.rowcount>0; conn.commit(); conn.close(); return u
    def is_authorized(self, uid): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("SELECT role FROM users WHERE user_id=?",(uid,)); r=c.fetchone(); conn.close(); return r is not None

    # --- Meetings (기존 동일) ---
    def save_meeting(self, gid, name, cid, smry, url):
        conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("INSERT INTO meetings (guild_id,name,date,channel_id,summary,jump_url) VALUES (?,?,?,?,?,?)",(gid,name,datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),cid,smry,url)); mid=c.lastrowid; conn.commit(); conn.close(); return mid
    def delete_meeting(self, mid, gid): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("DELETE FROM meetings WHERE id=? AND guild_id=?",(mid,gid)); u=c.rowcount>0; conn.commit(); conn.close(); return u
    def get_recent_meetings(self, gid, lim=5): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("SELECT id,name,date,summary,jump_url FROM meetings WHERE guild_id=? ORDER BY id DESC LIMIT ?", (gid,lim)); r=c.fetchall(); conn.close(); return r
    def get_meeting_detail(self, mid, gid): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("SELECT name,date,summary,jump_url FROM meetings WHERE id=? AND guild_id=?",(mid,gid)); r=c.fetchone(); conn.close(); return r

    # --- [변경] Repositories (다중 채널 지원) ---
    def add_repo(self, repo_name, channel_id, added_by):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        try:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            # [변경] INSERT OR REPLACE -> INSERT OR IGNORE (중복 시 무시, 다른 채널이면 추가됨)
            c.execute("INSERT OR IGNORE INTO repositories (repo_name, channel_id, added_by, date) VALUES (?, ?, ?, ?)",
                      (repo_name, channel_id, added_by, date_str))
            conn.commit()
            return True
        except Exception as e:
            print(f"DB Error: {e}")
            return False
        finally:
            conn.close()

    def remove_repo(self, repo_name, channel_id):
        """[변경] 특정 채널에서의 연결만 해제"""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("DELETE FROM repositories WHERE repo_name = ? AND channel_id = ?", (repo_name, channel_id))
        deleted = c.rowcount > 0
        conn.commit()
        conn.close()
        return deleted

    def get_repo_channels(self, repo_name):
        """[변경] 해당 레포가 연결된 모든 채널 ID 리스트 반환"""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT channel_id FROM repositories WHERE repo_name = ?", (repo_name,))
        rows = c.fetchall()
        conn.close()
        return [row[0] for row in rows] # List of IDs

    def get_all_repos(self):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT repo_name, channel_id FROM repositories")
        rows = c.fetchall()
        conn.close()
        return rows

    # --- Tasks (기존 동일) ---
    def add_task(self, p, c, sm_id=None): conn=sqlite3.connect(self.db_name); cur=conn.cursor(); cur.execute("INSERT INTO tasks (project_name,content,status,created_at,source_meeting_id) VALUES (?,?,'TODO',?,?)",(p,c,datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),sm_id)); tid=cur.lastrowid; conn.commit(); conn.close(); return tid
    def get_tasks(self, p=None):
        conn=sqlite3.connect(self.db_name); cur=conn.cursor()
        if p: cur.execute("SELECT * FROM tasks WHERE project_name=? ORDER BY task_id",(p,))
        else: cur.execute("SELECT * FROM tasks ORDER BY task_id")
        r=cur.fetchall(); conn.close(); return r
    def update_task_status(self, tid, s): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("UPDATE tasks SET status=? WHERE task_id=?",(s,tid)); u=c.rowcount>0; conn.commit(); conn.close(); return u
    def assign_task(self, tid, aid, an): conn=sqlite3.connect(self.db_name); c=conn.cursor(); c.execute("UPDATE tasks SET assignee_id=?, assignee_name=? WHERE task_id=?",(aid,an,tid)); u=c.rowcount>0; conn.commit(); conn.close(); return u