import logging
import requests
import json
import os
import uuid
import time
import threading
from collections import defaultdict
from datetime import datetime
import psycopg2
import psycopg2.extras
import psycopg2.pool
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ======================== إعدادات البوت ========================
BOT_TOKEN       = os.environ.get("BOT_TOKEN",       "8773580013:AAFku28jd9oF0JpCpv9U_BvXtDY5yzSnvyQ")
ADMIN_ID        = int(os.environ.get("ADMIN_ID",    "8492949590"))
ADMIN_USERNAME  = os.environ.get("ADMIN_USERNAME",  "@VIP10ADMIN")
SMM_API_KEY     = os.environ.get("SMM_API_KEY",     "e7c929c6ff91fa7b91f945f59d726348")
SMM_API_URL     = os.environ.get("SMM_API_URL",     "https://boostprovider.com/api/v2")
SHAM_CASH_ACCOUNT    = os.environ.get("SHAM_CASH_ACCOUNT",    "faff24e005ce48a4528f18674ad95967")
SYRIATEL_CASH_ACCOUNT = os.environ.get("SYRIATEL_CASH_ACCOUNT", "38090777")
REFERRAL_COMMISSION  = float(os.environ.get("REFERRAL_COMMISSION", "0.07"))
DATABASE_URL = "postgresql://postgres.yxafhdudoycjeyukvtkf:hasn1234DDGGGDSD@aws-1-ap-southeast-1.pooler.supabase.com:6543/postgres"

# ======================== الاشتراك الإجباري ========================
REQUIRED_CHANNEL_ID       = -1003772429885
REQUIRED_CHANNEL_URL      = "https://t.me/VIPBOST10"
REQUIRED_CHANNEL_USERNAME = "@VIPBOST10"

# ======================== حالات المحادثة ========================
(
    MAIN_MENU, CHARGE_MENU, SHAM_MENU, SHAM_TYPE,
    SHAM_AMOUNT, SHAM_TX_ID, SYRIATEL_AMOUNT, SYRIATEL_TX_ID,
    SERVICE_PLATFORM, SERVICE_TYPE, SERVICE_SELECT,
    ORDER_QUANTITY, ORDER_LINK, ORDER_CONFIRM,
    ADMIN_PANEL, ADMIN_MULTIPLIER,
    ADMIN_CONFIRM_AMOUNT,
    ADMIN_USERS_LIST, ADMIN_USERS_SEARCH, ADMIN_USER_VIEW,
    ADMIN_USER_EDIT_BALANCE,
    ADMIN_PRICES_PLATFORM, ADMIN_PRICES_CATEGORY,
    ADMIN_PRICES_SERVICE, ADMIN_PRICE_EDIT,
    ORDER_STATUS_LIST, ADMIN_BROADCAST_INPUT,
    ADMIN_CBTN_LIST, ADMIN_CBTN_NAME, ADMIN_CBTN_VIEW,
    ADMIN_CBTN_RENAME, ADMIN_CBTN_ADD_SVC,
    ADMIN_MANAGE_ADMINS,
    ADMIN_ADD_ADMIN_INPUT,
    ADMIN_CBTN_ROW_INPUT,
) = range(35)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ======================== اتصال PostgreSQL ========================
_db_lock = threading.Lock()
_db_pool = None

def _init_pool():
    global _db_pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set!")
    _db_pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=1, maxconn=10,
        dsn=DATABASE_URL,
        cursor_factory=psycopg2.extras.RealDictCursor
    )
    logger.info("✅ PostgreSQL connection pool initialized")

def _get_conn():
    """Get a connection from the pool, reconnecting if needed."""
    global _db_pool
    try:
        conn = _db_pool.getconn()
        # Test connection is alive
        conn.cursor().execute("SELECT 1")
        return conn
    except Exception:
        # Pool may have stale connections — reinitialize
        try:
            _init_pool()
        except Exception as e:
            logger.error(f"Pool reinit failed: {e}")
            raise
        return _db_pool.getconn()

def _put_conn(conn):
    try:
        _db_pool.putconn(conn)
    except Exception:
        pass

def _db_run(sql, params=None, *, fetch=None, script=False):
    """Execute SQL and optionally fetch results. Thread-safe."""
    with _db_lock:
        conn = _get_conn()
        try:
            with conn.cursor() as c:
                if script:
                    for stmt in sql.split(";"):
                        stmt = stmt.strip()
                        if stmt:
                            c.execute(stmt)
                else:
                    c.execute(sql, params)
                if fetch == "one":
                    result = c.fetchone()
                elif fetch == "all":
                    result = c.fetchall()
                elif fetch == "val":
                    row = c.fetchone()
                    result = row[0] if row else None
                else:
                    result = None
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            _put_conn(conn)

