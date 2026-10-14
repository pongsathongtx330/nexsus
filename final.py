import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import pydeck as pdk
import sqlite3
from datetime import datetime
import time

try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except ImportError:
    HAS_AUTOREFRESH = False

# สร้าง State สำหรับควบคุมสถานะการรันเวลา (NORMAL, FAST, STOPPED)
if "sim_state" not in st.session_state:
    st.session_state.sim_state = "NORMAL"

# ================= 1. ตั้งค่าหน้าเพจและ Cyberpunk Theme =================
st.set_page_config(
    page_title="NEXUS v5.0: Enterprise Digital Twin",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp { background-color: #0b1120; color: #f8fafc; }
    [data-testid="stSidebar"] { background-color: #111827 !important; border-right: 1px solid #1e293b; }
    [data-testid="stSidebar"] * { color: #f8fafc !important; }
    h1, h2, h3 { color: #00f0ff; font-family: 'Consolas', 'Courier New', monospace; text-shadow: 0px 0px 10px rgba(0, 240, 255, 0.35); }
    div[data-testid="stMetric"] {
        background: linear-gradient(145deg, #1e293b, #0f172a);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.4);
    }
    div[data-testid="stMetricValue"] { color: #00f0ff; font-family: 'Consolas', monospace; font-weight: bold; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #1e293b; border-radius: 8px 8px 0px 0px;
        padding: 12px 24px; color: #94a3b8; border: 1px solid #334155; border-bottom: none;
    }
    .stTabs [aria-selected="true"] {
        background-color: #0f172a !important; border-top: 3px solid #00f0ff;
        color: #ffffff !important; font-weight: bold; box-shadow: 0px -4px 12px rgba(0, 240, 255, 0.15);
    }
    .stChatMessage { background-color: #1e293b; border-radius: 10px; padding: 12px; border: 1px solid #334155; margin-bottom: 8px; }
    .stChatMessage, .stChatMessage * { color: #f8fafc !important; }
    .stButton > button {
        background-color: #0f172a !important; color: #00f0ff !important;
        border: 1px solid #00f0ff !important; border-radius: 8px; font-weight: 600; transition: all 0.25s ease;
    }
    .stButton > button:hover {
        background-color: #00f0ff !important; color: #0f172a !important;
        box-shadow: 0px 0px 12px rgba(0, 240, 255, 0.7); transform: translateY(-1px);
    }
    button[data-testid="baseButton-primary"] {
        background-color: #ef4444 !important; color: white !important; border: 1px solid #dc2626 !important;
    }
    button[data-testid="baseButton-primary"]:hover {
        background-color: #dc2626 !important; box-shadow: 0px 0px 12px rgba(239, 68, 68, 0.7) !important;
    }
    .stTextInput > div > div > input { background-color: #1e293b; color: #f8fafc; border: 1px solid #334155; }
    [data-testid="stDataFrame"] { background-color: #1e293b; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

if HAS_AUTOREFRESH:
    if st.session_state.sim_state == "FAST":
        st_autorefresh(interval=2500, limit=None, key="factory_refresh_fast")
    elif st.session_state.sim_state == "NORMAL":
        st_autorefresh(interval=60000, limit=None, key="factory_refresh_normal")

# ================= 2. ค่าคงที่และสมมติฐานทางการเงิน =================
DB_FILE = "nexus_factory_v5.db"
FACTORY_CENTER = [100.6870, 13.6425]
SIMULATION_INTERVAL_SEC = 55

PROFIT_PER_MINUTE = 83.33
COST_SAFE_PAUSE = 15 * PROFIT_PER_MINUTE
COST_SWAP = 5 * PROFIT_PER_MINUTE
COST_MICRO_SLOWDOWN = 1.5 * PROFIT_PER_MINUTE

# ================= 3. ระบบจัดการฐานข้อมูล SQLite =================
def init_db():
    with sqlite3.connect(DB_FILE, timeout=15) as conn:
        c = conn.cursor()

        c.execute("PRAGMA table_info(active_workers)")
        worker_cols = [col[1] for col in c.fetchall()]
        c.execute("PRAGMA table_info(kpi_logs)")
        log_cols = [col[1] for col in c.fetchall()]

        if (worker_cols and "efficiency" not in worker_cols) or (log_cols and "oee_snapshot" not in log_cols):
            c.execute("DROP TABLE IF EXISTS active_workers")
            c.execute("DROP TABLE IF EXISTS standby_pool")
            c.execute("DROP TABLE IF EXISTS kpi_logs")
            conn.commit()

        c.execute("""CREATE TABLE IF NOT EXISTS active_workers (
                        worker_id TEXT PRIMARY KEY, name TEXT, role TEXT, zone TEXT,
                        bpm INTEGER, hrv INTEGER, temp_c REAL, fatigue INTEGER,
                        machine_risk INTEGER, efficiency REAL, lon REAL, lat REAL,
                        status TEXT, last_update REAL)""")

        c.execute("""CREATE TABLE IF NOT EXISTS standby_pool (
                        worker_id TEXT PRIMARY KEY, name TEXT, role TEXT, shift TEXT,
                        fatigue INTEGER, status TEXT, last_update REAL)""")

        c.execute("""CREATE TABLE IF NOT EXISTS kpi_logs (
                        log_id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT,
                        name TEXT, role TEXT, fatigue INTEGER, event_type TEXT,
                        detail TEXT, cost_lost_thb REAL, oee_snapshot REAL)""")

        c.execute("SELECT COUNT(*) FROM active_workers")
        if c.fetchone()[0] == 0:
            np.random.seed(42)
            current_time = time.time()
            active_names = [
                "สมชาย", "วิชัย", "มานพ", "ประเสริฐ", "สุชาติ", "อำนาจ", "ธนากร", "นพดล",
                "นิพนธ์", "ศุภชัย", "วีระ", "บรรจง", "สมศักดิ์", "เอกราช", "อรรถพล", "เกรียงไกร",
                "ธีรภัทร", "ชาญชัย", "ยุทธนา", "วสันต์", "พีระพล", "อนันต์", "ทักษิณ", "ทรงพล"
            ]
            roles = ["Forklift", "CNC", "Welding", "Packaging", "Quality Control", "Lifter", "Assembly", "Supervisor"]
            zones = ["Zone A (Heavy)", "Zone B (Machining)", "Zone C (Thermal)", "Zone D (Logistics)"]
            risk_map = {"Forklift": 8, "CNC": 9, "Welding": 9, "Packaging": 3, "Quality Control": 2, "Lifter": 7, "Assembly": 5, "Supervisor": 2}

            active_data = []
            for i, name in enumerate(active_names):
                role = roles[i % len(roles)]
                zone = zones[i % len(zones)]
                fatigue = int(np.random.randint(15, 58))
                bpm = int(70 + (fatigue * 0.45) + np.random.randint(-5, 6))
                hrv = int(max(15, 95 - (fatigue * 0.75) + np.random.randint(-5, 6)))
                temp_c = round(36.4 + (fatigue * 0.012) + np.random.uniform(-0.1, 0.15), 1)
                eff = round(max(60.0, 100.0 - max(0, fatigue - 50) * 0.6), 1)
                status = "CRITICAL" if fatigue >= 80 else ("WARNING" if fatigue >= 60 else "OPTIMAL")

                row_idx, col_idx = divmod(i, 6)
                lon = FACTORY_CENTER[0] - 0.0009 + (col_idx * 0.00036) + np.random.uniform(-0.00004, 0.00004)
                lat = FACTORY_CENTER[1] - 0.0006 + (row_idx * 0.00038) + np.random.uniform(-0.00004, 0.00004)

                active_data.append((
                    f"W-{i+1:03d}", name, role, zone, bpm, hrv, temp_c, fatigue,
                    risk_map[role], eff, lon, lat, status, current_time
                ))

            standby_names = [
                "กฤษดา", "จิรายุ", "ณัฐพล", "ทวีศักดิ์", "พงศกร", "สุรพล", "วงศ์กร", "รุ่งโรจน์",
                "อนุชา", "พิทักษ์", "นที", "ชัยวัฒน์", "สมพร", "นิคม", "อุดม", "สุเมธ"
            ]
            standby_data = []
            for i, name in enumerate(standby_names):
                role = roles[i % len(roles)]
                fatigue_sb = int(np.random.randint(15, 55))
                status_sb = "Standby" if fatigue_sb <= 35 else "Resting"
                standby_data.append((f"W-{i+25:03d}", name, role, "Reserve Shift", fatigue_sb, status_sb, current_time))

            c.executemany("INSERT INTO active_workers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", active_data)
            c.executemany("INSERT INTO standby_pool VALUES (?,?,?,?,?,?,?)", standby_data)

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute(
                "INSERT INTO kpi_logs (timestamp, name, role, fatigue, event_type, detail, cost_lost_thb, oee_snapshot) VALUES (?,?,?,?,?,?,?,?)",
                (timestamp, "SYSTEM", "ALL", 0, "SYSTEM_START", "Initialized NEXUS v5.0 Digital Twin Engine", 0.0, 96.5)
            )
        conn.commit()

def reset_database():
    with sqlite3.connect(DB_FILE, timeout=15) as conn:
        c = conn.cursor()
        c.execute("DROP TABLE IF EXISTS active_workers")
        c.execute("DROP TABLE IF EXISTS standby_pool")
        c.execute("DROP TABLE IF EXISTS kpi_logs")
        conn.commit()
    init_db()

# ================= 4. ระบบจำลองเวลาและชีวมาตรอัตโนมัติ =================
def calculate_current_oee(conn):
    c = conn.cursor()
    c.execute("SELECT status, efficiency FROM active_workers")
    rows = c.fetchall()
    if not rows:
        return 100.0
    availability = (sum(1 for r in rows if r[0] != "PAUSED") / len(rows)) * 100.0
    performance = sum(r[1] for r in rows) / len(rows)
    quality = max(88.0, 100.0 - (sum(1 for r in rows if r[0] == "CRITICAL") * 1.8))
    return round((availability * performance * quality) / 10000.0, 2)

def simulate_time_passing(force=False):
    current_time = time.time()
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with sqlite3.connect(DB_FILE, timeout=15) as conn:
        c = conn.cursor()
        c.execute("SELECT MIN(last_update) FROM active_workers")
        min_last_update = c.fetchone()[0]

        if not force and min_last_update and (current_time - min_last_update < SIMULATION_INTERVAL_SEC):
            return

        current_oee = calculate_current_oee(conn)

        c.execute("SELECT worker_id, name, role, fatigue, status FROM active_workers")
        for worker_id, name, role, fatigue, old_status in c.fetchall():
            if old_status == "PAUSED":
                new_fatigue = max(20, int(fatigue - np.random.randint(15, 25)))
                new_status = "OPTIMAL" if new_fatigue < 55 else "PAUSED"
                if new_status == "OPTIMAL":
                    c.execute(
                        "INSERT INTO kpi_logs (timestamp, name, role, fatigue, event_type, detail, cost_lost_thb, oee_snapshot) VALUES (?,?,?,?,?,?,?,?)",
                        (timestamp_str, name, role, new_fatigue, "MACHINE_RESUMED", "Safe Pause completed, station back online", 0.0, current_oee)
                    )
            else:
                new_fatigue = min(99, int(fatigue + np.random.randint(2, 6)))
                new_status = "CRITICAL" if new_fatigue >= 80 else ("WARNING" if new_fatigue >= 60 else "OPTIMAL")

            new_bpm = int(70 + (new_fatigue * 0.55) + np.random.randint(-4, 6))
            new_hrv = int(max(12, 95 - (new_fatigue * 0.78) + np.random.randint(-4, 5)))
            new_temp = round(36.4 + (new_fatigue * 0.015) + np.random.uniform(-0.1, 0.15), 1)
            new_eff = 0.0 if new_status == "PAUSED" else round(max(55.0, 100.0 - max(0, new_fatigue - 50) * 0.75), 1)

            if new_status != old_status and new_status in ["WARNING", "CRITICAL"]:
                c.execute(
                    "INSERT INTO kpi_logs (timestamp, name, role, fatigue, event_type, detail, cost_lost_thb, oee_snapshot) VALUES (?,?,?,?,?,?,?,?)",
                    (timestamp_str, name, role, new_fatigue, "STATUS_DEGRADE", f"Escalated from {old_status} to {new_status}", 0.0, current_oee)
                )
            elif new_status == "CRITICAL" and old_status == "CRITICAL":
                c.execute(
                    "INSERT INTO kpi_logs (timestamp, name, role, fatigue, event_type, detail, cost_lost_thb, oee_snapshot) VALUES (?,?,?,?,?,?,?,?)",
                    (timestamp_str, name, role, new_fatigue, "FATIGUE_SLOWDOWN", "Severe fatigue causing cycle time loss", COST_MICRO_SLOWDOWN, current_oee)
                )

            c.execute(
                "UPDATE active_workers SET fatigue=?, bpm=?, hrv=?, temp_c=?, efficiency=?, status=?, last_update=? WHERE worker_id=?",
                (new_fatigue, new_bpm, new_hrv, new_temp, new_eff, new_status, current_time, worker_id)
            )

        c.execute("SELECT worker_id, name, role, fatigue, status FROM standby_pool")
        for worker_id, name, role, fatigue, old_status in c.fetchall():
            new_fatigue = max(5, int(fatigue - np.random.randint(4, 9)))
            new_status = "Standby" if new_fatigue <= 35 else "Resting"

            if new_status == "Standby" and old_status == "Resting":
                c.execute(
                    "INSERT INTO kpi_logs (timestamp, name, role, fatigue, event_type, detail, cost_lost_thb, oee_snapshot) VALUES (?,?,?,?,?,?,?,?)",
                    (timestamp_str, name, role, new_fatigue, "READY_FOR_WORK", "Recovered and ready in Standby Pool", 0.0, current_oee)
                )

            c.execute(
                "UPDATE standby_pool SET fatigue=?, status=?, last_update=? WHERE worker_id=?",
                (new_fatigue, new_status, current_time, worker_id)
            )

        conn.commit()

def inject_crisis_simulation():
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_FILE, timeout=15) as conn:
        c = conn.cursor()
        c.execute("SELECT worker_id, name, role FROM active_workers WHERE status != 'CRITICAL' ORDER BY RANDOM() LIMIT 3")
        targets = c.fetchall()
        oee = calculate_current_oee(conn)
        for w_id, name, role in targets:
            f_val = int(np.random.randint(84, 96))
            c.execute(
                "UPDATE active_workers SET fatigue=?, bpm=?, hrv=?, temp_c=?, efficiency=?, status='CRITICAL' WHERE worker_id=?",
                (f_val, int(np.random.randint(125, 148)), int(np.random.randint(15, 25)), 37.9, 62.0, w_id)
            )
            c.execute(
                "INSERT INTO kpi_logs (timestamp, name, role, fatigue, event_type, detail, cost_lost_thb, oee_snapshot) VALUES (?,?,?,?,?,?,?,?)",
                (timestamp_str, name, role, f_val, "STATUS_DEGRADE", "Simulated Sudden Heat/Fatigue Spike", 0.0, oee)
            )
        conn.commit()

# ================= 5. ฟังก์ชันปฏิบัติการ =================
def fetch_all_data():
    with sqlite3.connect(DB_FILE, timeout=15) as conn:
        active = pd.read_sql_query("SELECT * FROM active_workers", conn)
        standby = pd.read_sql_query("SELECT * FROM standby_pool", conn)
        logs = pd.read_sql_query("SELECT * FROM kpi_logs ORDER BY log_id DESC", conn)
    return active, standby, logs

def execute_worker_swap(tired_name, fresh_name):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_FILE, timeout=15) as conn:
        c = conn.cursor()
        oee = calculate_current_oee(conn)
        
        c.execute("SELECT worker_id, name, role, fatigue FROM active_workers WHERE name=?", (tired_name,))
        tired = c.fetchone()
        c.execute("SELECT worker_id, name, role, fatigue FROM standby_pool WHERE name=?", (fresh_name,))
        fresh = c.fetchone()

        if tired and fresh:
            t_id, t_name, t_role, t_fat = tired
            f_id, f_name, f_role, f_fat = fresh
            new_bpm = int(70 + f_fat * 0.4)
            new_hrv = int(95 - f_fat * 0.7)

            c.execute(
                "UPDATE active_workers SET worker_id=?, name=?, fatigue=?, bpm=?, hrv=?, temp_c=36.6, efficiency=98.5, status='OPTIMAL' WHERE name=?",
                (f_id, f_name, f_fat, new_bpm, new_hrv, t_name)
            )
            c.execute(
                "UPDATE standby_pool SET worker_id=?, name=?, role=?, fatigue=?, status='Resting' WHERE name=?",
                (t_id, t_name, t_role, t_fat, f_name)
            )

            c.execute(
                "INSERT INTO kpi_logs (timestamp, name, role, fatigue, event_type, detail, cost_lost_thb, oee_snapshot) VALUES (?,?,?,?,?,?,?,?)",
                (timestamp, t_name, t_role, t_fat, "SWAP_OUT", f"Replaced by {f_name} at station ({t_role})", COST_SWAP, oee)
            )
            c.execute(
                "INSERT INTO kpi_logs (timestamp, name, role, fatigue, event_type, detail, cost_lost_thb, oee_snapshot) VALUES (?,?,?,?,?,?,?,?)",
                (timestamp, f_name, t_role, f_fat, "SWAP_IN", f"Took over {t_role} station from {t_name}", 0.0, oee)
            )
            conn.commit()
            return True
    return False

def trigger_safe_pause(name, worker_id, role, fatigue):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_FILE, timeout=15) as conn:
        c = conn.cursor()
        oee = calculate_current_oee(conn)
        
        c.execute("UPDATE active_workers SET status='PAUSED', efficiency=0.0, bpm=80 WHERE worker_id=?", (worker_id,))
        c.execute(
            "INSERT INTO kpi_logs (timestamp, name, role, fatigue, event_type, detail, cost_lost_thb, oee_snapshot) VALUES (?,?,?,?,?,?,?,?)",
            (timestamp, name, role, fatigue, "SAFE_PAUSE_TRIGGERED", "Emergency Interlock Activated (15m Cooling)", COST_SAFE_PAUSE, oee)
        )
        conn.commit()

init_db()

if st.session_state.sim_state == "FAST":
    simulate_time_passing(force=True)
elif st.session_state.sim_state == "NORMAL":
    simulate_time_passing(force=False)

workers_data, standby_pool, logs_data = fetch_all_data()

# ================= 6. SIDEBAR: COMMAND =================
with st.sidebar:
    st.markdown("<h2 style='text-align: center;'>NEXUS CONTROL</h2>", unsafe_allow_html=True)
    st.caption("<p style='text-align: center;'>Enterprise Digital Twin v5.0</p>", unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("### Simulation Controls")

    if st.session_state.sim_state == "FAST":
        if st.button("กลับสู่ความเร็วปกติ (Pause Fast-Run)", use_container_width=True):
            st.session_state.sim_state = "NORMAL"
            st.rerun()
    elif st.session_state.sim_state == "NORMAL":
        if st.button("เร่งเวลาจำลองต่อเนื่อง (Start Fast-Run)", use_container_width=True, type="primary"):
            st.session_state.sim_state = "FAST"
            st.rerun()
    elif st.session_state.sim_state == "STOPPED":
        st.info("ระบบถูกหยุดการจำลองชั่วคราวแล้ว")

    if st.button("กดข้ามเวลา 1 รอบ (+1 Step)", use_container_width=True):
        simulate_time_passing(force=True)
        st.rerun()

    if st.button("จำลองวิกฤต (Inject 3 Criticals)", use_container_width=True):
        inject_crisis_simulation()
        st.toast("จำลองเหตุฉุกเฉิน: พนักงาน 3 คนเข้าสู่สภาวะวิกฤต!")
        st.rerun()

    st.markdown("---")
    st.markdown("### ตัวกรองพื้นที่ (Zone Filter)")
    selected_zones = st.multiselect(
        "เลือกโซนที่ต้องการแสดงผล:",
        options=workers_data["zone"].unique().tolist(),
        default=workers_data["zone"].unique().tolist()
    )

    st.markdown("---")
    st.markdown("### Database Admin")
    if st.button("รีเซ็ตระบบทั้งหมด (Factory Reset)", use_container_width=True, type="primary"):
        reset_database()
        st.session_state.pop("chat_history", None)
        st.session_state.sim_state = "NORMAL"
        st.toast("ล้างฐานข้อมูลและรีเซ็ตระบบเรียบร้อย!")
        st.rerun()
        
    if st.session_state.sim_state != "STOPPED":
        if st.button("หยุดการจำลองทั้งหมด (Stop System)", use_container_width=True):
            st.session_state.sim_state = "STOPPED"
            st.toast("หยุดระบบทั้งหมดแล้ว หน้าจอจะไม่รีเฟรชอัตโนมัติ")
            st.rerun()
    else:
        if st.button("กลับสู่โหมดปกติ (Resume System)", use_container_width=True):
            st.session_state.sim_state = "NORMAL"
            st.toast("กลับสู่การจำลองปกติ (อัปเดตทุก 1 นาที)")
            st.rerun()

if selected_zones:
    filtered_workers = workers_data[workers_data["zone"].isin(selected_zones)].copy()
else:
    filtered_workers = workers_data.copy()

# ================= 7. EXECUTIVE OEE & FINANCIAL RIBBON =================
st.title("NEXUS: DIGITAL TWIN FACTORY")
st.markdown("*Real-Time Biometric Telemetry, Autonomous Interlock & Financial OEE Analytics*")

total_cost_lost = logs_data["cost_lost_thb"].sum() if not logs_data.empty else 0.0
swap_cost = logs_data[logs_data["event_type"] == "SWAP_OUT"]["cost_lost_thb"].sum() if not logs_data.empty else 0.0
pause_cost = logs_data[logs_data["event_type"] == "SAFE_PAUSE_TRIGGERED"]["cost_lost_thb"].sum() if not logs_data.empty else 0.0
slowdown_cost = logs_data[logs_data["event_type"] == "FATIGUE_SLOWDOWN"]["cost_lost_thb"].sum() if not logs_data.empty else 0.0

availability_pct = (len(workers_data[workers_data["status"] != "PAUSED"]) / len(workers_data)) * 100.0
performance_pct = workers_data["efficiency"].mean()
quality_pct = max(88.0, 100.0 - (len(workers_data[workers_data["status"] == "CRITICAL"]) * 1.8))
live_oee = (availability_pct * performance_pct * quality_pct) / 10000.0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Live Factory OEE", f"{live_oee:.1f}%", f"A:{availability_pct:.0f}% P:{performance_pct:.0f}% Q:{quality_pct:.0f}%")
k2.metric("Total Financial Loss", f"฿ {total_cost_lost:,.2f}", f"Slowdown: ฿{slowdown_cost:,.0f}", delta_color="inverse")
k3.metric("Shift Swap Costs", f"฿ {swap_cost:,.2f}", f"{int(swap_cost // COST_SWAP)} ครั้งที่สลับกะ", delta_color="inverse")
k4.metric("Machine Downtime Loss", f"฿ {pause_cost:,.2f}", f"{int(pause_cost // COST_SAFE_PAUSE)} ครั้งที่เบรกฉุกเฉิน", delta_color="inverse")
k5.metric("Ready Standby Pool", f"{len(standby_pool[standby_pool['status'] == 'Standby'])} / {len(standby_pool)} คน", "พร้อมสลับตัวทันที")

st.markdown("---")

# ================= 8. TABS โครงสร้างหลัก =================
tab1, tab2, tab3, tab4 = st.tabs([
    "1. 3D DIGITAL TWIN",
    "2. BIOMETRIC TELEMETRY",
    "3. SMART SHIFT MANAGER",
    "4. OEE & FINANCIAL LEDGER"
])

# ----------------- TAB 1: 3D DIGITAL TWIN MAP -----------------
with tab1:
    col_map, col_stat = st.columns([2.1, 1])

    with col_map:
        color_map = {
            "CRITICAL": [255, 45, 85, 235],
            "WARNING": [255, 195, 0, 235],
            "OPTIMAL": [16, 185, 129, 235],
            "PAUSED": [56, 189, 248, 220]
        }
        filtered_workers["Color"] = filtered_workers["status"].map(color_map)
        filtered_workers["elevation_height"] = filtered_workers["fatigue"] * 1.2

        factory_bounds = pd.DataFrame([{
            "polygon": [
                [FACTORY_CENTER[0] - 0.0013, FACTORY_CENTER[1] - 0.0009],
                [FACTORY_CENTER[0] + 0.0013, FACTORY_CENTER[1] - 0.0009],
                [FACTORY_CENTER[0] + 0.0013, FACTORY_CENTER[1] + 0.0009],
                [FACTORY_CENTER[0] - 0.0013, FACTORY_CENTER[1] + 0.0009]
            ]
        }])

        poly_layer = pdk.Layer(
            "PolygonLayer",
            data=factory_bounds,
            get_polygon="polygon",
            get_fill_color=[15, 23, 42, 140],
            get_line_color=[0, 240, 255, 180],
            line_width_min_pixels=2,
            pickable=False
        )

        crit_df = filtered_workers[filtered_workers["status"] == "CRITICAL"]
        hazard_layer = pdk.Layer(
            "ScatterplotLayer",
            data=crit_df,
            get_position=["lon", "lat"],
            get_fill_color=[255, 45, 85, 70],
            get_line_color=[255, 45, 85, 255],
            get_radius=16,
            stroked=True,
            line_width_min_pixels=2
        )

        column_layer = pdk.Layer(
            "ColumnLayer",
            data=filtered_workers,
            get_position=["lon", "lat"],
            get_elevation="elevation_height",
            elevation_scale=1.5,
            radius=4.5,
            get_fill_color="Color",
            pickable=True,
            auto_highlight=True
        )

        view_state = pdk.ViewState(
            longitude=FACTORY_CENTER[0],
            latitude=FACTORY_CENTER[1],
            zoom=17.2,
            pitch=55,
            bearing=15
        )

        deck = pdk.Deck(
            layers=[poly_layer, hazard_layer, column_layer],
            initial_view_state=view_state,
            map_style="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
            tooltip={
                "html": """
                <div style='font-family: Consolas, monospace; padding: 4px;'>
                    <b style='color:#00f0ff; font-size:14px;'>{name} ({worker_id})</b><br/>
                    <span>ตำแหน่ง: <b>{role}</b> | {zone}</span><br/>
                    <span>สถานะ: <b>{status}</b> | ความล้า: <b>{fatigue}%</b></span><br/>
                    <span>BPM: <b>{bpm}</b> | HRV: <b>{hrv} ms</b> | อุณหภูมิ: <b>{temp_c}°C</b></span><br/>
                    <span>ประสิทธิภาพเครื่อง: <b>{efficiency}%</b></span>
                </div>
                """
            }
        )
        st.pydeck_chart(deck, use_container_width=True)
        st.caption("คำอธิบายพิกัด 3D: ความสูงของแท่งแสดงระดับความล้า (Fatigue) | สีแดง = วิกฤต | สีเหลือง = เฝ้าระวัง | สีเขียว = ปกติ | สีฟ้า = หยุดพักเครื่อง")

    with col_stat:
        st.subheader(f"LIVE ACTION CENTER ({datetime.now().strftime('%H:%M:%S')})")
        critical_workers = filtered_workers[filtered_workers["status"] == "CRITICAL"].sort_values(by="fatigue", ascending=False)
        ready_standby = standby_pool[standby_pool["status"] == "Standby"].sort_values(by="fatigue", ascending=True)

        if not critical_workers.empty:
            st.error(f"พบพนักงานเสี่ยงวิกฤต {len(critical_workers)} คน! กรุณาตัดสินใจเลือกมาตรการด้านล่าง:")
            for _, row in critical_workers.iterrows():
                with st.expander(f"{row['name']} ({row['role']}) — ความล้า {row['fatigue']}%", expanded=True):
                    st.markdown(
                        f"**โซน:** `{row['zone']}` | **ความเสี่ยงเครื่องจักร:** `{row['machine_risk']}/10`  \n"
                        f"**ชีพจร:** `{row['bpm']} BPM` | **HRV:** `{row['hrv']} ms` | **อุณหภูมิ:** `{row['temp_c']} °C`"
                    )
                    b_col1, b_col2 = st.columns(2)
                    with b_col1:
                        if st.button("Safe Pause (฿1,250)", key=f"pause_{row['worker_id']}", use_container_width=True, type="primary"):
                            trigger_safe_pause(row["name"], row["worker_id"], row["role"], int(row["fatigue"]))
                            st.toast(f"สั่งหยุดเครื่องของ {row['name']} ชั่วคราวเรียบร้อย!")
                            time.sleep(0.5)
                            st.rerun()
                    with b_col2:
                        if not ready_standby.empty:
                            same_role = ready_standby[ready_standby["role"] == row["role"]]
                            if not same_role.empty:
                                best_sub = same_role.iloc[0]
                                if st.button(f"สลับ {best_sub['name']} (฿417)", key=f"autoswap_{row['worker_id']}", use_container_width=True):
                                    execute_worker_swap(row["name"], best_sub["name"])
                                    st.toast(f"สลับ {best_sub['name']} เข้าแทนที่ {row['name']} สำเร็จ!")
                                    time.sleep(0.5)
                                    st.rerun()
                            else:
                                st.button("ไม่มีสำรองตำแหน่งนี้", disabled=True, key=f"nosub_{row['worker_id']}", use_container_width=True)
                        else:
                            st.button("ไม่มีคนสำรองพร้อม", disabled=True, key=f"nosub_{row['worker_id']}", use_container_width=True)
        else:
            st.success("พื้นที่การผลิตทั้งหมดอยู่ในเกณฑ์ปลอดภัย ไม่พบพนักงานในสภาวะวิกฤต")

        paused_workers = filtered_workers[filtered_workers["status"] == "PAUSED"]
        if not paused_workers.empty:
            st.info(f"เครื่องจักรที่กำลังอยู่ในโหมดพักฟื้น (Safe Pause): {len(paused_workers)} สถานี")
            for _, prow in paused_workers.iterrows():
                st.caption(f"• **{prow['name']}** ({prow['role']}) — ความล้าลดลงเหลือ **{prow['fatigue']}%**")

# ----------------- TAB 2: BIOMETRIC TELEMETRY -----------------
with tab2:
    st.subheader("DEEP BIOMETRIC TELEMETRY & FATIGUE FORECAST")
    col_sel1, col_sel2 = st.columns([1, 2])
    with col_sel1:
        worker_sel = st.selectbox(
            "เลือกพนักงานเพื่อตรวจวิเคราะห์สัญญาณชีพเชิงลึก:",
            options=workers_data["name"].tolist(),
            format_func=lambda x: f"{x} ({workers_data[workers_data['name']==x]['role'].values[0]} - Fatigue: {workers_data[workers_data['name']==x]['fatigue'].values[0]}%)"
        )
    w_data = workers_data[workers_data["name"] == worker_sel].iloc[0]

    with col_sel2:
        remaining_fatigue = max(0, 80 - int(w_data["fatigue"]))
        est_minutes_left = int(remaining_fatigue * 14)
        st.info(
            f"**รหัสพนักงาน:** `{w_data['worker_id']}` | **สถานี:** `{w_data['role']}` ({w_data['zone']}) | "
            f"**เวลาทำงานปลอดภัยคงเหลือ (Estimated Safe Time):** `~{est_minutes_left} นาที`"
        )

    g1, g2, g3, g4 = st.columns(4)

    def make_gauge(val, title, max_val, bar_color, min_val=0):
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=val,
            title={"text": title, "font": {"color": "#e2e8f0", "size": 15}},
            gauge={
                "axis": {"range": [min_val, max_val], "tickcolor": "#64748b"},
                "bar": {"color": bar_color},
                "bgcolor": "#1e293b",
                "bordercolor": "#334155"
            }
        ))
        fig.update_layout(height=230, margin=dict(l=20, r=20, t=45, b=15), paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#f8fafc"))
        return fig

    g1.plotly_chart(make_gauge(w_data["bpm"], "Heart Rate (BPM)", 180, "#00f0ff", 50), use_container_width=True)
    g2.plotly_chart(make_gauge(w_data["hrv"], "HRV Readiness (ms)", 100, "#a855f7", 0), use_container_width=True)
    g3.plotly_chart(make_gauge(w_data["temp_c"], "Skin Temp (°C)", 39.5, "#f59e0b", 35.5), use_container_width=True)
    g4.plotly_chart(make_gauge(w_data["fatigue"], "Fatigue Index (%)", 100, "#ef4444" if w_data["fatigue"] >= 80 else "#10b981", 0), use_container_width=True)

    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        st.markdown("#### การพยากรณ์ความล้าล่วงหน้า (60-Min Fatigue Trajectory)")
        future_mins = np.arange(0, 65, 10)
        projected_fatigue = [min(100, w_data["fatigue"] + (m * 0.38)) for m in future_mins]
        if_swap_fatigue = [w_data["fatigue"]] + [max(15, 25 + ((m - 10) * 0.25)) for m in future_mins[1:]]

        fig_proj = go.Figure()
        fig_proj.add_trace(go.Scatter(x=future_mins, y=projected_fatigue, mode="lines+markers", name="กรณีทำงานต่อ (No Action)", line=dict(color="#ef4444", width=3)))
        fig_proj.add_trace(go.Scatter(x=future_mins, y=if_swap_fatigue, mode="lines+markers", name="กรณีสลับกะทันที (Smart Swap)", line=dict(color="#10b981", width=3, dash="dot")))
        fig_proj.add_hline(y=80, line_dash="dash", line_color="#ff3366", annotation_text="Critical Threshold (80%)")
        fig_proj.update_layout(
            height=300, xaxis_title="เวลาข้างหน้า (นาที)", yaxis_title="ระดับความล้า (%)",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(30,41,59,0.4)", font=dict(color="#f8fafc"),
            margin=dict(l=20, r=20, t=20, b=20), legend=dict(orientation="h", y=1.12, font=dict(color="#f8fafc"))
        )
        st.plotly_chart(fig_proj, use_container_width=True, theme=None)

    with chart_col2:
        st.markdown("#### สมดุลสมรรถนะรายบุคคล (Biometric Radar)")
        categories = ["ความตื่นตัว (Alertness)", "ความพร้อม HRV", "ประสิทธิภาพงาน (Efficiency)", "ความปลอดภัยสถานี", "ความทนทานความร้อน"]
        r_values = [
            100 - w_data["fatigue"],
            w_data["hrv"],
            w_data["efficiency"],
            (10 - w_data["machine_risk"]) * 10,
            max(10, min(100, (38.5 - w_data["temp_c"]) * 45))
        ]
        fig_radar = go.Figure(data=go.Scatterpolar(
            r=r_values + [r_values[0]],
            theta=categories + [categories[0]],
            fill="toself",
            fillcolor="rgba(0, 240, 255, 0.25)",
            line=dict(color="#00f0ff", width=2)
        ))
        fig_radar.update_layout(
            polar=dict(
                bgcolor="rgba(30,41,59,0.5)",
                radialaxis=dict(visible=True, range=[0, 100], gridcolor="#334155")
            ),
            showlegend=False, height=300,
            paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#f8fafc"),
            margin=dict(l=40, r=40, t=30, b=20)
        )
        st.plotly_chart(fig_radar, use_container_width=True, theme=None)

# ----------------- TAB 3: SMART SHIFT MANAGER -----------------
with tab3:
    st.subheader("DATABASE SHIFT MANAGER & WORKFORCE ALLOCATION")
    c_active, c_standby = st.columns(2)

    with c_active:
        st.markdown(f"#### Active Shift ({len(workers_data)} คน)")
        st.dataframe(
            workers_data[["worker_id", "name", "role", "zone", "bpm", "fatigue", "efficiency", "status"]].sort_values(by="fatigue", ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={
                "fatigue": st.column_config.ProgressColumn("ความล้า (%)", min_value=0, max_value=100, format="%d%%"),
                "efficiency": st.column_config.NumberColumn("ประสิทธิภาพ", format="%.1f%%"),
                "bpm": st.column_config.NumberColumn("BPM", format="%d")
            }
        )

    with c_standby:
        st.markdown(f"#### Standby Pool ({len(standby_pool)} คน)")
        st.dataframe(
            standby_pool[["worker_id", "name", "role", "shift", "fatigue", "status"]].sort_values(by="fatigue", ascending=True),
            use_container_width=True,
            hide_index=True,
            column_config={
                "fatigue": st.column_config.ProgressColumn("ความล้าสะสม (%)", min_value=0, max_value=100, format="%d%%")
            }
        )

    st.markdown("---")
    st.markdown("### Manual Swap Allocation (จัดการสลับตัวรายบุคคล)")
    st.caption(f"ต้นทุนเวลาสูญเปล่าในการส่งมอบงานหน้าเครื่อง (Swap Handover Cost): ฿{COST_SWAP:,.2f} / ครั้ง")

    col_tired, col_fresh, col_exec = st.columns(3)
    sorted_active = workers_data.sort_values(by="fatigue", ascending=False)
    fresh_candidates = standby_pool[standby_pool["status"] == "Standby"].sort_values(by="fatigue", ascending=True)

    with col_tired:
        sel_tired = st.selectbox(
            "1. เลือกพนักงานหน้างานที่ต้องการให้พัก:",
            options=sorted_active["name"].tolist(),
            format_func=lambda n: f"{n} ({workers_data[workers_data['name']==n]['role'].values[0]} - ล้า {workers_data[workers_data['name']==n]['fatigue'].values[0]}%)",
            key="manual_swap_tired"
        )
        
    target_role = workers_data[workers_data['name'] == sel_tired]['role'].values[0]

    with col_fresh:
        matching_fresh_candidates = fresh_candidates[fresh_candidates['role'] == target_role]
        fresh_list = matching_fresh_candidates["name"].tolist()
        
        sel_fresh = st.selectbox(
            f"2. เลือกพนักงานสำรอง (กรองเฉพาะตำแหน่ง {target_role}):",
            options=fresh_list if fresh_list else ["ไม่มีพนักงานตำแหน่งนี้ที่พร้อมทำงาน..."],
            format_func=lambda n: f"{n} ({standby_pool[standby_pool['name']==n]['role'].values[0]} - ล้า {standby_pool[standby_pool['name']==n]['fatigue'].values[0]}%)" if n in fresh_list else n,
            key="manual_swap_fresh"
        )
        
    with col_exec:
        st.write("")
        st.write("")
        if fresh_list:
            if st.button("ยืนยันการสลับกะเดี่ยว", key="manual_swap_btn", use_container_width=True):
                execute_worker_swap(sel_tired, sel_fresh)
                st.toast(f"สลับ {sel_fresh} เข้าเสียบตำแหน่ง {target_role} แทน {sel_tired} เรียบร้อย!")
                time.sleep(0.5)
                st.rerun()
        else:
            st.button("ไม่มีสำรองตำแหน่งนี้", disabled=True, use_container_width=True)

# ----------------- TAB 4: KPI & FINANCIAL LOGS -----------------
with tab4:
    st.subheader("PERMANENT DATABASE ANALYTICS (OEE & FINANCIAL LEDGER)")

    c_chart1, c_chart2 = st.columns(2)
    with c_chart1:
        st.markdown("#### สัดส่วนมูลค่าความสูญเสียตามประเภทเหตุการณ์")
        cost_events = logs_data[logs_data["cost_lost_thb"] > 0]
        if not cost_events.empty:
            kpi_costs = cost_events.groupby("event_type")["cost_lost_thb"].sum().reset_index()
            fig_pie = px.pie(
                kpi_costs, values="cost_lost_thb", names="event_type", hole=0.45,
                color_discrete_sequence=["#ef4444", "#00f0ff", "#f59e0b", "#a855f7"]
            )
            fig_pie.update_layout(
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#f8fafc"),
                legend=dict(font=dict(color="#f8fafc")), # บังคับเปลี่ยนสีตัวอักษรในส่วนอธิบายสัญลักษณ์เป็นสีสว่าง
                height=320, margin=dict(l=20, r=20, t=20, b=20)
            )
            st.plotly_chart(fig_pie, use_container_width=True, theme=None)
        else:
            st.info("ยังไม่มีความสูญเสียทางการเงินเกิดขึ้นในระบบ (Zero Financial Loss)")

    with c_chart2:
        st.markdown("#### แนวโน้มความสูญเสียสะสม (Cumulative Financial Loss)")
        logs_chron = logs_data.sort_values(by="log_id", ascending=True).copy()
        logs_chron["cumulative_cost"] = logs_chron["cost_lost_thb"].cumsum()

        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(
            x=logs_chron["timestamp"], y=logs_chron["cumulative_cost"],
            mode="lines+markers", name="ความสูญเสียสะสม (บาท)",
            fill="tozeroy", line=dict(color="#ff3366", width=2.5)
        ))
        fig_trend.update_layout(
            height=320, xaxis_title="เวลา", yaxis_title="บาท (THB)",
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(30,41,59,0.4)",
            font=dict(color="#f8fafc"),
            legend=dict(font=dict(color="#f8fafc")), # บังคับเปลี่ยนสีตัวอักษรในส่วนอธิบายสัญลักษณ์เป็นสีสว่าง
            margin=dict(l=20, r=20, t=20, b=20)
        )
        st.plotly_chart(fig_trend, use_container_width=True, theme=None)

    st.markdown("#### บันทึกเหตุการณ์ถาวรในฐานข้อมูล (Audit Trail & Financial Ledger)")
    col_dl, _ = st.columns([1, 3])
    with col_dl:
        csv_bytes = logs_data.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="ดาวน์โหลดรายงาน CSV (Export Audit Log)",
            data=csv_bytes,
            file_name=f"nexus_factory_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )

    st.dataframe(
        logs_data,
        use_container_width=True,
        hide_index=True,
        column_config={
            "cost_lost_thb": st.column_config.NumberColumn("มูลค่าความสูญเสีย (THB)", format="฿ %.2f"),
            "oee_snapshot": st.column_config.NumberColumn("OEE ณ ขณะนั้น", format="%.1f%%")
        }
    )