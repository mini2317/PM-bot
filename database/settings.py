import sqlite3

class SettingsMixin:
    def set_dashboard(self, guild_id, channel_id, message_id):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        # 기존 설정 유지하며 업데이트 (비서 채널 ID 보존)
        c.execute("SELECT assistant_channel_id FROM guild_settings WHERE guild_id=?", (guild_id,))
        row = c.fetchone()
        assist_cid = row[0] if row else None
        
        c.execute("INSERT OR REPLACE INTO guild_settings (guild_id, dashboard_channel_id, dashboard_message_id, assistant_channel_id) VALUES (?, ?, ?, ?)", 
                  (guild_id, channel_id, message_id, assist_cid))
        conn.commit(); conn.close()

    def get_dashboard_settings(self, guild_id):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT dashboard_channel_id, dashboard_message_id FROM guild_settings WHERE guild_id=?", (guild_id,))
        res = c.fetchone(); conn.close(); return res

    # [NEW] 비서 채널 설정
    def set_assistant_channel(self, guild_id, channel_id):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        # 기존 대시보드 설정 보존
        c.execute("SELECT dashboard_channel_id, dashboard_message_id FROM guild_settings WHERE guild_id=?", (guild_id,))
        row = c.fetchone()
        dash_cid, dash_mid = (row[0], row[1]) if row else (None, None)
        
        c.execute("INSERT OR REPLACE INTO guild_settings (guild_id, dashboard_channel_id, dashboard_message_id, assistant_channel_id) VALUES (?, ?, ?, ?)", 
                  (guild_id, dash_cid, dash_mid, channel_id))
        conn.commit(); conn.close()

    def get_assistant_channel(self, guild_id):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT assistant_channel_id FROM guild_settings WHERE guild_id=?", (guild_id,))
        res = c.fetchone(); conn.close()
        return res[0] if res else None