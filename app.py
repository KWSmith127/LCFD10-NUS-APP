#!/usr/bin/env python3
"""
Fire Apparatus Inventory Tracker
Tracks Normal Unit Stocking (NUS) for Structural (Type 1/2) and Wildland (Type 3–6) engines.
Includes individual user logins.
"""

import streamlit as st
import pandas as pd
import sqlite3
import bcrypt
from datetime import datetime
from pathlib import Path
from itertools import groupby

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
APP_DIR = Path(__file__).parent
DB_PATH = Path("/tmp/apparatus_inventory.db")
STRUCTURAL_NUS = APP_DIR / "structural_nus.xlsx"
WILDLAND_NUS = APP_DIR / "wildland_nus.xlsx"

TYPE_TO_CATEGORY = {
    "Type 1": "Structural",
    "Type 2": "Structural",
    "Type 3": "Wildland",
    "Type 4": "Wildland",
    "Type 5": "Wildland",
    "Type 6": "Wildland",
}

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def get_conn():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            display_name TEXT NOT NULL,
            password_hash BLOB NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS trucks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            type TEXT NOT NULL,
            station TEXT,
            notes TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            truck_id INTEGER NOT NULL,
            category TEXT,
            item_description TEXT,
            specification TEXT,
            unit TEXT,
            priority TEXT,
            required_qty REAL,
            current_qty REAL DEFAULT 0,
            stock_number TEXT,
            notes TEXT,
            last_checked TEXT,
            last_checked_by TEXT,
            UNIQUE(truck_id, category, item_description, specification),
            FOREIGN KEY (truck_id) REFERENCES trucks(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            truck_id INTEGER,
            message TEXT,
            severity TEXT,
            created_at TEXT,
            acknowledged INTEGER DEFAULT 0,
            acknowledged_by TEXT,
            FOREIGN KEY (truck_id) REFERENCES trucks(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS check_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            truck_id INTEGER,
            checked_by TEXT,
            checked_at TEXT,
            incomplete_count INTEGER,
            notes TEXT,
            FOREIGN KEY (truck_id) REFERENCES trucks(id) ON DELETE CASCADE
        )
    """)

    # Migrations for older DBs
    try:
        c.execute("ALTER TABLE inventory ADD COLUMN last_checked_by TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE notifications ADD COLUMN acknowledged_by TEXT")
    except Exception:
        pass

    # Seed default admin if no users exist
    count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        pw = bcrypt.hashpw(b"admin123", bcrypt.gensalt())
        now = datetime.now().isoformat(timespec="seconds")
        c.execute(
            "INSERT INTO users (username, display_name, password_hash, role, active, created_at) VALUES (?,?,?,?,?,?)",
            ("admin", "Administrator", pw, "admin", 1, now),
        )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())


def check_password(password: str, password_hash: bytes) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash)
    except Exception:
        return False


def authenticate(username: str, password: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM users WHERE username=? AND active=1", (username.strip().lower(),)
    ).fetchone()
    conn.close()
    if row and check_password(password, row["password_hash"]):
        return dict(row)
    return None


def create_user(username, display_name, password, role="user"):
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    try:
        conn.execute(
            "INSERT INTO users (username, display_name, password_hash, role, active, created_at) VALUES (?,?,?,?,?,?)",
            (username.strip().lower(), display_name.strip(), hash_password(password), role, 1, now),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def list_users():
    conn = get_conn()
    rows = conn.execute("SELECT id, username, display_name, role, active, created_at FROM users ORDER BY username").fetchall()
    conn.close()
    return rows


def set_user_active(user_id, active: bool):
    conn = get_conn()
    conn.execute("UPDATE users SET active=? WHERE id=?", (1 if active else 0, user_id))
    conn.commit()
    conn.close()


def change_password(user_id, new_password):
    conn = get_conn()
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), user_id))
    conn.commit()
    conn.close()


def require_login():
    """Return current user dict or show login form and stop."""
    if "user" in st.session_state and st.session_state["user"]:
        return st.session_state["user"]

    st.title("🚒 Apparatus Inventory Tracker")
    st.markdown("Sign in to continue")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign In", type="primary")
        if submitted:
            user = authenticate(username, password)
            if user:
                st.session_state["user"] = {
                    "id": user["id"],
                    "username": user["username"],
                    "display_name": user["display_name"],
                    "role": user["role"],
                }
                st.rerun()
            else:
                st.error("Invalid username or password.")

    st.caption("Default admin login: **admin** / **admin123** — change this after first login.")
    st.stop()


# ---------------------------------------------------------------------------
# Load NUS standards
# ---------------------------------------------------------------------------
@st.cache_data
def load_structural_standard():
    df = pd.read_excel(STRUCTURAL_NUS, header=None)
    header_row = None
    for i, row in df.iterrows():
        if str(row.iloc[0]).strip().lower() == "category":
            header_row = i
            break
    if header_row is None:
        return pd.DataFrame()
    df = pd.read_excel(STRUCTURAL_NUS, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    col_map = {}
    for c in df.columns:
        cl = c.lower()
        if "category" in cl:
            col_map[c] = "Category"
        elif "item description" in cl or cl == "item":
            col_map[c] = "Item Description"
        elif "specification" in cl or "size" in cl:
            col_map[c] = "Specification"
        elif "type 1 qty" in cl:
            col_map[c] = "Type 1 Qty"
        elif "type 2 qty" in cl:
            col_map[c] = "Type 2 Qty"
        elif cl == "unit":
            col_map[c] = "Unit"
        elif "priority" in cl:
            col_map[c] = "Priority"
        elif "notes" in cl:
            col_map[c] = "Notes"
    df = df.rename(columns=col_map)
    if "Specification" not in df.columns and "Specification / Size" in df.columns:
        df = df.rename(columns={"Specification / Size": "Specification"})
    needed = ["Category", "Item Description", "Specification", "Type 1 Qty", "Type 2 Qty", "Unit", "Priority", "Notes"]
    for n in needed:
        if n not in df.columns:
            df[n] = ""
    df = df[needed].dropna(subset=["Item Description"])
    df = df[df["Item Description"].astype(str).str.strip() != ""]
    return df.reset_index(drop=True)


@st.cache_data
def load_wildland_standard():
    df = pd.read_excel(WILDLAND_NUS, sheet_name=0, header=None)
    header_row = None
    for i, row in df.iterrows():
        if str(row.iloc[0]).strip().lower() == "category":
            header_row = i
            break
    if header_row is None:
        return pd.DataFrame()
    df = pd.read_excel(WILDLAND_NUS, sheet_name=0, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    col_map = {}
    for c in df.columns:
        cl = c.lower()
        if "category" in cl:
            col_map[c] = "Category"
        elif "item description" in cl:
            col_map[c] = "Item Description"
        elif "specification" in cl or "size" in cl:
            col_map[c] = "Specification"
        elif "type 3 qty" in cl:
            col_map[c] = "Type 3 Qty"
        elif "type 4 qty" in cl:
            col_map[c] = "Type 4 Qty"
        elif "type 5 qty" in cl:
            col_map[c] = "Type 5 Qty"
        elif "type 6 qty" in cl:
            col_map[c] = "Type 6 Qty"
        elif cl == "unit":
            col_map[c] = "Unit"
        elif "priority" in cl:
            col_map[c] = "Priority"
        elif "notes" in cl:
            col_map[c] = "Notes"
    df = df.rename(columns=col_map)
    if "Specification" not in df.columns and "Specification / Size" in df.columns:
        df = df.rename(columns={"Specification / Size": "Specification"})
    needed = ["Category", "Item Description", "Specification",
              "Type 3 Qty", "Type 4 Qty", "Type 5 Qty", "Type 6 Qty",
              "Unit", "Priority", "Notes"]
    for n in needed:
        if n not in df.columns:
            df[n] = ""
    df = df[needed].dropna(subset=["Item Description"])
    df = df[df["Item Description"].astype(str).str.strip() != ""]
    return df.reset_index(drop=True)


def get_required_qty(row, truck_type):
    key = f"{truck_type} Qty"
    if key in row and pd.notna(row[key]):
        try:
            return float(row[key])
        except (ValueError, TypeError):
            return 0.0
    return 0.0


# ---------------------------------------------------------------------------
# Truck & inventory operations
# ---------------------------------------------------------------------------
def create_truck(name, truck_type, station="", notes=""):
    conn = get_conn()
    c = conn.cursor()
    now = datetime.now().isoformat(timespec="seconds")
    try:
        c.execute(
            "INSERT INTO trucks (name, type, station, notes, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (name.strip(), truck_type, station.strip(), notes.strip(), now, now),
        )
        truck_id = c.lastrowid
        if TYPE_TO_CATEGORY[truck_type] == "Structural":
            std = load_structural_standard()
        else:
            std = load_wildland_standard()
        for _, row in std.iterrows():
            req = get_required_qty(row, truck_type)
            c.execute(
                """INSERT INTO inventory
                   (truck_id, category, item_description, specification, unit, priority,
                    required_qty, current_qty, stock_number, notes, last_checked)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    truck_id,
                    str(row.get("Category", "")),
                    str(row.get("Item Description", "")),
                    str(row.get("Specification", "")),
                    str(row.get("Unit", "")),
                    str(row.get("Priority", "Core")),
                    req,
                    0.0,
                    "",
                    str(row.get("Notes", "")),
                    None,
                ),
            )
        conn.commit()
        c.execute(
            "INSERT INTO notifications (truck_id, message, severity, created_at) VALUES (?,?,?,?)",
            (truck_id, f"New apparatus '{name}' created — inventory is empty and needs to be stocked.", "warning", now),
        )
        conn.commit()
        return truck_id
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def list_trucks():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM trucks ORDER BY name").fetchall()
    conn.close()
    return rows


