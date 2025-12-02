import sqlite3
import datetime
import json

class MemoryService:
    def __init__(self, db_name="memory.db"):
        self.db_name = db_name
        self.init_db()

    def init_db(self):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        # 벡터 DB 대신 간단한 텍스트 검색용 테이블 생성
        c.execute('''CREATE TABLE IF NOT EXISTS memories
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      guild_id INTEGER,
                      text TEXT,
                      metadata TEXT,
                      created_at TEXT)''')
        conn.commit()
        conn.close()

    def add_memory(self, text, metadata=None, guild_id=None):
        """기억 저장"""
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else "{}"
        created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        c.execute("INSERT INTO memories (guild_id, text, metadata, created_at) VALUES (?, ?, ?, ?)",
                  (guild_id, text, meta_json, created_at))
        conn.commit()
        conn.close()

    def query_relevant(self, query, guild_id, limit=3):
        """
        관련 기억 검색 (간이 RAG)
        - 실제 임베딩 벡터 검색 대신, 쿼리 키워드가 포함된 최근 기억을 가져옵니다.
        """
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        
        # 간단한 키워드 매칭 (공백으로 단어 분리)
        keywords = query.split()
        if not keywords:
            return []

        # SQL라이트 LIKE 검색 조건 생성
        conditions = []
        params = [guild_id]
        for word in keywords:
            if len(word) > 1: # 2글자 이상만 검색
                conditions.append("text LIKE ?")
                params.append(f"%{word}%")
        
        if not conditions:
            # 키워드가 없으면 그냥 최근거 가져옴
            sql = "SELECT text FROM memories WHERE guild_id=? ORDER BY id DESC LIMIT ?"
            params.append(limit)
        else:
            # 키워드 중 하나라도 포함된 기억 검색
            sql = f"SELECT text FROM memories WHERE guild_id=? AND ({' OR '.join(conditions)}) ORDER BY id DESC LIMIT ?"
            params.append(limit)

        c.execute(sql, tuple(params))
        rows = c.fetchall()
        conn.close()
        
        return [r[0] for r in rows]