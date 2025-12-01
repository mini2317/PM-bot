import sqlite3

class SettingsMixin:
    def create_settings_table(self):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS guild_settings
                     (guild_id INTEGER PRIMARY KEY, dashboard_channel_id INTEGER, dashboard_message_id INTEGER)''')
        conn.commit(); conn.close()

    def set_dashboard(self, guild_id, channel_id, message_id):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO guild_settings VALUES (?, ?, ?)", (guild_id, channel_id, message_id))
        conn.commit(); conn.close()

    def get_dashboard_settings(self, guild_id):
        conn = sqlite3.connect(self.db_name); c = conn.cursor()
        c.execute("SELECT dashboard_channel_id, dashboard_message_id FROM guild_settings WHERE guild_id=?", (guild_id,))
        res = c.fetchone(); conn.close(); return res