def get_truck(truck_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM trucks WHERE id=?", (truck_id,)).fetchone()
    conn.close()
    return row


def get_inventory(truck_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM inventory WHERE truck_id=? ORDER BY category, item_description",
        (truck_id,),
    ).fetchall()
    conn.close()
    return rows


def update_item_qty(item_id, current_qty, stock_number=None, checked_by=""):
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    if stock_number is not None:
        conn.execute(
            "UPDATE inventory SET current_qty=?, stock_number=?, last_checked=?, last_checked_by=? WHERE id=?",
            (current_qty, stock_number, now, checked_by, item_id),
        )
    else:
        conn.execute(
            "UPDATE inventory SET current_qty=?, last_checked=?, last_checked_by=? WHERE id=?",
            (current_qty, now, checked_by, item_id),
        )
    truck_id = conn.execute("SELECT truck_id FROM inventory WHERE id=?", (item_id,)).fetchone()[0]
    conn.execute("UPDATE trucks SET updated_at=? WHERE id=?", (now, truck_id))
    conn.commit()
    conn.close()


def bulk_update_qty(truck_id, updates: dict, checked_by=""):
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    for item_id, qty in updates.items():
        conn.execute(
            "UPDATE inventory SET current_qty=?, last_checked=?, last_checked_by=? WHERE id=? AND truck_id=?",
            (qty, now, checked_by, item_id, truck_id),
        )
    conn.execute("UPDATE trucks SET updated_at=? WHERE id=?", (now, truck_id))
    conn.commit()
    conn.close()


def mark_all_full(truck_id, checked_by=""):
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "UPDATE inventory SET current_qty=required_qty, last_checked=?, last_checked_by=? WHERE truck_id=?",
        (now, checked_by, truck_id),
    )
    conn.execute("UPDATE trucks SET updated_at=? WHERE id=?", (now, truck_id))
    conn.commit()
    conn.close()