# ======================== تهيئة الجداول ========================
def init_db():
    _init_pool()
    stmts = [
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            balance DOUBLE PRECISION DEFAULT 0.0,
            referral_balance DOUBLE PRECISION DEFAULT 0.0,
            referred_by TEXT,
            username TEXT,
            first_name TEXT,
            referrals TEXT DEFAULT '[]',
            orders TEXT DEFAULT '[]'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS admins (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            added_by TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS pending_payments (
            payment_key TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS custom_buttons (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT DEFAULT 'main',
            service_ids TEXT DEFAULT '[]',
            sort_order INTEGER DEFAULT 0,
            row_number INTEGER DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS custom_prices (
            svc_id TEXT PRIMARY KEY,
            price DOUBLE PRECISION NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS smm_id_map (
            svc_id TEXT PRIMARY KEY,
            smm_id TEXT NOT NULL
        )
        """,
        # إضافة عمود row_number إن لم يكن موجوداً (ترقية من إصدار سابق)
        """
        ALTER TABLE custom_buttons ADD COLUMN IF NOT EXISTS row_number INTEGER DEFAULT 0
        """,
        # Default price multiplier
        """
        INSERT INTO settings (key, value) VALUES ('price_multiplier', '2.0')
        ON CONFLICT (key) DO NOTHING
        """,
        # Seed main admin
        f"""
        INSERT INTO admins (user_id, username, added_by)
        VALUES ('{ADMIN_ID}', '{ADMIN_USERNAME}', 'system')
        ON CONFLICT (user_id) DO NOTHING
        """,
    ]
    with _db_lock:
        conn = _get_conn()
        try:
            with conn.cursor() as c:
                for stmt in stmts:
                    try:
                        c.execute(stmt)
                    except Exception as e:
                        logger.warning(f"Init stmt warning: {e}")
                        conn.rollback()
            conn.commit()
            logger.info("✅ All database tables initialized")
        except Exception as e:
            conn.rollback()
            logger.error(f"init_db error: {e}")
            raise
        finally:
            _put_conn(conn)

# ======================== دوال مساعدة ========================
def _row_to_user(row):
    if row is None:
        return None
    d = dict(row)
    d["referrals"] = json.loads(d.get("referrals") or "[]")
    d["orders"]    = json.loads(d.get("orders")    or "[]")
    return d

def _row_to_btn(row):
    if row is None:
        return None
    d = dict(row)
    d["service_ids"] = json.loads(d.get("service_ids") or "[]")
    return d

# ======================== إدارة الأدمن ========================
def is_admin(user_id):
    uid = str(user_id)
    row = _db_run("SELECT 1 FROM admins WHERE user_id=%s", (uid,), fetch="one")
    return row is not None

def get_all_admins():
    rows = _db_run("SELECT * FROM admins ORDER BY added_at ASC", fetch="all")
    return [dict(r) for r in rows] if rows else []

def add_admin(user_id, username=None, added_by=None):
    uid = str(user_id)
    _db_run(
        """INSERT INTO admins (user_id, username, added_by)
           VALUES (%s, %s, %s)
           ON CONFLICT (user_id) DO UPDATE SET username=EXCLUDED.username""",
        (uid, username or uid, str(added_by or ""))
    )

def remove_admin(user_id):
    uid = str(user_id)
    if uid == str(ADMIN_ID):
        return False  # Cannot remove main admin
    _db_run("DELETE FROM admins WHERE user_id=%s", (uid,))
    return True

# ======================== دوال المستخدمين ========================
def get_user(user_id):
    uid = str(user_id)
    row = _db_run("SELECT * FROM users WHERE user_id=%s", (uid,), fetch="one")
    if row is None:
        _db_run(
            """INSERT INTO users (user_id, balance, referral_balance, referred_by,
               username, first_name, referrals, orders)
               VALUES (%s, 0.0, 0.0, NULL, NULL, NULL, '[]', '[]')
               ON CONFLICT (user_id) DO NOTHING""",
            (uid,)
        )
        return {"balance": 0.0, "referral_balance": 0.0, "referred_by": None,
                "referrals": [], "orders": [], "username": None, "first_name": None}
    return _row_to_user(row)

def update_user(user_id, updates):
    uid = str(user_id)
    # Ensure user exists
    existing = get_user(uid)
    existing.update(updates)
    referrals = json.dumps(existing.get("referrals", []), ensure_ascii=False)
    orders    = json.dumps(existing.get("orders",    []), ensure_ascii=False)
    _db_run(
        """UPDATE users SET balance=%s, referral_balance=%s, referred_by=%s,
               username=%s, first_name=%s, referrals=%s, orders=%s
           WHERE user_id=%s""",
        (
            existing.get("balance", 0.0),
            existing.get("referral_balance", 0.0),
            existing.get("referred_by"),
            existing.get("username"),
            existing.get("first_name"),
            referrals,
            orders,
            uid
        )
    )

def get_all_users():
    rows = _db_run("SELECT * FROM users ORDER BY user_id", fetch="all")
    return {r["user_id"]: _row_to_user(r) for r in rows} if rows else {}

def get_users_count():
    return _db_run("SELECT COUNT(*) FROM users", fetch="val") or 0

def add_referral(referrer_id, new_user_id):
    rid = str(referrer_id)
    nid = str(new_user_id)
    with _db_lock:
        conn = _get_conn()
        try:
            with conn.cursor() as c:
                c.execute("SELECT referrals FROM users WHERE user_id=%s", (rid,))
                row = c.fetchone()
                if row is None:
                    c.execute(
                        """INSERT INTO users (user_id, referrals)
                           VALUES (%s, %s)
                           ON CONFLICT (user_id) DO NOTHING""",
                        (rid, json.dumps([nid]))
                    )
                else:
                    refs = json.loads(row["referrals"] or "[]")
                    if nid not in refs:
                        refs.append(nid)
                        c.execute("UPDATE users SET referrals=%s WHERE user_id=%s",
                                  (json.dumps(refs), rid))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _put_conn(conn)

# ======================== إعدادات النظام ========================
def get_multiplier():
    val = _db_run("SELECT value FROM settings WHERE key='price_multiplier'", fetch="one")
    return float(val["value"]) if val else 2.0

def set_multiplier(v):
    _db_run(
        "INSERT INTO settings (key, value) VALUES ('price_multiplier', %s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value",
        (str(float(v)),)
    )

# ======================== المدفوعات المعلقة ========================
def save_pending_payment(payment_key, info):
    _db_run(
        """INSERT INTO pending_payments (payment_key, data) VALUES (%s, %s)
           ON CONFLICT (payment_key) DO UPDATE SET data=EXCLUDED.data""",
        (str(payment_key), json.dumps(info, ensure_ascii=False))
    )

def get_pending_payment(payment_key):
    row = _db_run("SELECT data FROM pending_payments WHERE payment_key=%s", (str(payment_key),), fetch="one")
    return json.loads(row["data"]) if row else None

def remove_pending_payment(payment_key):
    _db_run("DELETE FROM pending_payments WHERE payment_key=%s", (str(payment_key),))

# ======================== الأسعار المخصصة ========================
def get_custom_price(svc_id):
    row = _db_run("SELECT price FROM custom_prices WHERE svc_id=%s", (str(svc_id),), fetch="one")
    return float(row["price"]) if row else None

def set_custom_price(svc_id, price):
    _db_run(
        """INSERT INTO custom_prices (svc_id, price) VALUES (%s, %s)
           ON CONFLICT (svc_id) DO UPDATE SET price=EXCLUDED.price""",
        (str(svc_id), float(price))
    )

def clear_custom_price(svc_id):
    _db_run("DELETE FROM custom_prices WHERE svc_id=%s", (str(svc_id),))

# ======================== خريطة معرفات المزود ========================
def get_smm_id_map(svc_id):
    row = _db_run("SELECT smm_id FROM smm_id_map WHERE svc_id=%s", (str(svc_id),), fetch="one")
    return row["smm_id"] if row else None

def save_smm_id_map(svc_id, smm_id):
    _db_run(
        """INSERT INTO smm_id_map (svc_id, smm_id) VALUES (%s, %s)
           ON CONFLICT (svc_id) DO UPDATE SET smm_id=EXCLUDED.smm_id""",
        (str(svc_id), str(smm_id))
    )

# ======================== SMM API ========================
def smm_request(action, params={}):
    payload = {"key": SMM_API_KEY, "action": action}
    payload.update(params)
    try:
        r = requests.post(SMM_API_URL, data=payload, timeout=15)
        return r.json()
    except Exception as e:
        logger.error(f"SMM API Error: {e}")
        return None

def get_smm_services():
    return smm_request("services")

def place_order(service_id, link, quantity):
    return smm_request("add", {"service": service_id, "link": link, "quantity": quantity})

def get_order_status(order_id):
    return smm_request("status", {"order": order_id})

# ======================== كاش أسعار المزود ========================
_services_cache = {"data": None, "ts": 0}
SERVICES_CACHE_TTL = 300

def fetch_provider_services(force=False):
    now = time.time()
    if not force and _services_cache["data"] and (now - _services_cache["ts"] < SERVICES_CACHE_TTL):
        return _services_cache["data"]
    result = get_smm_services()
    if isinstance(result, list):
        mapping = {}
        for s in result:
            sid = str(s.get("service"))
            try:
                rate = float(s.get("rate", 0))
            except (TypeError, ValueError):
                rate = 0.0
            mapping[sid] = {
                "rate": rate,
                "min": s.get("min"),
                "max": s.get("max"),
                "name": s.get("name", "")
            }
        _services_cache["data"] = mapping
        _services_cache["ts"] = now
        return mapping
    return _services_cache["data"] or {}

def get_live_price(svc):
    smm_id = svc.get("smm_id")
    if smm_id:
        info = fetch_provider_services().get(str(smm_id))
        if info and info.get("rate"):
            return info["rate"]
    return svc.get("price_per_1000", 0.0)

def get_customer_price(svc):
    custom = get_custom_price(svc["id"])
    if custom is not None:
        return custom
    return get_live_price(svc) * get_multiplier()

PLATFORM_KEYWORDS = {
    "instagram": ["instagram", "insta", "ig "],
    "facebook":  ["facebook", "fb "],
    "telegram":  ["telegram", "tg "],
}
CATEGORY_KEYWORDS = {
    "followers":  ["follower", "followers", "subscriber", "subscribers", "member", "members"],
    "reactions":  ["like", "likes", "reaction", "reactions", "view", "views", "love", "haha", "wow", "angry", "sad", "share", "shares"],
    "comments":   ["comment", "comments"],
}

def _name_matches(name, keywords):
    n = (name or "").lower()
    return any(k in n for k in keywords)

def resolve_smm_id(svc, platform_key, category_key):
    cached = get_smm_id_map(svc["id"])
    if cached:
        return cached
    if svc.get("smm_id"):
        save_smm_id_map(svc["id"], svc["smm_id"])
        return svc["smm_id"]
    provider = fetch_provider_services()
    if not provider:
        return None
    p_kw = PLATFORM_KEYWORDS.get(platform_key, [])
    c_kw = CATEGORY_KEYWORDS.get(category_key, [])
    candidates = []
    for sid, info in provider.items():
        nm = info.get("name", "")
        if p_kw and not _name_matches(nm, p_kw):
            continue
        if c_kw and not _name_matches(nm, c_kw):
            continue
        if info.get("rate", 0) <= 0:
            continue
        candidates.append((info["rate"], sid, info))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    chosen = candidates[0][1]
    save_smm_id_map(svc["id"], chosen)
    return chosen

def find_service_by_id(svc_id):
    for platform_key, platform_data in SERVICES.items():
        for cat_key, cat_data in platform_data["categories"].items():
            for s in cat_data["services"]:
                if s["id"] == svc_id:
                    return platform_key, cat_key, s
    return None, None, None

# ======================== أزرار مخصصة (PostgreSQL + row_number) ========================
def get_custom_buttons():
    rows = _db_run(
        "SELECT * FROM custom_buttons ORDER BY sort_order ASC, id ASC",
        fetch="all"
    )
    return [_row_to_btn(r) for r in rows] if rows else []

def get_custom_button(btn_id):
    row = _db_run("SELECT * FROM custom_buttons WHERE id=%s", (btn_id,), fetch="one")
    return _row_to_btn(row)

def create_custom_button(name, location="main"):
    btn_id = uuid.uuid4().hex[:8]
    with _db_lock:
        conn = _get_conn()
        try:
            with conn.cursor() as c:
                c.execute("SELECT COALESCE(MAX(sort_order), 0) FROM custom_buttons")
                max_order = c.fetchone()[0]
                next_order = max_order + 1
                c.execute(
                    """INSERT INTO custom_buttons
                       (id, name, location, service_ids, sort_order, row_number)
                       VALUES (%s, %s, %s, '[]', %s, 0)""",
                    (btn_id, name, location, next_order)
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _put_conn(conn)
    return {"id": btn_id, "name": name, "location": location,
            "service_ids": [], "sort_order": next_order, "row_number": 0}

def update_custom_button(btn_id, updates):
    existing = get_custom_button(btn_id)
    if existing is None:
        return None
    existing.update(updates)
    _db_run(
        """UPDATE custom_buttons
           SET name=%s, location=%s, service_ids=%s, sort_order=%s, row_number=%s
           WHERE id=%s""",
        (
            existing["name"],
            existing["location"],
            json.dumps(existing["service_ids"], ensure_ascii=False),
            existing.get("sort_order", 0),
            existing.get("row_number", 0),
            btn_id
        )
    )
    return existing

def delete_custom_button(btn_id):
    _db_run("DELETE FROM custom_buttons WHERE id=%s", (btn_id,))

def get_custom_buttons_for_location(location):
    rows = _db_run(
        "SELECT * FROM custom_buttons WHERE location=%s ORDER BY sort_order ASC, id ASC",
        (location,),
        fetch="all"
    )
    return [_row_to_btn(r) for r in rows] if rows else []

def build_buttons_layout(buttons):
    """
    Build a keyboard layout from custom buttons using row_number.
    Buttons with the same row_number appear side-by-side on the same row.
    Buttons with different row_number appear on separate rows.
    row_number=0 means the button gets its own row.
    """
    if not buttons:
        return []
    # Separate solo buttons (row_number=0) from grouped ones
    groups = defaultdict(list)
    solos  = []
    for btn in sorted(buttons, key=lambda b: (b.get("sort_order", 0), b.get("id", ""))):
        rn = btn.get("row_number", 0)
        if rn == 0:
            solos.append(btn)
        else:
            groups[rn].append(btn)
    keyboard = []
    # Merge solo + grouped buttons, maintaining sort_order
    processed = []
    for btn in sorted(buttons, key=lambda b: (b.get("sort_order", 0), b.get("id", ""))):
        rn = btn.get("row_number", 0)
        if rn == 0:
            processed.append(("solo", btn))
        elif rn not in [x[0] for x in processed if isinstance(x[0], int)]:
            processed.append((rn, groups[rn]))
    seen_rows = set()
    for item in processed:
        key, val = item
        if isinstance(key, int):
            if key not in seen_rows:
                seen_rows.add(key)
                keyboard.append([
                    InlineKeyboardButton(b["name"], callback_data=f"cbtn_{b['id']}")
                    for b in val
                ])
        else:
            keyboard.append([InlineKeyboardButton(val["name"], callback_data=f"cbtn_{val['id']}")])
    return keyboard

def move_button_order(btn_id, direction):
    with _db_lock:
        conn = _get_conn()
        try:
            with conn.cursor() as c:
                c.execute("SELECT id, sort_order FROM custom_buttons WHERE id=%s", (btn_id,))
                btn = c.fetchone()
                if btn is None:
                    return
                current_order = btn["sort_order"]
                if direction < 0:
                    c.execute(
                        "SELECT id, sort_order FROM custom_buttons WHERE sort_order < %s ORDER BY sort_order DESC LIMIT 1",
                        (current_order,)
                    )
                else:
                    c.execute(
                        "SELECT id, sort_order FROM custom_buttons WHERE sort_order > %s ORDER BY sort_order ASC LIMIT 1",
                        (current_order,)
                    )
                other = c.fetchone()
                if other is None:
                    return
                c.execute("UPDATE custom_buttons SET sort_order=%s WHERE id=%s",
                          (other["sort_order"], btn_id))
                c.execute("UPDATE custom_buttons SET sort_order=%s WHERE id=%s",
                          (current_order, other["id"]))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _put_conn(conn)

LOCATION_LABELS = {
    "main":               "🏠 القائمة الرئيسية",
    "platform_telegram":  "✈️ تيليجرام",
    "platform_instagram": "📸 انستغرام",
    "platform_facebook":  "📘 فيسبوك",
}

# ======================== الخدمات (معرفات المزود) ========================
SERVICE_IDS = {
    "telegram": {
        "name": "تيليجرام ✈️",
        "categories": {
            "views_past":    {"name": "مشاهدات منشورات سابقة 👁️",           "ids": [6062,6061,6060,6059,6058,6057,6055,4136,4135]},
            "views_future":  {"name": "مشاهدات منشورات مستقبلية 🔮",         "ids": [6068,6067,6066]},
            "members":       {"name": "أعضاء 👥",                             "ids": [8970,9039,9040,7756]},
            "reactions":     {"name": "تفاعلات ❤️",                          "ids": [9682,9681,9678,9676,9693,9705,9714,9715,9716,9729,9738,9742,9749,9906]},
            "referral_start":{"name": "بدء استخدام البوت / قبول الإحالة 🤝", "ids": [6034,6032,6031,6030]},
        },
    },
    "facebook": {
        "name": "فيسبوك 📘",
        "categories": {
            "followers": {"name": "متابعين 👥",   "ids": [8898,9430,8896,8882,4845,5369,4347,6030,6032]},
            "reactions": {"name": "تفاعلات ❤️",  "ids": [7738,7703,9536,9401,9376,9497,9375,4899]},
            "comments":  {"name": "تعليقات 💬",  "ids": [7566,7565]},
        },
    },
    "instagram": {
        "name": "انستغرام 📸",
        "categories": {
            "views":     {"name": "مشاهدات 👁️", "ids": [4013,4014,5351,4012,7566]},
            "followers": {"name": "متابعين 👥", "ids": [8849,8921,4805,4883]},
            "likes":     {"name": "إعجابات ❤️","ids": [7699,9252,8973]},
        },
    },
}

def get_provider_service(smm_id):
    return fetch_provider_services().get(str(smm_id))

def build_service(smm_id):
    info = get_provider_service(smm_id)
    if not info:
        return None
    return {
        "id": str(smm_id),
        "smm_id": str(smm_id),
        "name": info.get("name", f"خدمة #{smm_id}"),
        "min": info.get("min", 1),
        "max": info.get("max", 1000000),
        "price_per_1000": info.get("rate", 0.0),
        "avg_time": "غير محدد",
    }

def get_category_services(platform_key, category_key):
    cat = SERVICE_IDS.get(platform_key, {}).get("categories", {}).get(category_key, {})
    return [s for sid in cat.get("ids", []) if (s := build_service(sid))]

class _ServicesProxy:
    def __getitem__(self, key):
        return self._wrap(key)
    def get(self, key, default=None):
        return self._wrap(key) if key in SERVICE_IDS else default
    def items(self):
        return [(k, self._wrap(k)) for k in SERVICE_IDS]
    def keys(self):
        return SERVICE_IDS.keys()
    def __contains__(self, key):
        return key in SERVICE_IDS
    def _wrap(self, pkey):
        pdata = SERVICE_IDS[pkey]
        cats = {
            ckey: {"name": cdata["name"], "services": get_category_services(pkey, ckey)}
            for ckey, cdata in pdata["categories"].items()
        }
        return {"name": pdata["name"], "categories": cats}

SERVICES = _ServicesProxy()

# ======================== دوال مساعدة للواجهة ========================
def main_menu_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("💳 شحن رصيد",          callback_data="charge")],
        [InlineKeyboardButton("🛒 طلب خدمة",           callback_data="service")],
        [InlineKeyboardButton("📊 حالة الطلب",         callback_data="order_status")],
        [InlineKeyboardButton("👥 إحالة صديق",         callback_data="referral")],
        [InlineKeyboardButton("📞 التواصل مع الدعم",   callback_data="support")],
    ]
    # أزرار مخصصة للقائمة الرئيسية مع دعم تخطيط الصفوف
    custom_rows = build_buttons_layout(get_custom_buttons_for_location("main"))
    keyboard.extend(custom_rows)
    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton("⚙️ لوحة الأدمن", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

def main_menu_text(user_id):
    balance = get_user(user_id).get("balance", 0.0)
    return (
        "🏠 القائمة الرئيسية\n"
        "━━━━━━━━━━━━━━━━\n"
        f"💳 رصيدك الحالي: {balance:.4f}$\n"
        "━━━━━━━━━━━━━━━━\n"
        "اختر ما تريد:"
    )

def back_button(cb="main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=cb)]])

# ======================== فحص الاشتراك ========================
async def is_user_subscribed(context, user_id):
    if is_admin(user_id):
        return True
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.error(f"Subscription check failed for {user_id}: {e}")
        return False

def subscription_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 الانضمام إلى القناة", url=REQUIRED_CHANNEL_URL)],
        [InlineKeyboardButton("✅ تحقق من الاشتراك",    callback_data="check_subscription")],
    ])

async def send_subscription_required(update):
    text = (
        "🔒 الاشتراك الإجباري\n"
        "━━━━━━━━━━━━━━━━\n"
        "للاستفادة من خدمات البوت يرجى الاشتراك أولاً:\n"
        f"📢 {REQUIRED_CHANNEL_USERNAME}\n\n"
        "بعد الاشتراك اضغط «✅ تحقق من الاشتراك»."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=subscription_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=subscription_keyboard())

async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if await is_user_subscribed(context, user_id):
        await query.answer("✅ تم التحقق من اشتراكك!", show_alert=True)
        get_user(user_id)
        balance = get_user(user_id).get("balance", 0.0)
        await query.edit_message_text(
            f"👋 أهلاً {query.from_user.first_name}!\n\n"
            "🌟 مرحباً في بوت خدمات السوشيال ميديا\n"
            "━━━━━━━━━━━━━━━━\n"
            f"💳 رصيدك الحالي: {balance:.4f}$\n"
            "━━━━━━━━━━━━━━━━\n"
            "اختر ما تريد:",
            reply_markup=main_menu_keyboard(user_id)
        )
        return MAIN_MENU
    else:
        await query.answer("❌ لم تشترك بعد في القناة!", show_alert=True)
        await query.edit_message_text(
            "🔒 الاشتراك الإجباري\n"
            "━━━━━━━━━━━━━━━━\n"
            f"لم نجد اشتراكك في {REQUIRED_CHANNEL_USERNAME}.\n"
            "اشترك ثم اضغط مرة أخرى.",
            reply_markup=subscription_keyboard()
        )
        return ConversationHandler.END

# ======================== start ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id
    args    = context.args

    existing = get_user(user_id)
    update_user(user_id, {"username": user.username, "first_name": user.first_name})

    if not await is_user_subscribed(context, user_id):
        await send_subscription_required(update)
        return ConversationHandler.END

    if args and args[0].startswith("ref_"):
        referrer_id = args[0].replace("ref_", "")
        if referrer_id != str(user_id) and existing.get("referred_by") is None:
            update_user(user_id, {"referred_by": referrer_id})
            get_user(referrer_id)
            add_referral(referrer_id, user_id)

    balance = get_user(user_id).get("balance", 0.0)
    await update.message.reply_text(
        f"👋 أهلاً {user.first_name}!\n\n"
        "🌟 مرحباً في بوت خدمات السوشيال ميديا\n"
        "━━━━━━━━━━━━━━━━\n"
        f"💳 رصيدك الحالي: {balance:.4f}$\n"
        "━━━━━━━━━━━━━━━━\n"
        "اختر ما تريد:",
        reply_markup=main_menu_keyboard(user_id)
    )
    return MAIN_MENU

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await query.edit_message_text(main_menu_text(user_id), reply_markup=main_menu_keyboard(user_id))
    return MAIN_MENU

# ======================== شحن الرصيد ========================
async def charge_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("💚 شام كاش",        callback_data="sham_cash")],
        [InlineKeyboardButton("🔵 سيرياتيل كاش",  callback_data="syriatel_cash")],
        [InlineKeyboardButton("🔙 رجوع",           callback_data="main")],
    ]
    await query.edit_message_text("💳 شحن الرصيد\n━━━━━━━━━━━━━━━━\nاختر طريقة الدفع:",
                                   reply_markup=InlineKeyboardMarkup(keyboard))
    return CHARGE_MENU

async def sham_cash_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("💵 شحن شام كاش دولار", callback_data="sham_dollar")],
        [InlineKeyboardButton("🇸🇾 شحن شام كاش سوري", callback_data="sham_syp")],
        [InlineKeyboardButton("🔙 رجوع",              callback_data="charge")],
    ]
    await query.edit_message_text("💚 شام كاش\n━━━━━━━━━━━━━━━━\nاختر نوع العملة:",
                                   reply_markup=InlineKeyboardMarkup(keyboard))
    return SHAM_MENU

async def sham_syp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["charge_type"] = "sham_syp"
    keyboard = [
        [InlineKeyboardButton("✅ تحقق من الدفع", callback_data="verify_payment")],
        [InlineKeyboardButton("🔙 رجوع",           callback_data="sham_cash")],
    ]
    await query.edit_message_text(
        f"🇸🇾 شحن شام كاش سوري\n━━━━━━━━━━━━━━━━\n"
        f"📱 حساب شام كاش:\n`{SHAM_CASH_ACCOUNT}`\n\n"
        "📌 أرسل المبلغ ثم اضغط تحقق من الدفع.",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return SHAM_MENU

async def sham_dollar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["charge_type"] = "sham_dollar"
    keyboard = [
        [InlineKeyboardButton("✅ تحقق من الدفع", callback_data="verify_payment")],
        [InlineKeyboardButton("🔙 رجوع",           callback_data="sham_cash")],
    ]
    await query.edit_message_text(
        f"💵 شحن شام كاش دولار\n━━━━━━━━━━━━━━━━\n"
        f"📱 حساب شام كاش:\n`{SHAM_CASH_ACCOUNT}`\n\n"
        "📌 أرسل المبلغ ثم اضغط تحقق من الدفع.",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return SHAM_MENU

async def syriatel_cash_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["charge_type"] = "syriatel"
    keyboard = [
        [InlineKeyboardButton("✅ تحقق من الدفع", callback_data="verify_payment")],
        [InlineKeyboardButton("🔙 رجوع",           callback_data="charge")],
    ]
    await query.edit_message_text(
        f"🔵 شحن سيرياتيل كاش\n━━━━━━━━━━━━━━━━\n"
        f"📱 حساب سيرياتيل:\n`{SYRIATEL_CASH_ACCOUNT}`\n\n"
        "📌 أرسل المبلغ ثم اضغط تحقق من الدفع.",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return CHARGE_MENU

async def verify_payment_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    charge_type = context.user_data.get("charge_type", "unknown")
    currency = {"sham_syp": "باليرة السورية", "sham_dollar": "بالدولار"}.get(charge_type, "بالليرة السورية")
    context.user_data["currency_label"] = currency
    await query.edit_message_text(
        f"📝 التحقق من الدفع\n━━━━━━━━━━━━━━━━\nأدخل المبلغ المشحون ({currency}):"
    )
    return SHAM_AMOUNT

async def receive_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        amount = float(text)
        context.user_data["pay_amount"] = amount
        await update.message.reply_text("🔢 أدخل معرّف العملية (Transaction ID):")
        return SHAM_TX_ID
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح.")
        return SHAM_AMOUNT

async def receive_tx_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tx_id       = update.message.text.strip()
    user        = update.effective_user
    amount      = context.user_data.get("pay_amount")
    charge_type = context.user_data.get("charge_type", "unknown")
    currency    = context.user_data.get("currency_label", "")
    type_name   = {"sham_syp": "شام كاش سوري 🇸🇾", "sham_dollar": "شام كاش دولار 💵",
                   "syriatel": "سيرياتيل كاش 🔵"}.get(charge_type, charge_type)
    pay_info    = {"user_id": user.id, "username": user.username or user.first_name,
                   "amount": amount, "currency": currency,
                   "charge_type": charge_type, "tx_id": tx_id}
    payment_key = f"{user.id}_{tx_id}"
    save_pending_payment(payment_key, pay_info)
    await update.message.reply_text("⏳ نعالج الدفعة، الرجاء الانتظار...")
    keyboard = [[
        InlineKeyboardButton("✅ تأكيد الدفع", callback_data=f"admin_approve_{payment_key}"),
        InlineKeyboardButton("❌ رفض الدفع",  callback_data=f"admin_reject_{payment_key}")
    ]]
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"💳 طلب شحن رصيد جديد!\n━━━━━━━━━━━━━━━━\n"
                f"👤 {user.first_name} (@{user.username or 'بدون يوزر'})\n"
                f"🆔 {user.id}\n💰 {amount} {currency}\n"
                f"🏦 {type_name}\n🔢 {tx_id}"
            ),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error sending to admin: {e}")
    return MAIN_MENU

# ======================== قرارات الأدمن للدفع ========================
async def admin_approve_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    payment_key = query.data.replace("admin_approve_", "")
    pay_info = get_pending_payment(payment_key)
    if not pay_info:
        await query.edit_message_text("⚠️ لم يتم العثور على بيانات الدفع.")
        return
    context.user_data["approving_payment_key"] = payment_key
    context.user_data["approving_pay_info"]    = pay_info
    await query.edit_message_text(
        f"✅ تأكيد الدفع\n━━━━━━━━━━━━━━━━\n"
        f"المستخدم: {pay_info['username']}\n"
        f"المبلغ: {pay_info['amount']} {pay_info['currency']}\n\n"
        "📌 أدخل المبلغ بالدولار لإضافته للرصيد:"
    )
    return ADMIN_CONFIRM_AMOUNT

async def admin_receive_dollar_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text = update.message.text.strip()
    try:
        dollar_amount = float(text)
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح.")
        return ADMIN_CONFIRM_AMOUNT
    payment_key = context.user_data.get("approving_payment_key")
    pay_info    = context.user_data.get("approving_pay_info")
    if not pay_info:
        await update.message.reply_text("⚠️ خطأ: لم يتم العثور على بيانات الدفع.")
        return MAIN_MENU
    user_id     = pay_info["user_id"]
    user_data   = get_user(user_id)
    new_balance = user_data["balance"] + dollar_amount
    referred_by = user_data.get("referred_by")
    if referred_by:
        commission     = dollar_amount * REFERRAL_COMMISSION
        ref_data       = get_user(referred_by)
        ref_new_balance= ref_data["balance"] + commission
        update_user(referred_by, {"balance": ref_new_balance})
        try:
            await context.bot.send_message(
                chat_id=int(referred_by),
                text=f"🎉 حصلت على عمولة إحالة!\n💰 {commission:.4f}$\n💳 رصيدك: {ref_new_balance:.4f}$"
            )
        except Exception as e:
            logger.error(f"Referrer notify failed: {e}")
    update_user(user_id, {"balance": new_balance})
    remove_pending_payment(payment_key)
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ تم شحن رصيدك بنجاح!\n━━━━━━━━━━━━━━━━\n"
                f"💰 المبلغ المضاف: {dollar_amount}$\n"
                f"💳 رصيدك الحالي: {new_balance:.4f}$"
            ),
            reply_markup=main_menu_keyboard(user_id)
        )
    except Exception as e:
        logger.error(f"User notify failed: {e}")
    await update.message.reply_text(
        f"✅ تمت العملية!\n━━━━━━━━━━━━━━━━\n"
        f"💳 شُحن حساب {pay_info['username']}\n"
        f"💰 المضاف: {dollar_amount}$\n"
        f"📊 رصيده الجديد: {new_balance:.4f}$",
        reply_markup=main_menu_keyboard(update.effective_user.id)
    )
    return MAIN_MENU

async def admin_reject_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    payment_key = query.data.replace("admin_reject_", "")
    pay_info = get_pending_payment(payment_key)
    if not pay_info:
        await query.edit_message_text("⚠️ لم يتم العثور على بيانات الدفع.")
        return
    remove_pending_payment(payment_key)
    try:
        await context.bot.send_message(
            chat_id=pay_info["user_id"],
            text=(
                "❌ تم رفض الدفع\n━━━━━━━━━━━━━━━━\n"
                "يرجى التحقق من المعلومات ومراسلة الدعم.\n\n"
                f"📞 الدعم: {ADMIN_USERNAME}"
            ),
            reply_markup=main_menu_keyboard(pay_info["user_id"])
        )
    except Exception as e:
        logger.error(f"User rejection notify failed: {e}")
    await query.edit_message_text(f"❌ تم رفض الدفع للمستخدم {pay_info['username']}.")

# ======================== الإحالة ========================
async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id   = query.from_user.id
    user_data = get_user(user_id)
    bot_info  = await context.bot.get_me()
    ref_link  = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    keyboard  = [
        [InlineKeyboardButton("👥 إحالاتي", callback_data="my_referrals")],
        [InlineKeyboardButton("🔙 رجوع",    callback_data="main")],
    ]
    await query.edit_message_text(
        f"👥 برنامج الإحالة\n━━━━━━━━━━━━━━━━\n"
        f"🔗 رابط الإحالة:\n`{ref_link}`\n\n"
        f"💰 عمولتك: 7% من كل شحن للمُحالين\n"
        f"👥 عدد إحالاتك: {len(user_data.get('referrals', []))}",
        reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
    )
    return MAIN_MENU

async def my_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    user_id   = query.from_user.id
    user_data = get_user(user_id)
    referrals = user_data.get("referrals", [])
    ref_list  = "\n".join([f"• مستخدم {r}" for r in referrals]) if referrals else "لا يوجد إحالات حتى الآن"
    await query.edit_message_text(
        f"👥 إحالاتي\n━━━━━━━━━━━━━━━━\n{ref_list}\n\n"
        f"💳 رصيدك: {user_data['balance']:.4f}$",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="referral")]])
    )

# ======================== الدعم ========================
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        f"📞 التواصل مع الدعم\n━━━━━━━━━━━━━━━━\n{ADMIN_USERNAME}",
        reply_markup=back_button("main")
    )
    return MAIN_MENU

# ======================== طلب الخدمات ========================
async def service_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("✈️ تيليجرام", callback_data="platform_telegram")],
        [InlineKeyboardButton("📸 انستغرام", callback_data="platform_instagram")],
        [InlineKeyboardButton("📘 فيسبوك",   callback_data="platform_facebook")],
        [InlineKeyboardButton("🔙 رجوع",     callback_data="main")],
    ]
    await query.edit_message_text("🛒 طلب خدمة\n━━━━━━━━━━━━━━━━\nاختر المنصة:",
                                   reply_markup=InlineKeyboardMarkup(keyboard))
    return SERVICE_PLATFORM

async def platform_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    platform = query.data.replace("platform_", "")
    context.user_data["platform"] = platform
    pdata = SERVICES.get(platform)
    if not pdata:
        await query.edit_message_text("❌ منصة غير معروفة.")
        return SERVICE_PLATFORM
    keyboard = []
    for cat_key, cat_data in pdata["categories"].items():
        if cat_data["services"]:
            keyboard.append([InlineKeyboardButton(cat_data["name"], callback_data=f"category_{cat_key}")])
    custom_rows = build_buttons_layout(get_custom_buttons_for_location(f"platform_{platform}"))
    keyboard.extend(custom_rows)
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="service")])
    await query.edit_message_text(
        f"🛒 {pdata['name']}\n━━━━━━━━━━━━━━━━\nاختر نوع الخدمة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SERVICE_TYPE

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    cat_key  = query.data.replace("category_", "")
    platform = context.user_data.get("platform")
    context.user_data["category"]     = cat_key
    context.user_data["svc_back_cb"]  = f"category_{cat_key}"
    pdata    = SERVICES.get(platform)
    cat_data = pdata["categories"].get(cat_key)
    fetch_provider_services()
    keyboard = []
    for svc in cat_data["services"]:
        price = get_customer_price(svc)
        keyboard.append([InlineKeyboardButton(f"{svc['name'][:40]} | {price:.4f}$/1K",
                                               callback_data=f"svc_{svc['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"platform_{platform}")])
    await query.edit_message_text(
        f"🛒 {cat_data['name']}\n━━━━━━━━━━━━━━━━\nاختر الخدمة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SERVICE_SELECT

async def custom_button_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    btn_id = query.data.replace("cbtn_", "")
    btn    = get_custom_button(btn_id)
    if not btn:
        await query.edit_message_text("❌ الزر غير موجود.", reply_markup=back_button("main"))
        return MAIN_MENU
    context.user_data["svc_back_cb"] = f"cbtn_{btn_id}"
    context.user_data["platform"]    = None
    context.user_data["category"]    = None
    fetch_provider_services()
    keyboard = []
    for sid in btn.get("service_ids", []):
        svc = build_service(sid)
        if not svc:
            continue
        price = get_customer_price(svc)
        keyboard.append([InlineKeyboardButton(f"{svc['name'][:40]} | {price:.4f}$/1K",
                                               callback_data=f"svc_{svc['id']}")])
    loc     = btn.get("location", "main")
    back_cb = loc if loc.startswith("platform_") else "main"
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_cb)])
    text = (f"🛒 {btn['name']}\n━━━━━━━━━━━━━━━━\n"
            + ("اختر الخدمة:" if btn.get("service_ids") else "⚠️ لا توجد خدمات بعد."))
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return SERVICE_SELECT

async def service_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    svc_id   = query.data.replace("svc_", "")
    platform = context.user_data.get("platform")
    cat_key  = context.user_data.get("category")
    svc = None
    if platform and cat_key:
        pdata    = SERVICES.get(platform)
        cat_data = pdata["categories"].get(cat_key) if pdata else None
        if cat_data:
            svc = next((s for s in cat_data["services"] if s["id"] == svc_id), None)
    if not svc:
        svc = build_service(svc_id)
    if not svc:
        await query.edit_message_text("❌ الخدمة غير موجودة.")
        return SERVICE_SELECT
    context.user_data["selected_service"]      = svc
    context.user_data["selected_platform_key"] = platform
    context.user_data["selected_category_key"] = cat_key
    price   = get_customer_price(svc)
    back_cb = context.user_data.get("svc_back_cb") or (f"category_{cat_key}" if cat_key else "main")
    keyboard = [
        [InlineKeyboardButton("▶️ متابعة", callback_data="proceed_order")],
        [InlineKeyboardButton("🔙 رجوع",   callback_data=back_cb)],
    ]
    await query.edit_message_text(
        f"📋 تفاصيل الخدمة\n━━━━━━━━━━━━━━━━\n"
        f"🔹 {svc['name']}\n\n"
        f"💰 السعر: {price:.4f}$ / 1000\n"
        f"📉 الحد الأدنى: {svc['min']:,}\n"
        f"📈 الحد الأقصى: {svc['max']:,}\n"
        f"⏱️ متوسط الوقت: {svc['avg_time']}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SERVICE_SELECT

async def proceed_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    svc = context.user_data.get("selected_service")
    await query.edit_message_text(
        f"📦 إدخال الكمية\n━━━━━━━━━━━━━━━━\nأدخل الكمية:\n"
        f"📉 الحد الأدنى: {svc['min']:,}\n📈 الحد الأقصى: {svc['max']:,}"
    )
    return ORDER_QUANTITY

async def receive_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    svc = context.user_data.get("selected_service")
    try:
        qty = int(update.message.text.strip())
        if qty < svc["min"] or qty > svc["max"]:
            await update.message.reply_text(
                f"❌ الكمية خارج النطاق.\n📉 {svc['min']:,}\n📈 {svc['max']:,}")
            return ORDER_QUANTITY
        context.user_data["order_qty"] = qty
        await update.message.reply_text("🔗 أدخل الرابط:")
        return ORDER_LINK
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح.")
        return ORDER_QUANTITY

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link  = update.message.text.strip()
    svc   = context.user_data.get("selected_service")
    qty   = context.user_data.get("order_qty")
    total = (get_customer_price(svc) / 1000) * qty
    context.user_data["order_link"] = link
    keyboard = [
        [InlineKeyboardButton("✅ تأكيد الطلب", callback_data="confirm_order")],
        [InlineKeyboardButton("❌ إلغاء",       callback_data="main")],
    ]
    await update.message.reply_text(
        f"📋 ملخص الطلب\n━━━━━━━━━━━━━━━━\n"
        f"🔹 {svc['name'][:50]}\n🔗 {link}\n"
        f"📦 {qty:,}\n💰 {total:.4f}$",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ORDER_CONFIRM

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    svc     = context.user_data.get("selected_service")
    qty     = context.user_data.get("order_qty")
    link    = context.user_data.get("order_link")
    total   = (get_customer_price(svc) / 1000) * qty
    udata   = get_user(user_id)
    if udata["balance"] < total:
        await query.edit_message_text(
            f"❌ رصيدك غير كافٍ!\n💳 {udata['balance']:.4f}$\n💰 مطلوب: {total:.4f}$",
            reply_markup=main_menu_keyboard(user_id)
        )
        return MAIN_MENU
    await query.edit_message_text("⏳ جارٍ تنفيذ الطلب...")
    new_balance = udata["balance"] - total
    update_user(user_id, {"balance": new_balance})
    platform_key = context.user_data.get("selected_platform_key")
    category_key = context.user_data.get("selected_category_key")
    if not platform_key or not category_key:
        platform_key, category_key, _ = find_service_by_id(svc["id"])
    smm_service_id = resolve_smm_id(svc, platform_key, category_key)
    if not smm_service_id:
        update_user(user_id, {"balance": udata["balance"]})
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ لم نجد خدمة موافقة لدى المزود. تم استرداد رصيدك.",
            reply_markup=main_menu_keyboard(user_id)
        )
        return MAIN_MENU
    result = place_order(smm_service_id, link, qty)
    if result and "order" in result:
        order_id = result["order"]
        rec = {
            "order_id": str(order_id), "smm_service_id": str(smm_service_id),
            "service_name": svc.get("name", ""), "link": link,
            "quantity": int(qty), "cost": float(total),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        u = get_user(user_id)
        orders = u.get("orders", [])
        orders.insert(0, rec)
        update_user(user_id, {"orders": orders[:100]})
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ تم تنفيذ طلبك!\n━━━━━━━━━━━━━━━━\n"
                f"🔢 {order_id}\n🔹 {svc['name'][:50]}\n"
                f"📦 {qty:,}\n💰 {total:.4f}$\n"
                f"💳 رصيدك: {new_balance:.4f}$"
            ),
            reply_markup=main_menu_keyboard(user_id)
        )
    else:
        update_user(user_id, {"balance": udata["balance"]})
        error_msg = (result.get("error", "خطأ غير معروف") if result else "فشل الاتصال")
        await context.bot.send_message(
            chat_id=user_id,
            text=f"❌ فشل تنفيذ الطلب!\n{error_msg}\nتم استرداد رصيدك.",
            reply_markup=main_menu_keyboard(user_id)
        )
    return MAIN_MENU

# ======================== حالة الطلبات ========================
STATUS_AR = {
    "pending": "قيد الانتظار ⏳", "in progress": "جاري التنفيذ 🔄",
    "processing": "قيد المعالجة 🔄", "completed": "مكتمل ✅",
    "partial": "مكتمل جزئياً ⚠️", "canceled": "ملغي ❌",
    "cancelled": "ملغي ❌", "refunded": "تم الاسترداد 💸", "fail": "فشل ❌",
}
def translate_status(s):
    return STATUS_AR.get(str(s).lower(), str(s)) if s else "غير معروف"

async def order_status_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    u = get_user(query.from_user.id)
    orders = u.get("orders", [])
    if not orders:
        await query.edit_message_text(
            "📊 حالة الطلبات\n━━━━━━━━━━━━━━━━\nلا يوجد لديك أي طلبات.",
            reply_markup=back_button("main"))
        return MAIN_MENU
    keyboard = []
    for o in orders[:15]:
        keyboard.append([InlineKeyboardButton(
            f"#{o['order_id']} | {o['quantity']:,} | {o['cost']:.4f}$",
            callback_data=f"order_view_{o['order_id']}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main")])
    await query.edit_message_text(
        f"📊 حالة الطلبات\n━━━━━━━━━━━━━━━━\nإجمالي طلباتك: {len(orders)}\nاختر طلباً:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ORDER_STATUS_LIST

async def order_view_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer("⏳ جاري جلب الحالة...")
    order_id = query.data.replace("order_view_", "")
    u        = get_user(query.from_user.id)
    rec      = next((o for o in u.get("orders", []) if str(o["order_id"]) == order_id), None)
    if not rec:
        await query.edit_message_text("❌ لم يتم العثور على الطلب.", reply_markup=back_button("order_status"))
        return ORDER_STATUS_LIST
    info     = get_order_status(order_id) or {}
    status   = translate_status(info.get("status"))
    keyboard = [
        [InlineKeyboardButton("🔄 تحديث",  callback_data=f"order_view_{order_id}")],
        [InlineKeyboardButton("🔙 رجوع",   callback_data="order_status")],
    ]
    await query.edit_message_text(
        f"📋 تفاصيل الطلب\n━━━━━━━━━━━━━━━━\n"
        f"🆔 {rec['order_id']}\n📅 {rec['date']}\n🔗 {rec['link']}\n"
        f"💰 {rec['cost']:.4f}$\n🔢 {info.get('start_count','—')}\n"
        f"📦 {rec['quantity']:,}\n🔹 {rec['service_name'][:60]}\n"
        f"📊 {status}\n⏳ {info.get('remains','—')}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ORDER_STATUS_LIST

# ======================== لوحة الأدمن ========================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    multiplier   = get_multiplier()
    users_count  = get_users_count()
    admins_count = len(get_all_admins())
    keyboard = [
        [InlineKeyboardButton("💱 تعديل ضرب السعر",        callback_data="set_multiplier")],
        [InlineKeyboardButton("💵 تعديل الأسعار",           callback_data="admin_prices")],
        [InlineKeyboardButton(f"👥 إدارة الحسابات ({users_count})", callback_data="admin_users")],
        [InlineKeyboardButton(f"🛡️ إدارة الأدمن ({admins_count})", callback_data="manage_admins")],
        [InlineKeyboardButton("📢 بث رسالة",                callback_data="admin_broadcast")],
        [InlineKeyboardButton("🧩 إدارة الأزرار",           callback_data="admin_cbtns")],
        [InlineKeyboardButton("🔙 رجوع",                    callback_data="main")],
    ]
    await query.edit_message_text(
        f"⚙️ لوحة الأدمن\n━━━━━━━━━━━━━━━━\n"
        f"💱 معامل الضرب: ×{multiplier}\n👥 المستخدمون: {users_count}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_PANEL

# ======================== إدارة الأدمن ========================
async def manage_admins_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ هذه الصفحة للأدمن الرئيسي فقط!", show_alert=True)
        return ADMIN_PANEL
    await query.answer()
    admins  = get_all_admins()
    keyboard = []
    for a in admins:
        uid  = a["user_id"]
        name = a.get("username") or uid
        if uid == str(ADMIN_ID):
            keyboard.append([InlineKeyboardButton(f"👑 {name} (رئيسي)", callback_data="noop")])
        else:
            keyboard.append([
                InlineKeyboardButton(f"🛡️ {name}", callback_data="noop"),
                InlineKeyboardButton("🗑️ حذف", callback_data=f"del_admin_{uid}"),
            ])
    keyboard.append([InlineKeyboardButton("➕ إضافة أدمن جديد", callback_data="add_admin_prompt")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع",            callback_data="admin_panel")])
    await query.edit_message_text(
        f"🛡️ إدارة الأدمن\n━━━━━━━━━━━━━━━━\n"
        f"إجمالي الأدمن: {len(admins)}\n\n"
        "اضغط 🗑️ لحذف أدمن، أو أضف واحداً جديداً:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_MANAGE_ADMINS

async def add_admin_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return ADMIN_PANEL
    await query.answer()
    await query.edit_message_text(
        "➕ إضافة أدمن جديد\n━━━━━━━━━━━━━━━━\n"
        "أرسل معرف المستخدم (User ID) الرقمي الذي تريد منحه صلاحيات الأدمن:\n\n"
        "أو /cancel للإلغاء.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="manage_admins")]])
    )
    return ADMIN_ADD_ADMIN_INPUT

async def add_admin_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text.strip()
    if text.lower() == "/cancel":
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_keyboard(ADMIN_ID))
        return MAIN_MENU
    try:
        new_admin_id = int(text)
    except ValueError:
        await update.message.reply_text("❌ يجب أن يكون معرف المستخدم رقماً صحيحاً. أعد الإرسال:")
        return ADMIN_ADD_ADMIN_INPUT
    add_admin(new_admin_id, added_by=ADMIN_ID)
    await update.message.reply_text(
        f"✅ تمت إضافة الأدمن بنجاح!\n🆔 {new_admin_id}\n\n"
        "سيتمكن هذا المستخدم من الوصول إلى لوحة الأدمن.",
        reply_markup=main_menu_keyboard(ADMIN_ID)
    )
    return MAIN_MENU

async def del_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return ADMIN_PANEL
    await query.answer()
    uid = query.data.replace("del_admin_", "")
    if uid == str(ADMIN_ID):
        await query.answer("❌ لا يمكن حذف الأدمن الرئيسي!", show_alert=True)
        return ADMIN_MANAGE_ADMINS
    remove_admin(uid)
    await query.answer(f"✅ تم حذف الأدمن {uid}", show_alert=True)
    return await manage_admins_list(update, context)

async def noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

# ======================== بث رسالة ========================
async def admin_broadcast_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(
        f"📢 بث رسالة جماعية\n━━━━━━━━━━━━━━━━\n"
        f"سيتم الإرسال إلى {get_users_count()} مستخدم.\n\n"
        "أرسل النص أو /cancel للإلغاء.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]])
    )
    return ADMIN_BROADCAST_INPUT

async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text = update.message.text
    if text and text.strip().lower() == "/cancel":
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_keyboard(update.effective_user.id))
        return MAIN_MENU
    users = get_all_users()
    await update.message.reply_text(f"⏳ جاري الإرسال إلى {len(users)} مستخدم...")
    sent = failed = 0
    for uid in users:
        try:
            await context.bot.send_message(
                chat_id=int(uid),
                text=f"📢 رسالة من الإدارة\n━━━━━━━━━━━━━━━━\n{text}"
            )
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(
        f"✅ اكتمل البث!\n📤 تم: {sent}\n⚠️ فشل: {failed}",
        reply_markup=main_menu_keyboard(update.effective_user.id)
    )
    return MAIN_MENU

# ======================== إدارة الأزرار المخصصة ========================
async def admin_cbtns_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return ADMIN_PANEL
    await query.answer()
    buttons  = get_custom_buttons()
    keyboard = [[InlineKeyboardButton("➕ إنشاء زر جديد", callback_data="cbtnnew")]]
    for b in buttons:
        loc_label = LOCATION_LABELS.get(b.get("location","main"), b.get("location",""))
        row_info  = f"صف:{b.get('row_number',0)}" if b.get("row_number", 0) else "صف مستقل"
        label     = f"{b['name']} | {loc_label} | {row_info} | ({len(b.get('service_ids',[]))})"
        keyboard.append([
            InlineKeyboardButton(label, callback_data=f"cbtnv_{b['id']}"),
            InlineKeyboardButton("⬆️",  callback_data=f"cbtnup_{b['id']}"),
            InlineKeyboardButton("⬇️",  callback_data=f"cbtndown_{b['id']}"),
        ])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])
    await query.edit_message_text(
        f"🧩 الأزرار المخصصة\n━━━━━━━━━━━━━━━━\n"
        f"إجمالي: {len(buttons)}\n\n"
        "الرقم في «صف» يحدد الصف — نفس الرقم = جنباً إلى جنب، 0 = صف مستقل:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_CBTN_LIST

async def admin_cbtn_move(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return ADMIN_CBTN_LIST
    await query.answer()
    if query.data.startswith("cbtnup_"):
        move_button_order(query.data.replace("cbtnup_", ""), -1)
    else:
        move_button_order(query.data.replace("cbtndown_", ""), 1)
    return await admin_cbtns_list(update, context)

async def admin_cbtn_new_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return ADMIN_PANEL
    await query.answer()
    await query.edit_message_text(
        "✏️ إنشاء زر جديد\n━━━━━━━━━━━━━━━━\n"
        "أرسل اسم الزر (الذي سيراه الزبون):\nأو /cancel للإلغاء.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_cbtns")]])
    )
    return ADMIN_CBTN_NAME

async def admin_cbtn_new_receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text = update.message.text.strip()
    if text.lower() == "/cancel":
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_keyboard(update.effective_user.id))
        return MAIN_MENU
    if not 1 <= len(text) <= 60:
        await update.message.reply_text("❌ الاسم يجب 1–60 حرفاً. أعد الإرسال.")
        return ADMIN_CBTN_NAME
    btn = create_custom_button(text, location="main")
    context.user_data["cbtn_id"] = btn["id"]
    await update.message.reply_text(
        f"✅ تم إنشاء الزر «{btn['name']}»!\n"
        "الموقع: 🏠 القائمة الرئيسية | صف مستقل\n"
        "يمكنك تعديله الآن:",
        reply_markup=_cbtn_view_keyboard(btn["id"])
    )
    return ADMIN_CBTN_VIEW

def _cbtn_view_keyboard(btn_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة خدمة",   callback_data=f"cbtnsvc_add_{btn_id}")],
        [InlineKeyboardButton("📋 إدارة الخدمات",callback_data=f"cbtnsvc_list_{btn_id}")],
        [InlineKeyboardButton("📍 تغيير الموقع", callback_data=f"cbtnloc_{btn_id}")],
        [InlineKeyboardButton("📐 تغيير الصف",   callback_data=f"cbtnrow_{btn_id}")],
        [InlineKeyboardButton("✏️ تعديل الاسم",  callback_data=f"cbtnren_{btn_id}")],
        [InlineKeyboardButton("🗑️ حذف الزر",    callback_data=f"cbtndel_{btn_id}")],
        [InlineKeyboardButton("🔙 رجوع",         callback_data="admin_cbtns")],
    ])

async def admin_cbtn_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return ADMIN_PANEL
    await query.answer()
    btn_id = query.data.replace("cbtnv_", "")
    btn    = get_custom_button(btn_id)
    if not btn:
        await query.edit_message_text("❌ الزر غير موجود.", reply_markup=back_button("admin_cbtns"))
        return ADMIN_CBTN_LIST
    context.user_data["cbtn_id"] = btn_id
    loc_label = LOCATION_LABELS.get(btn.get("location","main"), btn.get("location",""))
    row_info  = f"صف رقم {btn.get('row_number',0)} (مع أزرار أخرى)" if btn.get("row_number",0) else "صف مستقل"
    await query.edit_message_text(
        f"🧩 إدارة الزر\n━━━━━━━━━━━━━━━━\n"
        f"📛 الاسم: {btn['name']}\n"
        f"📍 الموقع: {loc_label}\n"
        f"📐 التخطيط: {row_info}\n"
        f"🛒 عدد الخدمات: {len(btn.get('service_ids',[]))}",
        reply_markup=_cbtn_view_keyboard(btn_id)
    )
    return ADMIN_CBTN_VIEW

async def admin_cbtn_change_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    btn_id = query.data.replace("cbtnloc_", "")
    context.user_data["cbtn_id"] = btn_id
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"cbtnsetloc_{btn_id}_{loc_key}")]
        for loc_key, label in LOCATION_LABELS.items()
    ]
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"cbtnv_{btn_id}")])
    await query.edit_message_text(
        "📍 اختر موقع الزر:", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_CBTN_VIEW

async def admin_cbtn_set_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    parts  = query.data.replace("cbtnsetloc_", "").split("_", 1)
    btn_id = parts[0]
    loc    = parts[1]
    update_custom_button(btn_id, {"location": loc})
    btn       = get_custom_button(btn_id)
    loc_label = LOCATION_LABELS.get(btn.get("location"), btn.get("location",""))
    await query.edit_message_text(
        f"✅ تم تحديث الموقع إلى: {loc_label}",
        reply_markup=_cbtn_view_keyboard(btn_id)
    )
    return ADMIN_CBTN_VIEW

async def admin_cbtn_row_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """طلب رقم الصف لتحديد التخطيط."""
    query  = update.callback_query
    await query.answer()
    btn_id = query.data.replace("cbtnrow_", "")
    context.user_data["cbtn_id"] = btn_id
    btn    = get_custom_button(btn_id)
    await query.edit_message_text(
        f"📐 تغيير الصف للزر «{btn['name'] if btn else btn_id}»\n"
        "━━━━━━━━━━━━━━━━\n"
        "رقم الصف يحدد كيف يظهر الزر في القائمة:\n\n"
        "• 0 = صف مستقل (الزر وحده في السطر)\n"
        "• 1 = الصف الأول (يظهر مع الأزرار التي رقمها 1 أيضاً جنباً إلى جنب)\n"
        "• 2 = الصف الثاني (وهكذا...)\n\n"
        "أرسل رقم الصف (0 أو أي رقم موجب):\nأو /cancel للإلغاء.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"cbtnv_{btn_id}")]])
    )
    return ADMIN_CBTN_ROW_INPUT

async def admin_cbtn_row_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text   = update.message.text.strip()
    btn_id = context.user_data.get("cbtn_id")
    if text.lower() == "/cancel" or not btn_id:
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_keyboard(update.effective_user.id))
        return MAIN_MENU
    try:
        row_num = int(text)
        if row_num < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح (0 أو أكبر).")
        return ADMIN_CBTN_ROW_INPUT
    update_custom_button(btn_id, {"row_number": row_num})
    row_info = f"صف رقم {row_num}" if row_num else "صف مستقل"
    await update.message.reply_text(
        f"✅ تم تحديث التخطيط: {row_info}",
        reply_markup=_cbtn_view_keyboard(btn_id)
    )
    return ADMIN_CBTN_VIEW

async def admin_cbtn_rename_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    btn_id = query.data.replace("cbtnren_", "")
    context.user_data["cbtn_id"] = btn_id
    await query.edit_message_text(
        "✏️ تعديل الاسم\n━━━━━━━━━━━━━━━━\nأرسل الاسم الجديد أو /cancel:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"cbtnv_{btn_id}")]])
    )
    return ADMIN_CBTN_RENAME

async def admin_cbtn_rename_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text   = update.message.text.strip()
    btn_id = context.user_data.get("cbtn_id")
    if text.lower() == "/cancel" or not btn_id:
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_keyboard(update.effective_user.id))
        return MAIN_MENU
    if not 1 <= len(text) <= 60:
        await update.message.reply_text("❌ الاسم يجب 1–60 حرفاً.")
        return ADMIN_CBTN_RENAME
    update_custom_button(btn_id, {"name": text})
    await update.message.reply_text(f"✅ تم تحديث الاسم: «{text}»",
                                     reply_markup=_cbtn_view_keyboard(btn_id))
    return ADMIN_CBTN_VIEW

async def admin_cbtn_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    btn_id = query.data.replace("cbtndel_", "")
    btn    = get_custom_button(btn_id)
    if not btn:
        await query.edit_message_text("❌ الزر غير موجود.", reply_markup=back_button("admin_cbtns"))
        return ADMIN_CBTN_LIST
    delete_custom_button(btn_id)
    await query.edit_message_text(f"🗑️ تم حذف الزر «{btn['name']}».")
    return await admin_cbtns_list(update, context)

async def admin_cbtn_add_svc_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    btn_id = query.data.replace("cbtnsvc_add_", "")
    context.user_data["cbtn_id"] = btn_id
    await query.edit_message_text(
        "➕ إضافة خدمة للزر\n━━━━━━━━━━━━━━━━\n"
        "أرسل معرف الخدمة (رقم) كما هو لدى المزود.\n"
        "أو /cancel للإلغاء.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"cbtnv_{btn_id}")]])
    )
    return ADMIN_CBTN_ADD_SVC

async def admin_cbtn_add_svc_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text   = update.message.text.strip()
    btn_id = context.user_data.get("cbtn_id")
    if text.lower() == "/cancel" or not btn_id:
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_keyboard(update.effective_user.id))
        return MAIN_MENU
    try:
        sid = int(text)
    except ValueError:
        await update.message.reply_text("❌ الرجاء إرسال رقم صحيح.")
        return ADMIN_CBTN_ADD_SVC
    info = get_provider_service(sid)
    if not info:
        await update.message.reply_text(f"❌ لم أجد خدمة بمعرف ({sid}) لدى المزود. أعد الإرسال أو /cancel.")
        return ADMIN_CBTN_ADD_SVC
    btn  = get_custom_button(btn_id)
    sids = btn.get("service_ids", [])
    if sid in sids:
        await update.message.reply_text("⚠️ هذه الخدمة موجودة مسبقاً.", reply_markup=_cbtn_view_keyboard(btn_id))
        return ADMIN_CBTN_VIEW
    sids.append(sid)
    update_custom_button(btn_id, {"service_ids": sids})
    multiplier     = get_multiplier()
    customer_price = float(info.get("rate", 0)) * multiplier
    await update.message.reply_text(
        f"✅ تمت إضافة الخدمة!\n━━━━━━━━━━━━━━━━\n"
        f"🆔 {sid}\n🔹 {info.get('name','')[:80]}\n"
        f"💰 سعر المزود: {info.get('rate')}$/1K\n"
        f"💵 سعر الزبون: {customer_price:.4f}$/1K\n"
        f"📉 {info.get('min'):,}  📈 {info.get('max'):,}",
        reply_markup=_cbtn_view_keyboard(btn_id)
    )
    return ADMIN_CBTN_VIEW

async def admin_cbtn_list_svc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query  = update.callback_query
    await query.answer()
    btn_id = query.data.replace("cbtnsvc_list_", "")
    btn    = get_custom_button(btn_id)
    if not btn:
        await query.edit_message_text("❌ الزر غير موجود.", reply_markup=back_button("admin_cbtns"))
        return ADMIN_CBTN_LIST
    context.user_data["cbtn_id"] = btn_id
    sids     = btn.get("service_ids", [])
    keyboard = []
    for sid in sids:
        info = get_provider_service(sid) or {}
        nm   = info.get("name", f"#{sid}")[:35]
        keyboard.append([InlineKeyboardButton(f"🗑️ {sid} | {nm}", callback_data=f"cbtnsvc_del_{btn_id}_{sid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"cbtnv_{btn_id}")])
    await query.edit_message_text(
        f"📋 خدمات الزر «{btn['name']}»\n━━━━━━━━━━━━━━━━\n"
        f"العدد: {len(sids)}\n" + ("اضغط على خدمة لحذفها." if sids else "لا توجد خدمات."),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_CBTN_VIEW

async def admin_cbtn_del_svc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🗑️ تم الحذف")
    rest   = query.data.replace("cbtnsvc_del_", "")
    btn_id, sid_str = rest.split("_", 1)
    try:
        sid = int(sid_str)
    except ValueError:
        return ADMIN_CBTN_VIEW
    btn  = get_custom_button(btn_id)
    if not btn:
        return ADMIN_CBTN_LIST
    sids = [s for s in btn.get("service_ids", []) if s != sid]
    update_custom_button(btn_id, {"service_ids": sids})
    query.data = f"cbtnsvc_list_{btn_id}"
    return await admin_cbtn_list_svc(update, context)

# ======================== إدارة حسابات المستخدمين ========================
USERS_PAGE_SIZE = 10

def _user_label(uid, info):
    bal  = info.get("balance", 0.0)
    name = info.get("username") or info.get("first_name") or uid
    return f"{name} | {uid} | {bal:.2f}$"

async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page=0):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return ADMIN_PANEL
    await query.answer()
    if query.data and query.data.startswith("users_page_"):
        try:
            page = int(query.data.replace("users_page_", ""))
        except ValueError:
            page = 0
    users    = get_all_users()
    items    = sorted(users.items(), key=lambda x: x[0])
    total    = len(items)
    start    = page * USERS_PAGE_SIZE
    end      = start + USERS_PAGE_SIZE
    keyboard = [[InlineKeyboardButton("🔍 بحث عن مستخدم", callback_data="users_search")]]
    for uid, info in items[start:end]:
        keyboard.append([InlineKeyboardButton(_user_label(uid, info), callback_data=f"user_view_{uid}")])
    nav = []
    if start > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"users_page_{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"users_page_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])
    pages = max(1, (total + USERS_PAGE_SIZE - 1) // USERS_PAGE_SIZE)
    await query.edit_message_text(
        f"👥 إدارة الحسابات\n━━━━━━━━━━━━━━━━\n"
        f"إجمالي: {total} | الصفحة {page+1}/{pages}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_USERS_LIST

async def admin_users_search_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(
        "🔍 بحث عن مستخدم\n━━━━━━━━━━━━━━━━\nأدخل ID أو اسم أو يوزرنيم:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]])
    )
    return ADMIN_USERS_SEARCH

async def admin_users_search_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    q       = update.message.text.strip().lower().lstrip("@")
    users   = get_all_users()
    matches = []
    for uid, info in users.items():
        if (q == uid or q in (info.get("username") or "").lower()
                     or q in (info.get("first_name") or "").lower()):
            matches.append((uid, info))
    if not matches:
        await update.message.reply_text(
            "❌ لا توجد نتائج.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]])
        )
        return ADMIN_USERS_LIST
    keyboard = [[InlineKeyboardButton(_user_label(uid, info), callback_data=f"user_view_{uid}")]
                for uid, info in matches[:30]]
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")])
    await update.message.reply_text(
        f"🔍 نتائج البحث ({len(matches)}):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_USERS_LIST

async def admin_user_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    uid  = query.data.replace("user_view_", "")
    info = get_user(int(uid)) if uid.isdigit() else get_all_users().get(uid, {})
    context.user_data["managed_user_id"] = uid
    name = info.get("username") or info.get("first_name") or uid
    keyboard = [
        [InlineKeyboardButton("✏️ تعديل الرصيد", callback_data="user_edit_balance")],
        [InlineKeyboardButton("🔙 رجوع",          callback_data="admin_users")],
    ]
    await query.edit_message_text(
        f"👤 بيانات المستخدم\n━━━━━━━━━━━━━━━━\n"
        f"🆔 {uid}\n👤 {name}\n"
        f"💳 {info.get('balance',0.0):.4f}$\n"
        f"👥 إحالات: {len(info.get('referrals',[]))}\n"
        f"🔗 محال من: {info.get('referred_by') or 'لا أحد'}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_USER_VIEW

async def admin_user_edit_balance_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    uid  = context.user_data.get("managed_user_id")
    info = get_user(int(uid)) if str(uid).isdigit() else {}
    await query.edit_message_text(
        f"✏️ تعديل رصيد {uid}\n━━━━━━━━━━━━━━━━\n"
        f"💳 الحالي: {info.get('balance',0.0):.4f}$\n\n"
        "• رقم بدون إشارة = ضبط على هذا المبلغ\n"
        "• +5 = إضافة 5$\n• -3 = خصم 3$"
    )
    return ADMIN_USER_EDIT_BALANCE

async def admin_user_edit_balance_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text = update.message.text.strip()
    uid  = context.user_data.get("managed_user_id")
    if not uid:
        await update.message.reply_text("⚠️ خطأ.")
        return ADMIN_PANEL
    info    = get_user(int(uid)) if str(uid).isdigit() else {}
    current = info.get("balance", 0.0)
    try:
        if text.startswith("+"):
            new_balance = current + float(text[1:])
            label = f"+{float(text[1:]):.4f}$"
        elif text.startswith("-"):
            new_balance = current - float(text[1:])
            label = f"-{float(text[1:]):.4f}$"
        else:
            new_balance = float(text)
            label = f"ضبط على {new_balance:.4f}$"
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح.")
        return ADMIN_USER_EDIT_BALANCE
    update_user(int(uid), {"balance": new_balance})
    try:
        await context.bot.send_message(
            chat_id=int(uid),
            text=f"💳 تم تحديث رصيدك من قبل الإدارة\n━━━━━━━━━━━━━━━━\n💰 رصيدك: {new_balance:.4f}$",
            reply_markup=main_menu_keyboard(int(uid))
        )
    except Exception as e:
        logger.error(f"Balance notify failed: {e}")
    await update.message.reply_text(
        f"✅ تم تحديث رصيد {uid}\n📌 {label}\n💳 الجديد: {new_balance:.4f}$",
        reply_markup=main_menu_keyboard(update.effective_user.id)
    )
    return MAIN_MENU

# ======================== تعديل أسعار الخدمات ========================
async def admin_prices_platforms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    keyboard = [
        [InlineKeyboardButton(pdata["name"], callback_data=f"adminprice_p_{pkey}")]
        for pkey, pdata in SERVICES.items()
    ]
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])
    await query.edit_message_text("💵 تعديل الأسعار\n━━━━━━━━━━━━━━━━\nاختر المنصة:",
                                   reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_PRICES_PLATFORM

async def admin_prices_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    pkey  = query.data.replace("adminprice_p_", "")
    context.user_data["admin_price_platform"] = pkey
    pdata = SERVICES.get(pkey)
    keyboard = [
        [InlineKeyboardButton(cdata["name"], callback_data=f"adminprice_c_{ckey}")]
        for ckey, cdata in pdata["categories"].items() if cdata["services"]
    ]
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_prices")])
    await query.edit_message_text(f"💵 {pdata['name']}\n━━━━━━━━━━━━━━━━\nاختر التصنيف:",
                                   reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_PRICES_CATEGORY

async def admin_prices_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    ckey  = query.data.replace("adminprice_c_", "")
    context.user_data["admin_price_category"] = ckey
    pkey  = context.user_data.get("admin_price_platform")
    pdata = SERVICES.get(pkey)
    cdata = pdata["categories"].get(ckey)
    keyboard = []
    for svc in cdata["services"]:
        cur  = get_customer_price(svc)
        mark = "✏️" if get_custom_price(svc["id"]) is not None else ""
        keyboard.append([InlineKeyboardButton(f"{mark}{svc['name'][:35]} | {cur:.4f}$",
                                               callback_data=f"adminprice_s_{svc['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"adminprice_p_{pkey}")])
    await query.edit_message_text(
        f"💵 {cdata['name']}\n━━━━━━━━━━━━━━━━\nاختر الخدمة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_PRICES_SERVICE

async def admin_price_edit_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    svc_id = query.data.replace("adminprice_s_", "")
    context.user_data["admin_price_svc_id"] = svc_id
    _, _, svc = find_service_by_id(svc_id)
    if not svc:
        await query.edit_message_text("❌ الخدمة غير موجودة.")
        return ADMIN_PANEL
    custom         = get_custom_price(svc_id)
    provider_price = get_live_price(svc)
    customer_price = get_customer_price(svc)
    keyboard = [
        [InlineKeyboardButton("♻️ إزالة السعر المخصص", callback_data="adminprice_clear")],
        [InlineKeyboardButton("🔙 رجوع",
            callback_data=f"adminprice_c_{context.user_data.get('admin_price_category')}")],
    ]
    await query.edit_message_text(
        f"✏️ تعديل سعر الخدمة\n━━━━━━━━━━━━━━━━\n"
        f"🔹 {svc['name']}\n"
        f"📦 سعر المزود: {provider_price:.4f}$/1000\n"
        f"💱 المعامل: ×{get_multiplier()}\n"
        f"💰 سعر الزبون: {customer_price:.4f}$/1000\n"
        f"{'✏️ سعر مخصص: ' + str(custom) + '$' if custom is not None else '⚙️ تلقائي'}\n\n"
        "أدخل السعر الجديد للزبون لكل 1000:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_PRICE_EDIT

async def admin_price_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer("✅ تمت إزالة السعر المخصص", show_alert=True)
    svc_id = context.user_data.get("admin_price_svc_id")
    if svc_id:
        clear_custom_price(svc_id)
    ckey  = context.user_data.get("admin_price_category")
    pkey  = context.user_data.get("admin_price_platform")
    pdata = SERVICES.get(pkey)
    cdata = pdata["categories"].get(ckey)
    keyboard = []
    for svc in cdata["services"]:
        cur  = get_customer_price(svc)
        mark = "✏️" if get_custom_price(svc["id"]) is not None else ""
        keyboard.append([InlineKeyboardButton(f"{mark}{svc['name'][:35]} | {cur:.4f}$",
                                               callback_data=f"adminprice_s_{svc['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"adminprice_p_{pkey}")])
    await query.edit_message_text(
        f"💵 {cdata['name']}\n━━━━━━━━━━━━━━━━\nاختر الخدمة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_PRICES_SERVICE

async def admin_price_edit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text = update.message.text.strip()
    try:
        new_price = float(text)
        if new_price < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح (≥ 0).")
        return ADMIN_PRICE_EDIT
    svc_id = context.user_data.get("admin_price_svc_id")
    if not svc_id:
        await update.message.reply_text("⚠️ خطأ.")
        return MAIN_MENU
    set_custom_price(svc_id, new_price)
    _, _, svc = find_service_by_id(svc_id)
    await update.message.reply_text(
        f"✅ تم تحديث السعر!\n🔹 {svc['name'] if svc else svc_id}\n"
        f"💰 {new_price:.4f}$/1000",
        reply_markup=main_menu_keyboard(update.effective_user.id)
    )
    return MAIN_MENU

async def set_multiplier_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(
        f"💱 تعديل معامل ضرب السعر\n━━━━━━━━━━━━━━━━\n"
        f"المعامل الحالي: ×{get_multiplier()}\n\n"
        "أدخل القيمة الجديدة (مثال: 2.5):"
    )
    return ADMIN_MULTIPLIER

async def receive_multiplier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text = update.message.text.strip()
    try:
        val = float(text)
        if val <= 0:
            await update.message.reply_text("❌ يجب أن تكون القيمة > 0.")
            return ADMIN_MULTIPLIER
        set_multiplier(val)
        await update.message.reply_text(
            f"✅ تم تحديث المعامل: ×{val}",
            reply_markup=main_menu_keyboard(update.effective_user.id)
        )
        return MAIN_MENU
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح.")
        return ADMIN_MULTIPLIER

# ======================== تشغيل البوت ========================
async def post_init(application):
    await application.bot.set_my_commands([
        BotCommand("start", "🚀 بدء استخدام البوت / القائمة الرئيسية"),
    ])

def main():
    init_db()
    logger.info("🤖 Starting bot with PostgreSQL backend...")

    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(charge_menu,         pattern="^charge$"),
                CallbackQueryHandler(service_menu,        pattern="^service$"),
                CallbackQueryHandler(order_status_menu,   pattern="^order_status$"),
                CallbackQueryHandler(referral_menu,       pattern="^referral$"),
                CallbackQueryHandler(support,             pattern="^support$"),
                CallbackQueryHandler(admin_panel,         pattern="^admin_panel$"),
                CallbackQueryHandler(custom_button_selected, pattern="^cbtn_[a-f0-9]+$"),
                CallbackQueryHandler(show_main_menu,      pattern="^main$"),
            ],
            CHARGE_MENU: [
                CallbackQueryHandler(sham_cash_menu,      pattern="^sham_cash$"),
                CallbackQueryHandler(syriatel_cash_menu,  pattern="^syriatel_cash$"),
                CallbackQueryHandler(verify_payment_start,pattern="^verify_payment$"),
                CallbackQueryHandler(show_main_menu,      pattern="^main$"),
            ],
            SHAM_MENU: [
                CallbackQueryHandler(sham_syp,            pattern="^sham_syp$"),
                CallbackQueryHandler(sham_dollar,         pattern="^sham_dollar$"),
                CallbackQueryHandler(charge_menu,         pattern="^charge$"),
                CallbackQueryHandler(sham_cash_menu,      pattern="^sham_cash$"),
                CallbackQueryHandler(verify_payment_start,pattern="^verify_payment$"),
                CallbackQueryHandler(show_main_menu,      pattern="^main$"),
            ],
            SHAM_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)],
            SHAM_TX_ID:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_tx_id)],
            SERVICE_PLATFORM: [
                CallbackQueryHandler(platform_selected,   pattern="^platform_"),
                CallbackQueryHandler(service_menu,        pattern="^service$"),
                CallbackQueryHandler(show_main_menu,      pattern="^main$"),
            ],
            SERVICE_TYPE: [
                CallbackQueryHandler(category_selected,   pattern="^category_"),
                CallbackQueryHandler(platform_selected,   pattern="^platform_"),
                CallbackQueryHandler(custom_button_selected, pattern="^cbtn_[a-f0-9]+$"),
                CallbackQueryHandler(service_menu,        pattern="^service$"),
                CallbackQueryHandler(show_main_menu,      pattern="^main$"),
            ],
            SERVICE_SELECT: [
                CallbackQueryHandler(service_selected,    pattern="^svc_"),
                CallbackQueryHandler(proceed_order,       pattern="^proceed_order$"),
                CallbackQueryHandler(category_selected,   pattern="^category_"),
                CallbackQueryHandler(platform_selected,   pattern="^platform_"),
                CallbackQueryHandler(custom_button_selected, pattern="^cbtn_[a-f0-9]+$"),
                CallbackQueryHandler(show_main_menu,      pattern="^main$"),
            ],
            ORDER_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_quantity)],
            ORDER_LINK:     [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            ORDER_CONFIRM: [
                CallbackQueryHandler(confirm_order,       pattern="^confirm_order$"),
                CallbackQueryHandler(show_main_menu,      pattern="^main$"),
            ],
            ADMIN_PANEL: [
                CallbackQueryHandler(set_multiplier_prompt,   pattern="^set_multiplier$"),
                CallbackQueryHandler(admin_users_list,        pattern="^admin_users$"),
                CallbackQueryHandler(admin_prices_platforms,  pattern="^admin_prices$"),
                CallbackQueryHandler(admin_broadcast_prompt,  pattern="^admin_broadcast$"),
                CallbackQueryHandler(admin_cbtns_list,        pattern="^admin_cbtns$"),
                CallbackQueryHandler(manage_admins_list,      pattern="^manage_admins$"),
                CallbackQueryHandler(admin_panel,             pattern="^admin_panel$"),
                CallbackQueryHandler(show_main_menu,          pattern="^main$"),
            ],
            ADMIN_MANAGE_ADMINS: [
                CallbackQueryHandler(add_admin_prompt,     pattern="^add_admin_prompt$"),
                CallbackQueryHandler(del_admin_callback,   pattern="^del_admin_"),
                CallbackQueryHandler(noop_callback,        pattern="^noop$"),
                CallbackQueryHandler(manage_admins_list,   pattern="^manage_admins$"),
                CallbackQueryHandler(admin_panel,          pattern="^admin_panel$"),
            ],
            ADMIN_ADD_ADMIN_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_receive),
                CallbackQueryHandler(manage_admins_list,   pattern="^manage_admins$"),
                CommandHandler("cancel", show_main_menu),
            ],
            ADMIN_CBTN_LIST: [
                CallbackQueryHandler(admin_cbtn_new_prompt, pattern="^cbtnnew$"),
                CallbackQueryHandler(admin_cbtn_view,       pattern="^cbtnv_"),
                CallbackQueryHandler(admin_cbtn_move,       pattern="^cbtnup_"),
                CallbackQueryHandler(admin_cbtn_move,       pattern="^cbtndown_"),
                CallbackQueryHandler(admin_cbtns_list,      pattern="^admin_cbtns$"),
                CallbackQueryHandler(admin_panel,           pattern="^admin_panel$"),
            ],
            ADMIN_CBTN_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_cbtn_new_receive_name),
                CallbackQueryHandler(admin_cbtns_list,      pattern="^admin_cbtns$"),
                CommandHandler("cancel", show_main_menu),
            ],
            ADMIN_CBTN_VIEW: [
                CallbackQueryHandler(admin_cbtn_add_svc_prompt, pattern="^cbtnsvc_add_"),
                CallbackQueryHandler(admin_cbtn_list_svc,       pattern="^cbtnsvc_list_"),
                CallbackQueryHandler(admin_cbtn_del_svc,        pattern="^cbtnsvc_del_"),
                CallbackQueryHandler(admin_cbtn_change_loc,     pattern="^cbtnloc_"),
                CallbackQueryHandler(admin_cbtn_set_loc,        pattern="^cbtnsetloc_"),
                CallbackQueryHandler(admin_cbtn_row_prompt,     pattern="^cbtnrow_"),
                CallbackQueryHandler(admin_cbtn_rename_prompt,  pattern="^cbtnren_"),
                CallbackQueryHandler(admin_cbtn_delete,         pattern="^cbtndel_"),
                CallbackQueryHandler(admin_cbtn_view,           pattern="^cbtnv_"),
                CallbackQueryHandler(admin_cbtns_list,          pattern="^admin_cbtns$"),
            ],
            ADMIN_CBTN_RENAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_cbtn_rename_receive),
                CallbackQueryHandler(admin_cbtn_view,   pattern="^cbtnv_"),
                CommandHandler("cancel", show_main_menu),
            ],
            ADMIN_CBTN_ADD_SVC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_cbtn_add_svc_receive),
                CallbackQueryHandler(admin_cbtn_view,   pattern="^cbtnv_"),
                CommandHandler("cancel", show_main_menu),
            ],
            ADMIN_CBTN_ROW_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_cbtn_row_receive),
                CallbackQueryHandler(admin_cbtn_view,   pattern="^cbtnv_"),
                CommandHandler("cancel", show_main_menu),
            ],
            ADMIN_BROADCAST_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_send),
                CallbackQueryHandler(admin_panel,       pattern="^admin_panel$"),
                CommandHandler("cancel", show_main_menu),
            ],
            ORDER_STATUS_LIST: [
                CallbackQueryHandler(order_view_detail,   pattern="^order_view_"),
                CallbackQueryHandler(order_status_menu,   pattern="^order_status$"),
                CallbackQueryHandler(show_main_menu,      pattern="^main$"),
            ],
            ADMIN_MULTIPLIER:       [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_multiplier)],
            ADMIN_CONFIRM_AMOUNT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_dollar_amount)],
            ADMIN_USERS_LIST: [
                CallbackQueryHandler(admin_users_list,          pattern="^admin_users$"),
                CallbackQueryHandler(admin_users_list,          pattern="^users_page_"),
                CallbackQueryHandler(admin_users_search_prompt, pattern="^users_search$"),
                CallbackQueryHandler(admin_user_view,           pattern="^user_view_"),
                CallbackQueryHandler(admin_panel,               pattern="^admin_panel$"),
            ],
            ADMIN_USERS_SEARCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_users_search_receive),
                CallbackQueryHandler(admin_users_list,  pattern="^admin_users$"),
            ],
            ADMIN_USER_VIEW: [
                CallbackQueryHandler(admin_user_edit_balance_prompt, pattern="^user_edit_balance$"),
                CallbackQueryHandler(admin_users_list,               pattern="^admin_users$"),
            ],
            ADMIN_USER_EDIT_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_user_edit_balance_receive)],
            ADMIN_PRICES_PLATFORM: [
                CallbackQueryHandler(admin_prices_categories, pattern="^adminprice_p_"),
                CallbackQueryHandler(admin_panel,             pattern="^admin_panel$"),
            ],
            ADMIN_PRICES_CATEGORY: [
                CallbackQueryHandler(admin_prices_services,  pattern="^adminprice_c_"),
                CallbackQueryHandler(admin_prices_platforms, pattern="^admin_prices$"),
            ],
            ADMIN_PRICES_SERVICE: [
                CallbackQueryHandler(admin_price_edit_prompt, pattern="^adminprice_s_"),
                CallbackQueryHandler(admin_prices_categories, pattern="^adminprice_p_"),
            ],
            ADMIN_PRICE_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_price_edit_receive),
                CallbackQueryHandler(admin_price_clear,       pattern="^adminprice_clear$"),
                CallbackQueryHandler(admin_prices_services,   pattern="^adminprice_c_"),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_user=True, per_chat=True, allow_reentry=True,
    )

    admin_payment_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_approve_payment, pattern="^admin_approve_")],
        states={
            ADMIN_CONFIRM_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_dollar_amount)],
        },
        fallbacks=[CommandHandler("start", start)],
        per_user=True, per_chat=True, allow_reentry=True,
    )

    application.add_handler(admin_payment_conv)
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_subscription$"))
    application.add_handler(CallbackQueryHandler(admin_reject_payment,         pattern="^admin_reject_"))
    application.add_handler(CallbackQueryHandler(my_referrals,                 pattern="^my_referrals$"))

    logger.info("🤖 Bot is running with PostgreSQL + admin management + dynamic button layout")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
