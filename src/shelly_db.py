# shelly_db.py – Database layer and Shelly communication.

import ipaddress
import socket
import sqlite3
import time
import requests
from datetime import datetime, timedelta

DEFAULT_SHELLY_IP         = "192.168.179.9"
DEFAULT_TIMEOUT           = 10
DEFAULT_NET_ENERGY_PERIOD = 3600
DEFAULT_REF_DAYS          = [1, 7, 14, 21, 28]


def _connect(db_path):
    """Return a new SQLite connection for *db_path*."""
    return sqlite3.connect(db_path)


def init_db(db_path):
    """Create the database and all required tables if they do not exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = _connect(db_path)

    con.execute("""
        CREATE TABLE IF NOT EXISTS shelly_devices (
            mac      TEXT PRIMARY KEY,
            ip       TEXT,
            typ      TEXT,
            model    TEXT,
            firmware TEXT,
            app      TEXT,
            profile  TEXT,
            updated  TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS raw_hours (
            mac          TEXT NOT NULL,
            ts           INTEGER NOT NULL,
            a_net_energy REAL,
            b_net_energy REAL,
            c_net_energy REAL,
            PRIMARY KEY (mac, ts)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS reference_days (
            mac            TEXT NOT NULL,
            date           TEXT NOT NULL,
            ts_start       INTEGER,
            ts_end         INTEGER,
            consumption_wh REAL,
            feedin_wh      REAL,
            PRIMARY KEY (mac, date)
        )
    """)

    con.commit()
    con.close()


def upsert_device(db_path, info):
    """Insert or update a Shelly device record identified by its MAC address."""
    con = _connect(db_path)
    con.execute("""
        INSERT INTO shelly_devices (mac, ip, typ, model, firmware, app, profile, updated)
        VALUES (:mac, :ip, :typ, :model, :firmware, :app, :profile, :updated)
        ON CONFLICT(mac) DO UPDATE SET
            ip       = excluded.ip,
            firmware = excluded.firmware,
            updated  = excluded.updated
    """, info)
    con.commit()
    con.close()


def load_devices(db_path):
    """Return all stored Shelly devices as a list of dicts."""
    con = _connect(db_path)
    rows = con.execute(
        "SELECT mac, ip, typ, model, firmware, app, profile, updated FROM shelly_devices"
    ).fetchall()
    con.close()
    return [
        {"mac": r[0], "ip": r[1], "typ": r[2], "model": r[3],
         "firmware": r[4], "app": r[5], "profile": r[6], "updated": r[7]}
        for r in rows
    ]


def stored_dates(db_path, mac):
    """Return the set of already stored reference day date strings for *mac*."""
    con = _connect(db_path)
    result = {r[0] for r in con.execute(
        "SELECT date FROM reference_days WHERE mac = ?", (mac,)
    ).fetchall()}
    con.close()
    return result


def last_raw_ts(db_path, mac):
    """Return the timestamp of the most recent stored hourly record for *mac*, or 0."""
    con = _connect(db_path)
    try:
        result = con.execute(
            "SELECT MAX(ts) FROM raw_hours WHERE mac = ?", (mac,)
        ).fetchone()[0]
        return result or 0
    except Exception:
        return 0
    finally:
        con.close()


def check_shelly(shelly_ip=DEFAULT_SHELLY_IP, timeout=DEFAULT_TIMEOUT):
    """Return True if the Shelly device at *shelly_ip* is reachable."""
    try:
        r = requests.get(f"http://{shelly_ip}/rpc/Shelly.GetStatus", timeout=timeout)
        return r.status_code == 200
    except requests.RequestException:
        return False


def _parse_device_info(ip, info):
    """Parse a GetDeviceInfo response into a normalised device dict."""
    raw_id  = info.get("id", "")
    parts   = raw_id.split("-", 1)
    typ     = parts[0] if len(parts) == 2 else raw_id
    mac_raw = parts[1].upper() if len(parts) == 2 else info.get("mac", "")
    mac_fmt = ":".join(mac_raw[i:i+2] for i in range(0, len(mac_raw), 2))
    firmware = info.get("fw_id", info.get("ver", ""))
    # Parse date/time from fw_id: "20260120-145246/1.7.4-gf9878b6"
    try:
        fw_date = firmware[:8]
        fw_time = firmware[9:15]
        d = datetime.strptime(fw_date, "%Y%m%d")
        t = datetime.strptime(fw_time, "%H%M%S")
        updated = f"{d.day:02d}.{d.month:02d}.{d.year} {t.hour:02d}:{t.minute:02d}"
    except Exception:
        updated = firmware
    return {
        "ip":       ip,
        "mac":      mac_fmt,
        "typ":      typ,
        "model":    info.get("model", ""),
        "firmware": firmware,
        "app":      info.get("app", ""),
        "profile":  info.get("profile", ""),
        "updated":  updated,
    }


def discover_shelly(timeout=0.3, log_callback=None):
    """Scan the local /24 subnet for a Shelly device and return its info dict, or None."""

    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        own_ip = s.getsockname()[0]
        s.close()
    except OSError:
        log("Network unavailable.")
        return None

    subnet = ".".join(own_ip.split(".")[:3]) + ".0/24"

    for ip in ipaddress.ip_network(subnet, strict=False).hosts():
        ip = str(ip)
        subis = int(ip.rsplit(".", 1)[1])
        if subis % 20 == 0:
            log(f"Scanning from: {ip} up to 254, please wait...")
        try:
            r = requests.get(f"http://{ip}/", timeout=timeout)
        except Exception:
            continue
        if r.text.find("Shelly") < 1:
            continue
        try:
            info = requests.get(
                f"http://{ip}/rpc/Shelly.GetDeviceInfo", timeout=DEFAULT_TIMEOUT
            ).json()
        except Exception:
            info = {}
        result = _parse_device_info(ip, info)
        log(f"Shelly found: {ip} | {result['typ']} | {result['model']} | {result['mac']}")
        return result

    log("No Shelly found.")
    return None


def get_device_info(shelly_ip=DEFAULT_SHELLY_IP, timeout=DEFAULT_TIMEOUT):
    """Fetch device info directly from a known IP and return a normalised dict, or None."""
    try:
        info = requests.get(
            f"http://{shelly_ip}/rpc/Shelly.GetDeviceInfo", timeout=timeout
        ).json()
        return _parse_device_info(shelly_ip, info)
    except Exception:
        return None


def get_range(shelly_ip=DEFAULT_SHELLY_IP, timeout=DEFAULT_TIMEOUT):
    """Return (begin_ts, end_ts) of available data on the device, or None on failure."""
    try:
        r        = requests.get(f"http://{shelly_ip}/rpc/EMData.GetRecords?id=0", timeout=timeout)
        block    = r.json().get("data_blocks", [{}])[0]
        begin_ts = block.get("ts")
        interval = block.get("period", 60)
        count    = block.get("records", 0)
        if begin_ts is None:
            return None
        return begin_ts, begin_ts + interval * count
    except requests.RequestException:
        return None


def align_to_period(ts, period):
    """Round *ts* down to the nearest multiple of *period*."""
    return (ts // period) * period


def fetch_all_raw(db_path, mac, begin_ts, end_ts,
                  shelly_ip=DEFAULT_SHELLY_IP,
                  timeout=DEFAULT_TIMEOUT,
                  net_energy_period=DEFAULT_NET_ENERGY_PERIOD,
                  log_callback=None):
    """Download all hourly net-energy records from the Shelly and store them in the DB."""

    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    start_ts = align_to_period(max(begin_ts, last_raw_ts(db_path, mac) + 1), net_energy_period)

    if start_ts >= end_ts:
        log("Raw data already up to date.")
        return

    log(f"Fetching raw data from {datetime.fromtimestamp(start_ts):%d.%m.%Y} ...")
    all_rows = []
    ts       = start_ts
    t_start  = time.time()
    cur_day  = None

    while ts < end_ts:
        url = (f"http://{shelly_ip}/rpc/EMData.GetNetEnergies"
               f"?id=0&ts={ts}&end_ts={end_ts}&period={net_energy_period}")
        try:
            payload = requests.get(url, timeout=timeout).json()
        except requests.RequestException:
            break

        keys   = payload.get("keys", [])
        blocks = payload.get("data", [])

        for block in blocks:
            block_ts = block["ts"]
            for i, values in enumerate(block["values"]):
                rec_ts = block_ts + i * net_energy_period
                rec    = dict(zip(keys, values))
                all_rows.append((
                    mac,
                    rec_ts,
                    rec.get("a_net_act_energy", 0.0),
                    rec.get("b_net_act_energy", 0.0),
                    rec.get("c_net_act_energy", 0.0),
                ))

        day = datetime.fromtimestamp(ts).day
        if day != cur_day:
            cur_day = day
            log(f"{datetime.fromtimestamp(ts):%d.%m.%Y} | rows: {len(all_rows)} | {time.time()-t_start:.1f}s")

        next_ts = payload.get("next_record_ts")
        if not next_ts or next_ts >= end_ts:
            break
        ts = next_ts

    if all_rows:
        con = _connect(db_path)
        con.executemany("INSERT OR IGNORE INTO raw_hours VALUES (?,?,?,?,?)", all_rows)
        con.commit()
        con.close()
        log(f"{len(all_rows)} raw records saved ({time.time()-t_start:.1f}s).")


def reference_days_in_range(begin, end, ref_days=DEFAULT_REF_DAYS):
    """Return a sorted list of reference day dates within [begin, end]."""
    result = []
    cur    = begin.replace(day=1)
    while cur <= end:
        for day in ref_days:
            try:
                d = cur.replace(day=day)
                if begin <= d <= end:
                    result.append(d)
            except ValueError:
                pass
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return sorted(result)


def collect(db_path, mac,
            shelly_ip=DEFAULT_SHELLY_IP,
            timeout=DEFAULT_TIMEOUT,
            net_energy_period=DEFAULT_NET_ENERGY_PERIOD,
            ref_days=DEFAULT_REF_DAYS,
            log_callback=None):
    """Main data collection routine: sync raw records and compute missing reference days."""

    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)

    log("Connecting to Shelly ...")

    if not check_shelly(shelly_ip, timeout):
        return f"WARNING: No Shelly reachable at {shelly_ip}. Please check the IP."

    # Update device info
    info = get_device_info(shelly_ip, timeout)
    if info:
        upsert_device(db_path, info)

    data_range = get_range(shelly_ip, timeout)
    if not data_range:
        return "WARNING: Could not retrieve data range."

    begin_ts, end_ts = data_range
    begin = datetime.fromtimestamp(begin_ts)
    end   = datetime.fromtimestamp(end_ts)
    log(f"Available: {begin:%d.%m.%Y} – {end:%d.%m.%Y}")

    fetch_all_raw(db_path, mac, begin_ts, end_ts, shelly_ip, timeout, net_energy_period, log_callback)

    all_ref_days = reference_days_in_range(begin, end, ref_days)
    known        = stored_dates(db_path, mac)
    missing      = [d for d in all_ref_days if d.strftime("%Y-%m-%d") not in known]

    if not missing:
        log("All reference days already stored.")
        return "Up to date."

    log(f"Computing {len(missing)} reference days ...")
    boundaries = sorted(set([begin] + all_ref_days + [end]))

    con      = _connect(db_path)
    inserted = 0

    for ref_day in missing:
        date_str = ref_day.strftime("%Y-%m-%d")
        idx      = boundaries.index(ref_day)
        prev_day = boundaries[idx - 1] if idx > 0 else ref_day
        ts_start = int(prev_day.timestamp())
        ts_end   = int(ref_day.timestamp())

        row = con.execute("""
            SELECT
                SUM(MAX(a_net_energy + b_net_energy + c_net_energy, 0)),
                SUM(ABS(MIN(a_net_energy + b_net_energy + c_net_energy, 0)))
            FROM raw_hours
            WHERE mac = ? AND ts >= ? AND ts < ?
        """, (mac, ts_start, ts_end)).fetchone()

        if row is None or row[0] is None:
            log(f"No raw data for period ending {ref_day:%d.%m.%Y}")
            continue

        con.execute(
            "INSERT OR IGNORE INTO reference_days VALUES (?,?,?,?,?,?)",
            (mac, date_str, ts_start, ts_end, row[0], row[1])
        )
        inserted += 1

    con.commit()
    con.close()
    log(f"{inserted} reference days saved.")
    return f"{inserted} reference days saved."