def compute_status(inventory_rows):
    total = len(inventory_rows)
    incomplete = 0
    missing_core = 0
    for r in inventory_rows:
        req = r["required_qty"] or 0
        cur = r["current_qty"] or 0
        if cur < req:
            incomplete += 1
            if (r["priority"] or "").lower() == "core":
                missing_core += 1
    return {
        "total": total,
        "incomplete": incomplete,
        "complete": total - incomplete,
        "missing_core": missing_core,
        "pct_complete": round(100 * (total - incomplete) / total, 1) if total else 100.0,
    }


def log_check(truck_id, checked_by, incomplete_count, notes=""):
    conn = get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO check_log (truck_id, checked_by, checked_at, incomplete_count, notes) VALUES (?,?,?,?,?)",
        (truck_id, checked_by, now, incomplete_count, notes),
    )
    truck = conn.execute("SELECT name FROM trucks WHERE id=?", (truck_id,)).fetchone()
    name = truck["name"] if truck else f"ID {truck_id}"
    if incomplete_count > 0:
        msg = f"Inventory check on '{name}' by {checked_by}: {incomplete_count} item(s) below required quantity."
        sev = "warning" if incomplete_count < 10 else "critical"
    else:
        msg = f"Inventory check on '{name}' by {checked_by}: all items complete."
        sev = "info"
    conn.execute(
        "INSERT INTO notifications (truck_id, message, severity, created_at) VALUES (?,?,?,?)",
        (truck_id, msg, sev, now),
    )
    conn.commit()
    conn.close()


