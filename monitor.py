import sys, os, subprocess, re, sqlite3, json
from datetime import datetime
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QObject, Signal, QTimer, QUrl, Slot
from PySide6.QtQuickControls2 import QQuickStyle

# Use Fusion for Arch Linux stability and KDE color matching
QQuickStyle.setStyle("Fusion")

class Bridge(QObject):
    liveSpeedUpdated = Signal(list)
    historyDataReady = Signal(list, str, str)
    globalTotalsReady = Signal(str, str)
    deviceListReady = Signal(list)

    def __init__(self):
        super().__init__()
        self.db_path = os.path.join(os.path.dirname(__file__), "network_logs.db")
        self.last_seen_raw = {} 
        self.pattern = re.compile(r"│\s*(\d+\.\d+\.\d+\.\d+)\s*│\s*[\da-f:]+\s*│\s*([^│]*?)\s*│\s*[^│]*?\s*│\s*([\d\.]+\s\wB)\s*│\s*([\d\.]+\s\wB)")
        self.unit_map = {"B": 1, "kB": 1024, "MB": 1048576, "GB": 1073741824}
        self.init_db()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_stats)
        # SPEED FIX: Doubled the polling rate to every 1 second (1000ms)
        self.timer.start(1000)

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute('''CREATE TABLE IF NOT EXISTS totals (ip TEXT PRIMARY KEY, name TEXT, rcvd_total INTEGER, sent_total INTEGER)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS hourly_logs (ip TEXT, rcvd_delta INTEGER, sent_delta INTEGER, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS aliases (ip TEXT PRIMARY KEY, nickname TEXT)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
        conn.commit()
        conn.close()

    @Slot(str, result=str)
    def get_setting(self, key):
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = cur.fetchone()
            conn.close()
            return str(row[0]) if row else ("1.0" if key == "uiScale" else "System")
        except:
            return "1.0"

    @Slot(str, str)
    def save_setting(self, key, value):
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()

    @Slot()
    def get_device_list(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT ip, nickname FROM aliases UNION SELECT ip, name FROM totals")
        rows = cur.fetchall()
        conn.close()
        seen = set()
        devices = [{"ip": "all", "name": "All Devices"}]
        for r in rows:
            if r[0] not in seen and r[0]:
                devices.append({"ip": r[0], "name": r[1] or r[0]})
                seen.add(r[0])
        self.deviceListReady.emit(devices)

    @Slot()
    def clear_database(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM hourly_logs")
        conn.execute("UPDATE totals SET rcvd_total=0, sent_total=0")
        conn.commit()
        conn.close()

    @Slot(str, str)
    def set_nickname(self, ip, nickname):
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT OR REPLACE INTO aliases (ip, nickname) VALUES (?, ?)", (ip, nickname))
        conn.commit()
        conn.close()
        self.get_device_list()

    def format_bytes(self, size_bytes):
        if size_bytes == 0: return "0 B"
        for unit in ['B', 'kB', 'MB', 'GB']:
            if size_bytes < 1024.0: return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} TB"

    def parse_to_bytes(self, size_str):
        parts = size_str.split()
        if len(parts) == 2:
            num, unit = float(parts[0]), parts[1]
            return int(num * self.unit_map.get(unit, 1))
        return 0

    def update_stats(self):
        try:
            with open('/sys/class/net/enp7s0/statistics/rx_bytes', 'r') as f:
                sys_rx = int(f.read().strip())
            with open('/sys/class/net/enp7s0/statistics/tx_bytes', 'r') as f:
                sys_tx = int(f.read().strip())

            if "SYS_NET" not in self.last_seen_raw:
                self.last_seen_raw["SYS_NET"] = {'r': sys_rx, 's': sys_tx}
                sys_dr, sys_ds = 0, 0
            else:
                sys_dr = max(0, sys_rx - self.last_seen_raw["SYS_NET"]['r'])
                sys_ds = max(0, sys_tx - self.last_seen_raw["SYS_NET"]['s'])
                self.last_seen_raw["SYS_NET"] = {'r': sys_rx, 's': sys_tx}

            # SPEED FIX: Tighter journalctl window (2s) to match the new 1s timer
            cmd = ["journalctl", "-u", "tv-monitor.service", "--since", "-2s", "--no-pager"]
            raw = subprocess.check_output(cmd).decode('utf-8')
            clean = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', raw)
            all_matches = self.pattern.findall(clean)

            sum_dn, sum_up = 0, 0
            spoofed_r_total, spoofed_s_total = 0, 0

            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("BEGIN TRANSACTION")

            for ip, b_name, sent, rcvd in reversed(all_matches):
                if ip != "192.168.1.1" and ip != "192.168.1.12":
                    name = b_name.strip() if b_name else f"Unknown ({ip})"
                    r_raw, s_raw = self.parse_to_bytes(rcvd), self.parse_to_bytes(sent)
                    if ip in self.last_seen_raw:
                        dr = max(0, r_raw - self.last_seen_raw[ip]['r'])
                        ds = max(0, s_raw - self.last_seen_raw[ip]['s'])
                        
                        spoofed_r_total += dr
                        spoofed_s_total += ds

                        cur.execute("INSERT INTO hourly_logs (ip, rcvd_delta, sent_delta) VALUES (?, ?, ?)", (ip, dr, ds))
                        cur.execute('''INSERT INTO totals (ip, name, rcvd_total, sent_total) 
                                       VALUES (?, ?, ?, ?) ON CONFLICT(ip) DO UPDATE SET 
                                       rcvd_total = rcvd_total + ?, sent_total = sent_total + ?, name = ?''', 
                                       (ip, name, dr, ds, dr, ds, name))
                        sum_dn += dr
                        sum_up += ds
                    self.last_seen_raw[ip] = {'r': r_raw, 's': s_raw}

            spoofed_combined = spoofed_r_total + spoofed_s_total
            
            laptop_dr = max(0, sys_dr - spoofed_combined)
            laptop_ds = max(0, sys_ds - spoofed_combined)

            if laptop_dr > 0 or laptop_ds > 0:
                laptop_ip = "192.168.1.12"
                laptop_name = "Arch Laptop"
                cur.execute("INSERT INTO hourly_logs (ip, rcvd_delta, sent_delta) VALUES (?, ?, ?)", (laptop_ip, laptop_dr, laptop_ds))
                cur.execute('''INSERT INTO totals (ip, name, rcvd_total, sent_total) 
                               VALUES (?, ?, ?, ?) ON CONFLICT(ip) DO UPDATE SET 
                               rcvd_total = rcvd_total + ?, sent_total = sent_total + ?, name = ?''', 
                               (laptop_ip, laptop_name, laptop_dr, laptop_ds, laptop_dr, laptop_ds, laptop_name))
                sum_dn += laptop_dr
                sum_up += laptop_ds

            cur.execute("COMMIT")
            conn.close()
            self.globalTotalsReady.emit(self.format_bytes(sum_up), self.format_bytes(sum_dn))
        except Exception as e: print(f"Logic Error: {e}")

    @Slot(str, str, str)
    def fetch_history(self, time_range, view_mode, ip_filter):
        time_map = {"Last Hour": "timestamp > datetime('now', '-1 hour')", "Last Day": "timestamp > datetime('now', '-24 hours')", "Last Month": "timestamp > datetime('now', '-30 days')", "Lifetime": "1=1"}
        local_ts = "datetime(timestamp, 'localtime')"
        fmt = "%Y-%m-%d %H:00" if time_range == "Last Hour" else "%Y-%m-%d" if time_range == "Last Day" else "%Y-%m"
        ip_sql = f"AND ip = '{ip_filter}'" if ip_filter != "all" else ""
        
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            final_data = []
            total_dn_all, total_up_all = 0, 0
            
            if view_mode == "Group by Date":
                sql_periods = f"SELECT DISTINCT strftime('{fmt}', {local_ts}) as p FROM hourly_logs WHERE {time_map[time_range]} {ip_sql} ORDER BY p DESC"
                cur.execute(sql_periods)
                for p in cur.fetchall():
                    period_str = p[0]
                    sql_items = f"SELECT ip, SUM(rcvd_delta) as d, SUM(sent_delta) as u, (SELECT COALESCE((SELECT nickname FROM aliases WHERE ip=hourly_logs.ip), (SELECT name FROM totals WHERE ip=hourly_logs.ip))) FROM hourly_logs WHERE strftime('{fmt}', {local_ts}) = ? {ip_sql} GROUP BY ip ORDER BY d DESC"
                    cur.execute(sql_items, (period_str,))
                    sub_items = []
                    pdn, pup = 0, 0
                    for si in cur.fetchall():
                        pdn += si[1]; pup += si[2]
                        sub_items.append({"label": si[3] or si[0], "ip": si[0], "val": f"↓ {self.format_bytes(si[1])}  ↑ {self.format_bytes(si[2])}"})
                    total_dn_all += pdn; total_up_all += pup
                    final_data.append({"header": period_str, "ip": "none", "total": f"DN: {self.format_bytes(pdn)}", "items": sub_items})
            else:
                sql_devices = f"SELECT DISTINCT ip, (SELECT COALESCE((SELECT nickname FROM aliases WHERE ip=hourly_logs.ip), (SELECT name FROM totals WHERE ip=hourly_logs.ip))) FROM hourly_logs WHERE {time_map[time_range]} {ip_sql}"
                cur.execute(sql_devices)
                for dev in cur.fetchall():
                    ip_val, name_val = dev[0], dev[1]
                    sql_items = f"SELECT strftime('{fmt}', {local_ts}) as p, SUM(rcvd_delta) as d, SUM(sent_delta) as u FROM hourly_logs WHERE ip = ? AND {time_map[time_range]} GROUP BY p ORDER BY p DESC"
                    cur.execute(sql_items, (ip_val,))
                    sub_items = []
                    ddn, dup = 0, 0
                    for si in cur.fetchall():
                        ddn += si[1]; dup += si[2]
                        sub_items.append({"label": si[0], "ip": ip_val, "val": f"↓ {self.format_bytes(si[1])}  ↑ {self.format_bytes(si[2])}"})
                    total_dn_all += ddn; total_up_all += dup
                    final_data.append({"header": name_val or ip_val, "ip": ip_val, "total": f"DN: {self.format_bytes(ddn)}", "items": sub_items})

            conn.close()
            self.historyDataReady.emit(final_data, self.format_bytes(total_up_all), self.format_bytes(total_dn_all))
        except Exception as e: print(f"History Error: {e}")

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
app = QGuiApplication(sys.argv)
engine = QQmlApplicationEngine()
bridge = Bridge()
engine.rootContext().setContextProperty("con", bridge)
engine.load(QUrl.fromLocalFile(os.path.join(CURRENT_DIR, "main.qml")))
sys.exit(app.exec())
