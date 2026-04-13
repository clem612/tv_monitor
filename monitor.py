import sys, os, subprocess, re, sqlite3, json, argparse
from datetime import datetime
from PySide6.QtGui import QGuiApplication, QPalette
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtCore import QObject, Signal, QTimer, QUrl, Slot
from PySide6.QtQuickControls2 import QQuickStyle

parser = argparse.ArgumentParser()
parser.add_argument("--debug", action="store_true", help="Enable terminal logging")
args = parser.parse_known_args()[0]

def log(msg):
    if args.debug:
        print(f"[DEBUG {datetime.now().strftime('%H:%M:%S')}] {msg}")

QQuickStyle.setStyle("Fusion")

class Bridge(QObject):
    historyDataReady = Signal(list, str, str)
    globalTotalsReady = Signal(str, str)
    deviceListReady = Signal(list)

    def __init__(self):
        super().__init__()
        self.db_path = os.path.join(os.path.dirname(__file__), "network_logs.db")
        self.last_seen_raw = {} 
        self.pattern = re.compile(r"│\s*(\d+\.\d+\.\d+\.\d+)\s*│\s*[\da-f:]+\s*│\s*([^│]*?)\s*│\s*[^│]*?\s*│\s*([\d\.]+\s\wB)\s*│\s*([\d\.]+\s\wB)")
        self.unit_map = {"B": 1, "kB": 1024, "MB": 1048576, "GB": 1073741824}
        self.active_range, self.active_mode, self.active_ip = "Last Hour", "Group by Date", "all"
        
        # SMOOTHING LOGIC: A buffer to average out the laptop's ghost spikes
        self.laptop_buffer = {"r": [0,0,0], "s": [0,0,0]}
        self.NOISE_THRESHOLD = 2048 # Ignore anything under 2KB/s for the host laptop
        
        self.init_db()
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_stats)
        self.timer.start(1000)

    @Slot(result=dict)
    def get_theme_colors(self):
        pal = QGuiApplication.palette()
        return {
            "window": pal.color(QPalette.Window).name(),
            "text": pal.color(QPalette.WindowText).name(),
            "base": pal.color(QPalette.Base).name(),
            "highlight": pal.color(QPalette.Highlight).name(),
            "mid": pal.color(QPalette.Mid).name()
        }

    @Slot(str, str, str)
    def set_active_filters(self, t_range, mode, ip):
        self.active_range, self.active_mode, self.active_ip = t_range, mode, ip
        self.fetch_history(t_range, mode, ip)

    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS totals (ip TEXT PRIMARY KEY, name TEXT, rcvd_total INTEGER, sent_total INTEGER)")
        conn.execute("CREATE TABLE IF NOT EXISTS hourly_logs (ip TEXT, rcvd_delta INTEGER, sent_delta INTEGER, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS aliases (ip TEXT PRIMARY KEY, nickname TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON hourly_logs (timestamp)")
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
        except: return "1.0"

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
        devices = [{"ip": "all", "name": "All Devices"}]
        seen = set()
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
                sys_dr, sys_ds = max(0, sys_rx - self.last_seen_raw["SYS_NET"]['r']), max(0, sys_tx - self.last_seen_raw["SYS_NET"]['s'])
                self.last_seen_raw["SYS_NET"] = {'r': sys_rx, 's': sys_tx}

            cmd = ["journalctl", "-u", "tv-monitor.service", "--since", "-2s", "--no-pager"]
            raw = subprocess.check_output(cmd).decode('utf-8')
            clean = re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', raw)
            all_matches = self.pattern.findall(clean)

            sum_dn, sum_up = 0, 0
            spoofed_r, spoofed_s = 0, 0

            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("BEGIN TRANSACTION")

            for ip, b_name, sent, rcvd in reversed(all_matches):
                if ip != "192.168.1.1" and ip != "192.168.1.12":
                    name = b_name.strip() if b_name else f"Unknown ({ip})"
                    r_raw, s_raw = self.parse_to_bytes(rcvd), self.parse_to_bytes(sent)
                    if ip in self.last_seen_raw:
                        dr, ds = max(0, r_raw - self.last_seen_raw[ip]['r']), max(0, s_raw - self.last_seen_raw[ip]['s'])
                        spoofed_r += dr; spoofed_s += ds
                        cur.execute("INSERT INTO hourly_logs (ip, rcvd_delta, sent_delta) VALUES (?, ?, ?)", (ip, dr, ds))
                        cur.execute("INSERT INTO totals (ip, name, rcvd_total, sent_total) VALUES (?, ?, ?, ?) ON CONFLICT(ip) DO UPDATE SET rcvd_total = rcvd_total + ?, sent_total = sent_total + ?, name = ?", (ip, name, dr, ds, dr, ds, name))
                        sum_dn += dr; sum_up += ds
                    self.last_seen_raw[ip] = {'r': r_raw, 's': s_raw}

            # CALIBRATED MATH: Subtract spoofed traffic and apply noise filter
            raw_l_dr = max(0, sys_dr - (spoofed_r + spoofed_s))
            raw_l_ds = max(0, sys_ds - (spoofed_r + spoofed_s))
            
            # Update buffers for smoothing
            self.laptop_buffer["r"].pop(0); self.laptop_buffer["r"].append(raw_l_dr)
            self.laptop_buffer["s"].pop(0); self.laptop_buffer["s"].append(raw_l_ds)
            
            # Calculate Smoothed Average
            avg_l_dr = sum(self.laptop_buffer["r"]) // len(self.laptop_buffer["r"])
            avg_l_ds = sum(self.laptop_buffer["s"]) // len(self.laptop_buffer["s"])

            # Apply Noise Threshold (hide background ARP noise)
            l_dr = avg_l_dr if avg_l_dr > self.NOISE_THRESHOLD else 0
            l_ds = avg_l_ds if avg_l_ds > self.NOISE_THRESHOLD else 0

            if l_dr > 0 or l_ds > 0:
                l_ip, l_name = "192.168.1.12", "Arch Laptop"
                cur.execute("INSERT INTO hourly_logs (ip, rcvd_delta, sent_delta) VALUES (?, ?, ?)", (l_ip, l_dr, l_ds))
                cur.execute("INSERT INTO totals (ip, name, rcvd_total, sent_total) VALUES (?, ?, ?, ?) ON CONFLICT(ip) DO UPDATE SET rcvd_total = rcvd_total + ?, sent_total = sent_total + ?, name = ?", (l_ip, l_name, l_dr, l_ds, l_dr, l_ds, l_name))
                sum_dn += l_dr; sum_up += l_ds

            cur.execute("COMMIT")
            conn.close()
            
            self.globalTotalsReady.emit(self.format_bytes(sum_up), self.format_bytes(sum_dn))
            self.fetch_history(self.active_range, self.active_mode, self.active_ip)
            
        except Exception as e: log(f"CRITICAL ERROR: {e}")

    @Slot(str, str, str)
    def fetch_history(self, time_range, view_mode, ip_filter):
        local_ts = "datetime(timestamp, 'localtime')"
        if time_range == "Last Hour":
            time_sql, fmt = "timestamp > datetime('now', '-1 hour')", "%Y-%m-%d %H:00"
        elif time_range == "Today":
            time_sql, fmt = "date(timestamp, 'localtime') = date('now', 'localtime')", "%Y-%m-%d %H:00"
        elif time_range == "This Month":
            time_sql, fmt = "strftime('%Y-%m', timestamp, 'localtime') = strftime('%Y-%m', 'now', 'localtime')", "%Y-%m-%d"
        else:
            time_sql, fmt = "1=1", "%Y-%m"
            
        ip_sql = f"AND ip = '{ip_filter}'" if ip_filter != "all" else ""
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            final_data, total_dn_all, total_up_all = [], 0, 0
            if view_mode == "Group by Date":
                cur.execute(f"SELECT DISTINCT strftime('{fmt}', {local_ts}) as p FROM hourly_logs WHERE {time_sql} {ip_sql} ORDER BY p DESC")
                for p in cur.fetchall():
                    cur.execute(f"SELECT ip, SUM(rcvd_delta), SUM(sent_delta), (SELECT COALESCE((SELECT nickname FROM aliases WHERE ip=hourly_logs.ip), (SELECT name FROM totals WHERE ip=hourly_logs.ip))) FROM hourly_logs WHERE strftime('{fmt}', {local_ts}) = ? {ip_sql} GROUP BY ip ORDER BY SUM(rcvd_delta) DESC", (p[0],))
                    sub, pdn, pup = [], 0, 0
                    for si in cur.fetchall():
                        pdn += si[1]; pup += si[2]
                        sub.append({"label": si[3] or si[0], "ip": si[0], "val": f"↓ {self.format_bytes(si[1])}  ↑ {self.format_bytes(si[2])}"})
                    total_dn_all += pdn; total_up_all += pup
                    final_data.append({"header": p[0], "ip": "none", "total": f"DN: {self.format_bytes(pdn)}", "items": sub})
            else:
                cur.execute(f"SELECT DISTINCT ip, (SELECT COALESCE((SELECT nickname FROM aliases WHERE ip=hourly_logs.ip), (SELECT name FROM totals WHERE ip=hourly_logs.ip))) FROM hourly_logs WHERE {time_sql} {ip_sql}")
                for dev in cur.fetchall():
                    cur.execute(f"SELECT strftime('{fmt}', {local_ts}) as p, SUM(rcvd_delta), SUM(sent_delta) FROM hourly_logs WHERE ip = ? AND {time_sql} GROUP BY p ORDER BY p DESC", (dev[0],))
                    sub, ddn, dup = [], 0, 0
                    for si in cur.fetchall():
                        ddn += si[1]; dup += si[2]
                        sub.append({"label": si[0], "ip": dev[0], "val": f"↓ {self.format_bytes(si[1])}  ↑ {self.format_bytes(si[2])}"})
                    total_dn_all += ddn; total_up_all += dup
                    final_data.append({"header": dev[1] or dev[0], "ip": dev[0], "total": f"DN: {self.format_bytes(ddn)}", "items": sub})
            conn.close()
            self.historyDataReady.emit(final_data, self.format_bytes(total_up_all), self.format_bytes(total_dn_all))
        except Exception as e: log(f"ERROR: {e}")

if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    bridge = Bridge()
    engine.rootContext().setContextProperty("con", bridge)
    engine.load(QUrl.fromLocalFile(os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.qml")))
    sys.exit(app.exec())