def get_notifications(unack_only=True, limit=50):
    conn = get_conn()
    if unack_only:
        rows = conn.execute(
            """SELECT n.*, t.name as truck_name FROM notifications n
               LEFT JOIN trucks t ON n.truck_id = t.id
               WHERE n.acknowledged=0 ORDER BY n.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT n.*, t.name as truck_name FROM notifications n
               LEFT JOIN trucks t ON n.truck_id = t.id
               ORDER BY n.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    conn.close()
    return rows


def acknowledge_notification(notif_id, by=""):
    conn = get_conn()
    conn.execute(
        "UPDATE notifications SET acknowledged=1, acknowledged_by=? WHERE id=?",
        (by, notif_id),
    )
    conn.commit()
    conn.close()


def acknowledge_all(by=""):
    conn = get_conn()
    conn.execute(
        "UPDATE notifications SET acknowledged=1, acknowledged_by=? WHERE acknowledged=0",
        (by,),
    )
    conn.commit()
    conn.close()


def delete_truck(truck_id):
    conn = get_conn()
    conn.execute("DELETE FROM inventory WHERE truck_id=?", (truck_id,))
    conn.execute("DELETE FROM notifications WHERE truck_id=?", (truck_id,))
    conn.execute("DELETE FROM check_log WHERE truck_id=?", (truck_id,))
    conn.execute("DELETE FROM trucks WHERE id=?", (truck_id,))
    conn.commit()
    conn.close()


def export_truck_inventory(truck_id):
    inv = get_inventory(truck_id)
    truck = get_truck(truck_id)
    rows = []
    for r in inv:
        rows.append({
            "Category": r["category"],
            "Item Description": r["item_description"],
            "Specification": r["specification"],
            "Unit": r["unit"],
            "Priority": r["priority"],
            "Required Qty": r["required_qty"],
            "Current Qty": r["current_qty"],
            "Status": "OK" if (r["current_qty"] or 0) >= (r["required_qty"] or 0) else "INCOMPLETE",
            "Stock #": r["stock_number"] or "",
            "Notes": r["notes"] or "",
            "Last Checked": r["last_checked"] or "",
            "Last Checked By": r["last_checked_by"] or "",
        })
    df = pd.DataFrame(rows)
    return df, truck["name"] if truck else "truck"


# ---------------------------------------------------------------------------
# UI setup
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Main UI (only runs under `streamlit run`)
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(
        page_title="Apparatus Inventory Tracker",
        page_icon="🚒",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_db()

    st.markdown('''
<style>
    div[data-testid="stMetricValue"] { font-size: 1.5rem; }
</style>
''', unsafe_allow_html=True)

    user = require_login()
    display_name = user["display_name"]
    is_admin = user["role"] == "admin"

    # Sidebar
    st.sidebar.title("🚒 Apparatus Inventory")
    st.sidebar.markdown(f"**{display_name}** ({user['role']})")
    if st.sidebar.button("Sign Out"):
        st.session_state.pop("user", None)
        st.rerun()

    nav_items = ["Dashboard", "Manage Trucks", "Truck Inventory", "Notifications", "Standards Reference"]
    if is_admin:
        nav_items.append("User Management")
    page = st.sidebar.radio("Navigation", nav_items, label_visibility="collapsed")

    # ---- DASHBOARD ----
    if page == "Dashboard":
        st.title("Apparatus Inventory Dashboard")
        trucks = list_trucks()
        notifs = get_notifications(unack_only=True)

        if not trucks:
            st.info("No apparatus registered yet. Go to **Manage Trucks** to add your first engine.")
        else:
            total_incomplete = 0
            critical_trucks = []
            complete_trucks = 0
            for t in trucks:
                inv = get_inventory(t["id"])
                status = compute_status(inv)
                total_incomplete += status["incomplete"]
                if status["incomplete"] == 0:
                    complete_trucks += 1
                if status["missing_core"] > 0:
                    critical_trucks.append((t["name"], status["missing_core"]))

            cols = st.columns(4)
            cols[0].metric("Total Apparatus", len(trucks))
            cols[1].metric("Fully Stocked", complete_trucks)
            cols[2].metric("Items Below Standard", total_incomplete)
            cols[3].metric("Open Notifications", len(notifs))

            st.subheader("Apparatus Status")
            status_rows = []
            for t in trucks:
                inv = get_inventory(t["id"])
                s = compute_status(inv)
                status_rows.append({
                    "Name": t["name"],
                    "Type": t["type"],
                    "Station": t["station"] or "—",
                    "Items": s["total"],
                    "Complete": s["complete"],
                    "Incomplete": s["incomplete"],
                    "Core Missing": s["missing_core"],
                    "% Complete": f"{s['pct_complete']}%",
                    "Last Updated": t["updated_at"] or "—",
                })
            st.dataframe(pd.DataFrame(status_rows), use_container_width=True, hide_index=True)

            if critical_trucks:
                st.warning(
                    "The following apparatus have **Core** items below required quantity: "
                    + ", ".join(f"{n} ({c} core)" for n, c in critical_trucks)
                )

            if notifs:
                st.subheader("Recent Unacknowledged Notifications")
                for n in notifs[:8]:
                    sev = n["severity"] or "info"
                    icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(sev, "ℹ️")
                    st.markdown(f"{icon} **{n['truck_name'] or 'System'}** — {n['message']}  \n*{n['created_at']}*")

    # ---- MANAGE TRUCKS ----
    elif page == "Manage Trucks":
        st.title("Manage Apparatus")
        with st.expander("➕ Add New Apparatus", expanded=True):
            with st.form("add_truck"):
                c1, c2 = st.columns(2)
                name = c1.text_input("Apparatus Name / Designator *", placeholder="e.g. Engine 31, Brush 6")
                truck_type = c2.selectbox("Type *", ["Type 1", "Type 2", "Type 3", "Type 4", "Type 5", "Type 6"])
                station = st.text_input("Station / Location", placeholder="e.g. Station 3")
                notes = st.text_area("Notes", height=80)
                submitted = st.form_submit_button("Create Apparatus & Seed Inventory")
                if submitted:
                    if not name.strip():
                        st.error("Name is required.")
                    else:
                        tid = create_truck(name, truck_type, station, notes)
                        if tid:
                            st.success(f"Created **{name}** ({truck_type}) and seeded inventory from NUS standard.")
                            st.rerun()
                        else:
                            st.error(f"An apparatus named '{name}' already exists.")

        st.subheader("Registered Apparatus")
        trucks = list_trucks()
        if not trucks:
            st.info("No apparatus yet.")
        else:
            for t in trucks:
                inv = get_inventory(t["id"])
                s = compute_status(inv)
                col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
                col1.markdown(f"**{t['name']}**  \n{t['type']} · {t['station'] or 'No station'}")
                col2.markdown(f"{s['pct_complete']}% complete  \n{s['incomplete']} incomplete")
                col3.markdown(f"Updated  \n{t['updated_at'] or '—'}")
                if is_admin and col4.button("🗑️ Delete", key=f"del_{t['id']}"):
                    delete_truck(t["id"])
                    st.rerun()
                st.divider()

    # ---- TRUCK INVENTORY ----
    elif page == "Truck Inventory":
        st.title("Truck Inventory Tracker")
        trucks = list_trucks()
        if not trucks:
            st.warning("No apparatus registered. Add one under **Manage Trucks**.")
        else:
            truck_options = {f"{t['name']} ({t['type']})": t["id"] for t in trucks}
            selected_label = st.selectbox("Select Apparatus", list(truck_options.keys()))
            truck_id = truck_options[selected_label]
            truck = get_truck(truck_id)
            inv = get_inventory(truck_id)
            status = compute_status(inv)

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Type", truck["type"])
            m2.metric("% Complete", f"{status['pct_complete']}%")
            m3.metric("Complete", status["complete"])
            m4.metric("Incomplete", status["incomplete"])
            m5.metric("Core Missing", status["missing_core"])

            a1, a2, a3, a4 = st.columns(4)
            with a1:
                if st.button("✅ Mark All Full"):
                    mark_all_full(truck_id, checked_by=display_name)
                    st.success("All items set to required quantity.")
                    st.rerun()
            with a2:
                st.caption(f"Logged in as: **{display_name}**")
            with a3:
                if st.button("📋 Log Inventory Check"):
                    log_check(truck_id, display_name, status["incomplete"])
                    st.success("Check logged. Notification created if items were incomplete.")
                    st.rerun()
            with a4:
                df_export, tname = export_truck_inventory(truck_id)
                csv = df_export.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇️ Export CSV",
                    data=csv,
                    file_name=f"{tname.replace(' ', '_')}_inventory_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                )

            st.divider()

            f1, f2, f3 = st.columns(3)
            categories = sorted(set(r["category"] for r in inv if r["category"]))
            filter_cat = f1.multiselect("Filter Category", categories, default=categories)
            filter_status = f2.selectbox("Status", ["All", "Incomplete only", "Complete only"])
            filter_prio = f3.multiselect("Priority", ["Core", "Recommended", "Optional"], default=["Core", "Recommended", "Optional"])

            rows_to_show = []
            for r in inv:
                if r["category"] not in filter_cat:
                    continue
                if (r["priority"] or "Core") not in filter_prio:
                    continue
                req = r["required_qty"] or 0
                cur = r["current_qty"] or 0
                is_ok = cur >= req
                if filter_status == "Incomplete only" and is_ok:
                    continue
                if filter_status == "Complete only" and not is_ok:
                    continue
                rows_to_show.append(r)

            st.caption(f"Showing {len(rows_to_show)} of {len(inv)} items")
            rows_to_show = sorted(rows_to_show, key=lambda x: (x["category"] or "", x["item_description"] or ""))
            updates = {}

            for cat, group in groupby(rows_to_show, key=lambda x: x["category"] or "Other"):
                group_list = list(group)
                with st.expander(f"**{cat}** ({len(group_list)} items)", expanded=("Hose" in (cat or "") or "Hand Tools" in (cat or "") or "Safety" in (cat or ""))):
                    for r in group_list:
                        req = r["required_qty"] or 0
                        cur = r["current_qty"] or 0
                        is_ok = cur >= req
                        status_icon = "✅" if is_ok else "❌"
                        prio_color = {"Core": "🟢", "Recommended": "🟡", "Optional": "🔴"}.get(r["priority"] or "Core", "⚪")
                        c1, c2, c3, c4, c5 = st.columns([4, 1.2, 1.2, 1.5, 2])
                        c1.markdown(
                            f"{status_icon} {prio_color} **{r['item_description']}**  \n"
                            f"<small>{r['specification'] or ''} · {r['unit'] or ''}</small>",
                            unsafe_allow_html=True,
                        )
                        c2.markdown(f"Req: **{req}**")
                        new_qty = c3.number_input(
                            "Current", min_value=0.0, value=float(cur),
                            step=1.0 if req == int(req) else 0.5,
                            key=f"qty_{r['id']}", label_visibility="collapsed",
                        )
                        if new_qty != cur:
                            updates[r["id"]] = new_qty
                        c4.text_input("Stock #", value=r["stock_number"] or "", key=f"stock_{r['id']}",
                                      label_visibility="collapsed", placeholder="Stock #")
                        note_preview = (r["notes"] or "")[:60]
                        if note_preview:
                            c5.caption(note_preview)

            if updates:
                if st.button("💾 Save Quantity Changes", type="primary"):
                    bulk_update_qty(truck_id, updates, checked_by=display_name)
                    for r in rows_to_show:
                        key = f"stock_{r['id']}"
                        if key in st.session_state:
                            new_stock = st.session_state[key]
                            if new_stock != (r["stock_number"] or ""):
                                update_item_qty(r["id"], updates.get(r["id"], r["current_qty"] or 0),
                                                stock_number=new_stock, checked_by=display_name)
                    st.success(f"Saved {len(updates)} quantity update(s).")
                    st.rerun()

    # ---- NOTIFICATIONS ----
    elif page == "Notifications":
        st.title("Notifications")
        show_all = st.checkbox("Show acknowledged notifications too", value=False)
        notifs = get_notifications(unack_only=not show_all, limit=100)
        if st.button("Acknowledge All Open"):
            acknowledge_all(by=display_name)
            st.rerun()
        if not notifs:
            st.success("No open notifications.")
        else:
            for n in notifs:
                sev = n["severity"] or "info"
                icon = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(sev, "ℹ️")
                c1, c2 = st.columns([8, 1])
                c1.markdown(
                    f"{icon} **{n['truck_name'] or 'System'}** — {n['message']}  \n"
                    f"<small>{n['created_at']} · {sev}"
                    + (f" · ack by {n['acknowledged_by']}" if n["acknowledged"] else "")
                    + "</small>",
                    unsafe_allow_html=True,
                )
                if not n["acknowledged"]:
                    if c2.button("Ack", key=f"ack_{n['id']}"):
                        acknowledge_notification(n["id"], by=display_name)
                        st.rerun()
                st.divider()

    # ---- STANDARDS ----
    elif page == "Standards Reference":
        st.title("NUS Standards Reference")
        tab1, tab2 = st.tabs(["Structural (Type 1 & 2)", "Wildland (Type 3–6)"])
        with tab1:
            std = load_structural_standard()
            st.dataframe(std, use_container_width=True, hide_index=True)
            st.caption(f"{len(std)} items from structural NUS standard")
        with tab2:
            std = load_wildland_standard()
            st.dataframe(std, use_container_width=True, hide_index=True)
            st.caption(f"{len(std)} items from wildland NUS standard")

    # ---- USER MANAGEMENT ----
    elif page == "User Management":
        if not is_admin:
            st.error("Admin access required.")
            st.stop()
        st.title("User Management")
        with st.expander("➕ Create New User", expanded=True):
            with st.form("create_user"):
                c1, c2 = st.columns(2)
                new_user = c1.text_input("Username *")
                new_display = c2.text_input("Display Name *")
                new_pw = st.text_input("Password *", type="password")
                new_role = st.selectbox("Role", ["user", "admin"])
                if st.form_submit_button("Create User"):
                    if not new_user.strip() or not new_display.strip() or not new_pw:
                        st.error("All fields are required.")
                    elif create_user(new_user, new_display, new_pw, new_role):
                        st.success(f"User **{new_user}** created.")
                        st.rerun()
                    else:
                        st.error("Username already exists.")

        st.subheader("Existing Users")
        users = list_users()
        for u in users:
            c1, c2, c3, c4 = st.columns([2, 2, 1, 2])
            c1.markdown(f"**{u['username']}**  \n{u['display_name']}")
            c2.markdown(f"Role: {u['role']}  \n{'Active' if u['active'] else 'Disabled'}")
            c3.markdown(u["created_at"] or "")
            with c4:
                if u["username"] != "admin":
                    if u["active"]:
                        if st.button("Disable", key=f"dis_{u['id']}"):
                            set_user_active(u["id"], False)
                            st.rerun()
                    else:
                        if st.button("Enable", key=f"en_{u['id']}"):
                            set_user_active(u["id"], True)
                            st.rerun()
            st.divider()

        st.subheader("Change Your Password")
        with st.form("change_pw"):
            pw1 = st.text_input("New password", type="password")
            pw2 = st.text_input("Confirm new password", type="password")
            if st.form_submit_button("Update Password"):
                if not pw1 or pw1 != pw2:
                    st.error("Passwords must match and not be empty.")
                else:
                    change_password(user["id"], pw1)
                    st.success("Password updated. Sign out and back in with the new password.")

    st.sidebar.markdown("---")
    st.sidebar.caption("Apparatus Inventory Tracker · NUS-based\nStructural Type 1/2 · Wildland Type 3–6")


# Streamlit executes the whole file; run UI when we have a script context
try:
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    _ctx = get_script_run_ctx()
except Exception:
    _ctx = None

if _ctx is not None:
    main()
