import logging
import requests
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ======================== إعدادات البوت ========================
BOT_TOKEN = "8697459386:AAGyan3a_UCf9oodPD96NEYAd3s1eyR7geo"
ADMIN_ID = 7632911735
ADMIN_USERNAME = "@VIP10ADMIN"
SMM_API_KEY = "e7c929c6ff91fa7b91f945f59d726348"
SMM_API_URL = "https://boostprovider.com/api/v2"
SHAM_CASH_ACCOUNT = "faff24e005ce48a4528f18674ad95967"
SYRIATEL_CASH_ACCOUNT = "38090777"
REFERRAL_COMMISSION = 0.07  # 7%
DATA_FILE = "data.json"

# ======================== الاشتراك الإجباري ========================
REQUIRED_CHANNEL_ID = -1003772429885
REQUIRED_CHANNEL_URL = "https://t.me/VIPBOST10"
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
) = range(32)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ======================== قاعدة البيانات البسيطة ========================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "users": {},
        "pending_payments": {},
        "settings": {"price_multiplier": 2.0},
        "referrals": {}
    }

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(user_id):
    data = load_data()
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "balance": 0.0,
            "referral_balance": 0.0,
            "referred_by": None,
            "referrals": []
        }
        save_data(data)
    return data["users"][uid]

def update_user(user_id, updates):
    data = load_data()
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {"balance": 0.0, "referral_balance": 0.0, "referred_by": None, "referrals": []}
    data["users"][uid].update(updates)
    save_data(data)

def get_multiplier():
    data = load_data()
    return data["settings"].get("price_multiplier", 2.0)

def set_multiplier(val):
    data = load_data()
    data["settings"]["price_multiplier"] = val
    save_data(data)

def save_pending_payment(payment_id, info):
    data = load_data()
    data["pending_payments"][str(payment_id)] = info
    save_data(data)

def get_pending_payment(payment_id):
    data = load_data()
    return data["pending_payments"].get(str(payment_id))

def remove_pending_payment(payment_id):
    data = load_data()
    data["pending_payments"].pop(str(payment_id), None)
    save_data(data)

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
    return smm_request("add", {
        "service": service_id,
        "link": link,
        "quantity": quantity
    })

def get_order_status(order_id):
    """يجلب حالة الطلب من المزود."""
    return smm_request("status", {"order": order_id})

# ======================== كاش أسعار المزود ========================
import time
_services_cache = {"data": None, "ts": 0}
SERVICES_CACHE_TTL = 300  # 5 دقائق

def fetch_provider_services(force=False):
    """يجلب قائمة خدمات المزود ويخزنها مؤقتاً"""
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

def get_custom_price(svc_id):
    data = load_data()
    return data.get("custom_prices", {}).get(str(svc_id))

def set_custom_price(svc_id, price):
    data = load_data()
    data.setdefault("custom_prices", {})[str(svc_id)] = float(price)
    save_data(data)

def clear_custom_price(svc_id):
    data = load_data()
    data.setdefault("custom_prices", {}).pop(str(svc_id), None)
    save_data(data)

def get_live_price(svc):
    """يعيد سعر المزود الحي (لكل 1000) إن توفر، وإلا السعر المحلي."""
    smm_id = svc.get("smm_id")
    if smm_id:
        services = fetch_provider_services()
        info = services.get(str(smm_id))
        if info and info.get("rate"):
            return info["rate"]
    return svc.get("price_per_1000", 0.0)

def get_customer_price(svc):
    """سعر الزبون = سعر مخصص (إن وُجد) أو سعر المزود × معامل الأدمن."""
    custom = get_custom_price(svc["id"])
    if custom is not None:
        return custom
    return get_live_price(svc) * get_multiplier()

PLATFORM_KEYWORDS = {
    "instagram": ["instagram", "insta", "ig "],
    "facebook": ["facebook", "fb "],
    "telegram": ["telegram", "tg "],
}

CATEGORY_KEYWORDS = {
    "followers": ["follower", "followers", "subscriber", "subscribers", "member", "members"],
    "reactions": ["like", "likes", "reaction", "reactions", "view", "views", "love", "haha", "wow", "angry", "sad", "share", "shares"],
    "comments": ["comment", "comments"],
}

def _name_matches(name, keywords):
    n = (name or "").lower()
    return any(k in n for k in keywords)

def resolve_smm_id(svc, platform_key, category_key):
    """يحاول إيجاد معرف خدمة المزود الموافقة (يخزّن النتيجة في data.json)."""
    data = load_data()
    smap = data.setdefault("smm_id_map", {})
    if svc["id"] in smap:
        return smap[svc["id"]]
    # أولوية لأي smm_id مخصص في تعريف الخدمة
    if svc.get("smm_id"):
        smap[svc["id"]] = svc["smm_id"]
        save_data(data)
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
    smap[svc["id"]] = chosen
    save_data(data)
    return chosen

def find_service_by_id(svc_id):
    for platform_key, platform_data in SERVICES.items():
        for cat_key, cat_data in platform_data["categories"].items():
            for s in cat_data["services"]:
                if s["id"] == svc_id:
                    return platform_key, cat_key, s
    return None, None, None

# ======================== أزرار مخصصة من الأدمن ========================
def get_custom_buttons():
    data = load_data()
    return data.get("custom_buttons", [])

def save_custom_buttons(buttons):
    data = load_data()
    data["custom_buttons"] = buttons
    save_data(data)

def get_custom_button(btn_id):
    for b in get_custom_buttons():
        if b.get("id") == btn_id:
            return b
    return None

def update_custom_button(btn_id, updates):
    buttons = get_custom_buttons()
    for b in buttons:
        if b.get("id") == btn_id:
            b.update(updates)
            save_custom_buttons(buttons)
            return b
    return None

def delete_custom_button(btn_id):
    buttons = [b for b in get_custom_buttons() if b.get("id") != btn_id]
    save_custom_buttons(buttons)

def create_custom_button(name, location="main"):
    import uuid
    buttons = get_custom_buttons()
    btn = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "location": location,
        "service_ids": [],
    }
    buttons.append(btn)
    save_custom_buttons(buttons)
    return btn

def get_custom_buttons_for_location(location):
    return [b for b in get_custom_buttons() if b.get("location") == location]

LOCATION_LABELS = {
    "main": "🏠 القائمة الرئيسية",
    "platform_telegram": "✈️ تيليجرام",
    "platform_instagram": "📸 انستغرام",
    "platform_facebook": "📘 فيسبوك",
}

# ======================== الخدمات (معرفات المزود فقط) ========================
# كل خدمة تُحدد فقط بمعرفها لدى المزود (smm service id كرقم)
# والاسم/السعر/الحد الأدنى والأقصى تُجلب من المزود مباشرة (مع كاش)
SERVICE_IDS = {
    "telegram": {
        "name": "تيليجرام ✈️",
        "categories": {
            "views_past": {
                "name": "مشاهدات منشورات سابقة 👁️",
                "ids": [6062, 6061, 6060, 6059, 6058, 6057, 6055, 4136, 4135],
            },
            "views_future": {
                "name": "مشاهدات منشورات مستقبلية 🔮",
                "ids": [6068, 6067, 6066],
            },
            "members": {
                "name": "أعضاء 👥",
                "ids": [8970, 9039, 9040, 7756],
            },
            "reactions": {
                "name": "تفاعلات ❤️",
                "ids": [9682, 9681, 9678, 9676, 9693, 9705, 9714, 9715, 9716, 9729, 9738, 9742, 9749, 9906],
            },
            "referral_start": {
                "name": "بدء استخدام البوت / قبول الإحالة 🤝",
                "ids": [6034, 6032, 6031, 6030],
            },
        },
    },
    "facebook": {
        "name": "فيسبوك 📘",
        "categories": {
            "followers": {
                "name": "متابعين 👥",
                "ids": [8898, 9430, 8896, 8882, 4845, 5369, 4347, 6030, 6032],
            },
            "reactions": {
                "name": "تفاعلات ❤️",
                "ids": [7738, 7703, 9536, 9401, 9376, 9497, 9375, 4899],
            },
            "comments": {
                "name": "تعليقات 💬",
                "ids": [7566, 7565],
            },
        },
    },
    "instagram": {
        "name": "انستغرام 📸",
        "categories": {
            "views": {
                "name": "مشاهدات 👁️",
                "ids": [4013, 4014, 5351, 4012, 7566],
            },
            "followers": {
                "name": "متابعين 👥",
                "ids": [8849, 8921, 4805, 4883],
            },
            "likes": {
                "name": "إعجابات ❤️",
                "ids": [7699, 9252, 8973],
            },
        },
    },
}

def get_provider_service(smm_id):
    """يجلب تفاصيل خدمة من المزود (الاسم، السعر، الحد الأدنى/الأقصى)."""
    services = fetch_provider_services()
    return services.get(str(smm_id))

def build_service(smm_id):
    """يبني قاموس خدمة كامل من معرف المزود فقط."""
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
    """يعيد قائمة الخدمات (مبنية حياً) لتصنيف معين."""
    cat = SERVICE_IDS.get(platform_key, {}).get("categories", {}).get(category_key, {})
    services = []
    for sid in cat.get("ids", []):
        svc = build_service(sid)
        if svc:
            services.append(svc)
    return services

# واجهة توافق مع الكود القديم: SERVICES dict مبنية ديناميكياً
class _ServicesProxy:
    def __getitem__(self, key):
        return self._wrap_platform(key)
    def get(self, key, default=None):
        if key not in SERVICE_IDS:
            return default
        return self._wrap_platform(key)
    def items(self):
        return [(k, self._wrap_platform(k)) for k in SERVICE_IDS.keys()]
    def keys(self):
        return SERVICE_IDS.keys()
    def __contains__(self, key):
        return key in SERVICE_IDS
    def _wrap_platform(self, pkey):
        pdata = SERVICE_IDS[pkey]
        cats = {}
        for ckey, cdata in pdata["categories"].items():
            cats[ckey] = {
                "name": cdata["name"],
                "services": get_category_services(pkey, ckey),
            }
        return {"name": pdata["name"], "categories": cats}

SERVICES = _ServicesProxy()

# ======================== دوال مساعدة للواجهة ========================
def main_menu_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("💳 شحن رصيد", callback_data="charge")],
        [InlineKeyboardButton("🛒 طلب خدمة", callback_data="service")],
        [InlineKeyboardButton("📊 حالة الطلب", callback_data="order_status")],
        [InlineKeyboardButton("👥 إحالة صديق", callback_data="referral")],
        [InlineKeyboardButton("📞 التواصل مع الدعم", callback_data="support")],
    ]
    # أزرار مخصصة من الأدمن في القائمة الرئيسية
    for b in get_custom_buttons_for_location("main"):
        keyboard.append([InlineKeyboardButton(b["name"], callback_data=f"cbtn_{b['id']}")])
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("⚙️ لوحة الأدمن", callback_data="admin_panel")])
    return InlineKeyboardMarkup(keyboard)

def main_menu_text(user_id, header="🏠 القائمة الرئيسية"):
    user_data = get_user(user_id)
    balance = user_data.get("balance", 0.0)
    return (
        f"{header}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💳 رصيدك الحالي: {balance:.4f}$\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"اختر ما تريد:"
    )

def back_button(callback="main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=callback)]])

# ======================== الأوامر الرئيسية ========================
async def is_user_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """يتحقق إذا كان المستخدم مشتركاً في القناة المطلوبة."""
    if user_id == ADMIN_ID:
        return True
    try:
        member = await context.bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.error(f"Subscription check failed for {user_id}: {e}")
        return False

def subscription_required_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 الانضمام إلى القناة", url=REQUIRED_CHANNEL_URL)],
        [InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_subscription")],
    ])

async def send_subscription_required(update: Update):
    text = (
        "🔒 الاشتراك الإجباري\n"
        "━━━━━━━━━━━━━━━━\n"
        "للاستفادة من خدمات البوت، يرجى الاشتراك في قناتنا أولاً:\n"
        f"📢 {REQUIRED_CHANNEL_USERNAME}\n\n"
        "بعد الاشتراك اضغط زر «✅ تحقق من الاشتراك»."
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=subscription_required_keyboard())
    else:
        await update.message.reply_text(text, reply_markup=subscription_required_keyboard())

async def check_subscription_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if await is_user_subscribed(context, user_id):
        await query.answer("✅ تم التحقق من اشتراكك!", show_alert=True)
        # تشغيل القائمة الرئيسية
        get_user(user_id)
        balance = get_user(user_id).get("balance", 0.0)
        text = (
            f"👋 أهلاً بك {query.from_user.first_name}!\n\n"
            "🌟 مرحباً في بوت خدمات السوشيال ميديا\n"
            "━━━━━━━━━━━━━━━━\n"
            f"💳 رصيدك الحالي: {balance:.4f}$\n"
            "━━━━━━━━━━━━━━━━\n"
            "اختر ما تريد من القائمة أدناه:"
        )
        await query.edit_message_text(text, reply_markup=main_menu_keyboard(user_id))
        return MAIN_MENU
    else:
        await query.answer("❌ لم تشترك بعد في القناة!", show_alert=True)
        await query.edit_message_text(
            "🔒 الاشتراك الإجباري\n"
            "━━━━━━━━━━━━━━━━\n"
            "لم نتمكن من العثور على اشتراكك في القناة.\n"
            f"📢 {REQUIRED_CHANNEL_USERNAME}\n\n"
            "يرجى الاشتراك ثم الضغط مرة أخرى.",
            reply_markup=subscription_required_keyboard()
        )
        return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    args = context.args

    user_data = get_user(user_id)
    # تحديث بيانات المستخدم
    update_user(user_id, {
        "username": user.username,
        "first_name": user.first_name
    })

    # ======== التحقق من الاشتراك الإجباري ========
    if not await is_user_subscribed(context, user_id):
        await send_subscription_required(update)
        return ConversationHandler.END

    if args and args[0].startswith("ref_"):
        referrer_id = args[0].replace("ref_", "")
        if referrer_id != str(user_id) and user_data.get("referred_by") is None:
            update_user(user_id, {"referred_by": referrer_id})
            data = load_data()
            if referrer_id not in data["users"]:
                data["users"][referrer_id] = {"balance": 0.0, "referral_balance": 0.0, "referred_by": None, "referrals": []}
            if str(user_id) not in data["users"][referrer_id].get("referrals", []):
                data["users"][referrer_id].setdefault("referrals", []).append(str(user_id))
            save_data(data)

    balance = get_user(user_id).get("balance", 0.0)
    text = (
        f"👋 أهلاً بك {user.first_name}!\n\n"
        "🌟 مرحباً في بوت خدمات السوشيال ميديا\n"
        "━━━━━━━━━━━━━━━━\n"
        f"💳 رصيدك الحالي: {balance:.4f}$\n"
        "━━━━━━━━━━━━━━━━\n"
        "اختر ما تريد من القائمة أدناه:"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard(user_id))
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
        [InlineKeyboardButton("💚 شام كاش", callback_data="sham_cash")],
        [InlineKeyboardButton("🔵 سيرياتيل كاش", callback_data="syriatel_cash")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")],
    ]
    await query.edit_message_text(
        "💳 شحن الرصيد\n━━━━━━━━━━━━━━━━\nاختر طريقة الدفع:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHARGE_MENU

async def sham_cash_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("💵 شحن شام كاش دولار", callback_data="sham_dollar")],
        [InlineKeyboardButton("🇸🇾 شحن شام كاش سوري", callback_data="sham_syp")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="charge")],
    ]
    await query.edit_message_text(
        "💚 شام كاش\n━━━━━━━━━━━━━━━━\nاختر نوع العملة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SHAM_MENU

async def sham_syp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["charge_type"] = "sham_syp"
    keyboard = [
        [InlineKeyboardButton("✅ تحقق من الدفع", callback_data="verify_payment")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="sham_cash")],
    ]
    await query.edit_message_text(
        f"🇸🇾 شحن شام كاش سوري\n━━━━━━━━━━━━━━━━\n"
        f"📱 حساب شام كاش:\n`{SHAM_CASH_ACCOUNT}`\n\n"
        f"📌 أرسل المبلغ المراد شحنه على هذا الحساب، ثم اضغط على زر التحقق من الدفع.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SHAM_MENU

async def sham_dollar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["charge_type"] = "sham_dollar"
    keyboard = [
        [InlineKeyboardButton("✅ تحقق من الدفع", callback_data="verify_payment")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="sham_cash")],
    ]
    await query.edit_message_text(
        f"💵 شحن شام كاش دولار\n━━━━━━━━━━━━━━━━\n"
        f"📱 حساب شام كاش:\n`{SHAM_CASH_ACCOUNT}`\n\n"
        f"📌 أرسل المبلغ المراد شحنه على هذا الحساب، ثم اضغط على زر التحقق من الدفع.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return SHAM_MENU

async def syriatel_cash_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["charge_type"] = "syriatel"
    keyboard = [
        [InlineKeyboardButton("✅ تحقق من الدفع", callback_data="verify_payment")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="charge")],
    ]
    await query.edit_message_text(
        f"🔵 شحن سيرياتيل كاش\n━━━━━━━━━━━━━━━━\n"
        f"📱 حساب سيرياتيل كاش:\n`{SYRIATEL_CASH_ACCOUNT}`\n\n"
        f"📌 أرسل المبلغ المراد شحنه على هذا الحساب، ثم اضغط على زر التحقق من الدفع.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return CHARGE_MENU

async def verify_payment_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    charge_type = context.user_data.get("charge_type", "unknown")
    if charge_type == "sham_syp":
        currency = "باليرة السورية"
    elif charge_type == "sham_dollar":
        currency = "بالدولار"
    else:
        currency = "بالليرة السورية"
    context.user_data["currency_label"] = currency
    await query.edit_message_text(
        f"📝 التحقق من الدفع\n━━━━━━━━━━━━━━━━\n"
        f"أدخل المبلغ المشحون ({currency}):"
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
    tx_id = update.message.text.strip()
    context.user_data["tx_id"] = tx_id
    user = update.effective_user
    amount = context.user_data.get("pay_amount")
    charge_type = context.user_data.get("charge_type", "unknown")
    currency_label = context.user_data.get("currency_label", "")

    type_names = {
        "sham_syp": "شام كاش سوري 🇸🇾",
        "sham_dollar": "شام كاش دولار 💵",
        "syriatel": "سيرياتيل كاش 🔵"
    }
    type_name = type_names.get(charge_type, charge_type)

    pay_info = {
        "user_id": user.id,
        "username": user.username or user.first_name,
        "amount": amount,
        "currency": currency_label,
        "charge_type": charge_type,
        "tx_id": tx_id
    }
    payment_key = f"{user.id}_{tx_id}"
    save_pending_payment(payment_key, pay_info)

    await update.message.reply_text(
        "⏳ نحن نعالج الدفعة، الرجاء الانتظار لبضع لحظات..."
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ تأكيد الدفع", callback_data=f"admin_approve_{payment_key}"),
            InlineKeyboardButton("❌ رفض الدفع", callback_data=f"admin_reject_{payment_key}")
        ]
    ]
    admin_text = (
        f"💳 طلب شحن رصيد جديد!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👤 المستخدم: {user.first_name} (@{user.username or 'بدون يوزر'})\n"
        f"🆔 معرف: {user.id}\n"
        f"💰 المبلغ: {amount} {currency_label}\n"
        f"🏦 طريقة الدفع: {type_name}\n"
        f"🔢 معرّف العملية: {tx_id}"
    )
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Error sending to admin: {e}")

    return MAIN_MENU

# ======================== معالجة قرارات الأدمن للدفع ========================
async def admin_approve_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    payment_key = query.data.replace("admin_approve_", "")
    pay_info = get_pending_payment(payment_key)
    if not pay_info:
        await query.edit_message_text("⚠️ لم يتم العثور على بيانات الدفع.")
        return
    context.user_data["approving_payment_key"] = payment_key
    context.user_data["approving_pay_info"] = pay_info
    await query.edit_message_text(
        f"✅ تأكيد الدفع\n━━━━━━━━━━━━━━━━\n"
        f"المستخدم: {pay_info['username']}\n"
        f"المبلغ المدفوع: {pay_info['amount']} {pay_info['currency']}\n\n"
        f"📌 أدخل المبلغ بالدولار لإضافته لرصيد المستخدم:"
    )
    return ADMIN_CONFIRM_AMOUNT

async def admin_receive_dollar_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text.strip()
    try:
        dollar_amount = float(text)
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح.")
        return ADMIN_CONFIRM_AMOUNT

    payment_key = context.user_data.get("approving_payment_key")
    pay_info = context.user_data.get("approving_pay_info")
    if not pay_info:
        await update.message.reply_text("⚠️ خطأ: لم يتم العثور على بيانات الدفع.")
        return MAIN_MENU

    user_id = pay_info["user_id"]
    user_data = get_user(user_id)
    new_balance = user_data["balance"] + dollar_amount

    referred_by = user_data.get("referred_by")
    if referred_by:
        commission = dollar_amount * REFERRAL_COMMISSION
        ref_data = get_user(referred_by)
        ref_new_balance = ref_data["balance"] + commission
        update_user(referred_by, {"balance": ref_new_balance})
        try:
            await context.bot.send_message(
                chat_id=int(referred_by),
                text=f"🎉 حصلت على عمولة إحالة!\n💰 المبلغ: {commission:.4f}$\n💳 رصيدك الحالي: {ref_new_balance:.4f}$"
            )
        except Exception as e:
            logger.error(f"Failed to notify referrer: {e}")

    update_user(user_id, {"balance": new_balance})
    remove_pending_payment(payment_key)

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ تم شحن رصيدك بنجاح!\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"💰 المبلغ المضاف: {dollar_amount}$\n"
                f"💳 رصيدك الحالي: {new_balance:.4f}$"
            ),
            reply_markup=main_menu_keyboard(user_id)
        )
    except Exception as e:
        logger.error(f"Failed to notify user: {e}")

    await update.message.reply_text(
        f"✅ تمت العملية بنجاح!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💳 تم شحن حساب المستخدم {pay_info['username']} فوراً\n"
        f"💰 المبلغ المضاف: {dollar_amount}$\n"
        f"📊 رصيده الجديد: {new_balance:.4f}$\n"
        f"📨 تم إرسال إشعار للزبون.",
        reply_markup=main_menu_keyboard(ADMIN_ID)
    )
    return MAIN_MENU

async def admin_reject_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    payment_key = query.data.replace("admin_reject_", "")
    pay_info = get_pending_payment(payment_key)
    if not pay_info:
        await query.edit_message_text("⚠️ لم يتم العثور على بيانات الدفع.")
        return
    user_id = pay_info["user_id"]
    remove_pending_payment(payment_key)

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "❌ تم رفض الدفع\n"
                "━━━━━━━━━━━━━━━━\n"
                "يرجى التحقق من المعلومات المرسلة ومراسلة الدعم.\n\n"
                f"📞 الدعم: {ADMIN_USERNAME}"
            ),
            reply_markup=main_menu_keyboard(user_id)
        )
    except Exception as e:
        logger.error(f"Failed to notify user about rejection: {e}")

    await query.edit_message_text(f"❌ تم رفض الدفع للمستخدم {pay_info['username']}.")

# ======================== الإحالة ========================
async def referral_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)
    bot_info = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user_id}"
    referrals = user_data.get("referrals", [])
    keyboard = [
        [InlineKeyboardButton("👥 إحالاتي", callback_data="my_referrals")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")],
    ]
    await query.edit_message_text(
        f"👥 برنامج الإحالة\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔗 رابط الإحالة الخاص بك:\n`{ref_link}`\n\n"
        f"💰 عمولتك: 7% من كل عملية شحن للمُحالين\n"
        f"👥 عدد إحالاتك: {len(referrals)}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return MAIN_MENU

async def my_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = get_user(user_id)
    referrals = user_data.get("referrals", [])
    if referrals:
        ref_list = "\n".join([f"• مستخدم {r}" for r in referrals])
    else:
        ref_list = "لا يوجد إحالات حتى الآن"
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="referral")]]
    await query.edit_message_text(
        f"👥 إحالاتي\n━━━━━━━━━━━━━━━━\n{ref_list}\n\n"
        f"💳 رصيدك: {user_data['balance']:.4f}$",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ======================== الدعم ========================
async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="main")]]
    await query.edit_message_text(
        f"📞 التواصل مع الدعم\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"للتواصل مع الدعم الفني، تفضل:\n{ADMIN_USERNAME}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return MAIN_MENU

# ======================== طلب الخدمات ========================
async def service_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("✈️ تيليجرام", callback_data="platform_telegram")],
        [InlineKeyboardButton("📸 انستغرام", callback_data="platform_instagram")],
        [InlineKeyboardButton("📘 فيسبوك", callback_data="platform_facebook")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")],
    ]
    await query.edit_message_text(
        "🛒 طلب خدمة\n━━━━━━━━━━━━━━━━\nاختر المنصة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SERVICE_PLATFORM

async def platform_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    platform = query.data.replace("platform_", "")
    context.user_data["platform"] = platform
    platform_data = SERVICES.get(platform)
    if not platform_data:
        await query.edit_message_text("❌ منصة غير معروفة.")
        return SERVICE_PLATFORM

    keyboard = []
    for cat_key, cat_data in platform_data["categories"].items():
        if cat_data["services"]:
            keyboard.append([InlineKeyboardButton(cat_data["name"], callback_data=f"category_{cat_key}")])
    # أزرار مخصصة من الأدمن لهذه المنصة
    for b in get_custom_buttons_for_location(f"platform_{platform}"):
        keyboard.append([InlineKeyboardButton(b["name"], callback_data=f"cbtn_{b['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="service")])

    await query.edit_message_text(
        f"🛒 {platform_data['name']}\n━━━━━━━━━━━━━━━━\nاختر نوع الخدمة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SERVICE_TYPE

async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    cat_key = query.data.replace("category_", "")
    platform = context.user_data.get("platform")
    context.user_data["category"] = cat_key
    context.user_data["svc_back_cb"] = f"category_{cat_key}"

    platform_data = SERVICES.get(platform)
    cat_data = platform_data["categories"].get(cat_key)

    # تحديث أسعار المزود الحية
    fetch_provider_services()

    keyboard = []
    for svc in cat_data["services"]:
        price_shown = get_customer_price(svc)
        btn_text = f"{svc['name'][:40]} | {price_shown:.4f}$/1K"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"svc_{svc['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"platform_{platform}")])

    await query.edit_message_text(
        f"🛒 {cat_data['name']}\n━━━━━━━━━━━━━━━━\nاختر الخدمة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return SERVICE_SELECT

async def custom_button_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض خدمات زر مخصص للزبون."""
    query = update.callback_query
    await query.answer()
    btn_id = query.data.replace("cbtn_", "")
    btn = get_custom_button(btn_id)
    if not btn:
        await query.edit_message_text("❌ الزر غير موجود.", reply_markup=back_button("main"))
        return MAIN_MENU

    context.user_data["svc_back_cb"] = f"cbtn_{btn_id}"
    context.user_data["platform"] = None
    context.user_data["category"] = None

    fetch_provider_services()

    keyboard = []
    for sid in btn.get("service_ids", []):
        svc = build_service(sid)
        if not svc:
            continue
        price_shown = get_customer_price(svc)
        btn_text = f"{svc['name'][:40]} | {price_shown:.4f}$/1K"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"svc_{svc['id']}")])

    # زر رجوع حسب موقع الزر
    loc = btn.get("location", "main")
    if loc.startswith("platform_"):
        back_cb = loc
    else:
        back_cb = "main"
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=back_cb)])

    if not btn.get("service_ids"):
        text = f"🛒 {btn['name']}\n━━━━━━━━━━━━━━━━\n⚠️ لا توجد خدمات بعد في هذا الزر."
    else:
        text = f"🛒 {btn['name']}\n━━━━━━━━━━━━━━━━\nاختر الخدمة:"

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return SERVICE_SELECT

async def service_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    svc_id = query.data.replace("svc_", "")
    platform = context.user_data.get("platform")
    cat_key = context.user_data.get("category")

    svc = None
    if platform and cat_key:
        platform_data = SERVICES.get(platform)
        cat_data = platform_data["categories"].get(cat_key) if platform_data else None
        if cat_data:
            svc = next((s for s in cat_data["services"] if s["id"] == svc_id), None)
    # احتياط: ابني الخدمة مباشرة من المزود (مفيد للأزرار المخصصة)
    if not svc:
        svc = build_service(svc_id)
    if not svc:
        await query.edit_message_text("❌ الخدمة غير موجودة.")
        return SERVICE_SELECT

    context.user_data["selected_service"] = svc
    context.user_data["selected_platform_key"] = platform
    context.user_data["selected_category_key"] = cat_key
    price_shown = get_customer_price(svc)

    back_cb = context.user_data.get("svc_back_cb") or (f"category_{cat_key}" if cat_key else "main")
    keyboard = [
        [InlineKeyboardButton("▶️ متابعة", callback_data="proceed_order")],
        [InlineKeyboardButton("🔙 رجوع", callback_data=back_cb)],
    ]
    await query.edit_message_text(
        f"📋 تفاصيل الخدمة\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔹 {svc['name']}\n\n"
        f"💰 السعر: {price_shown:.4f}$ لكل 1000 وحدة\n"
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
        f"📦 إدخال الكمية\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"أدخل الكمية المطلوبة:\n"
        f"📉 الحد الأدنى: {svc['min']:,}\n"
        f"📈 الحد الأقصى: {svc['max']:,}"
    )
    return ORDER_QUANTITY

async def receive_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    svc = context.user_data.get("selected_service")
    try:
        qty = int(text)
        if qty < svc["min"] or qty > svc["max"]:
            await update.message.reply_text(
                f"❌ الكمية خارج النطاق المسموح.\n"
                f"📉 الحد الأدنى: {svc['min']:,}\n"
                f"📈 الحد الأقصى: {svc['max']:,}"
            )
            return ORDER_QUANTITY
        context.user_data["order_qty"] = qty
        await update.message.reply_text("🔗 أدخل الرابط:")
        return ORDER_LINK
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح.")
        return ORDER_QUANTITY

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    context.user_data["order_link"] = link
    svc = context.user_data.get("selected_service")
    qty = context.user_data.get("order_qty")
    price_per_unit = get_customer_price(svc) / 1000
    total_price = price_per_unit * qty

    keyboard = [
        [InlineKeyboardButton("✅ تأكيد الطلب", callback_data="confirm_order")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="main")],
    ]
    await update.message.reply_text(
        f"📋 ملخص الطلب\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔹 الخدمة: {svc['name'][:50]}\n"
        f"🔗 الرابط: {link}\n"
        f"📦 الكمية: {qty:,}\n"
        f"💰 السعر الإجمالي: {total_price:.4f}$",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ORDER_CONFIRM

async def confirm_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    svc = context.user_data.get("selected_service")
    qty = context.user_data.get("order_qty")
    link = context.user_data.get("order_link")
    price_per_unit = get_customer_price(svc) / 1000
    total_price = price_per_unit * qty

    user_data = get_user(user_id)
    if user_data["balance"] < total_price:
        await query.edit_message_text(
            f"❌ رصيدك غير كافٍ!\n"
            f"💳 رصيدك الحالي: {user_data['balance']:.4f}$\n"
            f"💰 المبلغ المطلوب: {total_price:.4f}$\n\n"
            f"يرجى شحن رصيدك أولاً.",
            reply_markup=main_menu_keyboard(user_id)
        )
        return MAIN_MENU

    await query.edit_message_text("⏳ جارٍ تنفيذ الطلب تلقائياً...")

    new_balance = user_data["balance"] - total_price
    update_user(user_id, {"balance": new_balance})

    platform_key = context.user_data.get("selected_platform_key")
    category_key = context.user_data.get("selected_category_key")
    if not platform_key or not category_key:
        platform_key, category_key, _ = find_service_by_id(svc["id"])
    smm_service_id = resolve_smm_id(svc, platform_key, category_key)
    if not smm_service_id:
        update_user(user_id, {"balance": user_data["balance"]})
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "❌ لم نتمكن من إيجاد خدمة موافقة لدى المزود حالياً.\n"
                "تم استرداد رصيدك بالكامل، يرجى المحاولة لاحقاً."
            ),
            reply_markup=main_menu_keyboard(user_id)
        )
        return MAIN_MENU
    result = place_order(smm_service_id, link, qty)

    if result and "order" in result:
        order_id = result["order"]
        # حفظ الطلب في بيانات المستخدم
        from datetime import datetime
        order_record = {
            "order_id": str(order_id),
            "smm_service_id": str(smm_service_id),
            "service_name": svc.get("name", ""),
            "link": link,
            "quantity": int(qty),
            "cost": float(total_price),
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        u = get_user(user_id)
        orders = u.get("orders", [])
        orders.insert(0, order_record)
        update_user(user_id, {"orders": orders[:100]})
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ تم تنفيذ طلبك بنجاح!\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🔢 رقم الطلب: {order_id}\n"
                f"🔹 الخدمة: {svc['name'][:50]}\n"
                f"📦 الكمية: {qty:,}\n"
                f"💰 المبلغ المخصوم: {total_price:.4f}$\n"
                f"💳 رصيدك المتبقي: {new_balance:.4f}$\n"
                f"⏱️ متوسط الوقت: {svc['avg_time']}"
            ),
            reply_markup=main_menu_keyboard(user_id)
        )
    else:
        update_user(user_id, {"balance": user_data["balance"]})
        error_msg = result.get("error", "خطأ غير معروف") if result else "فشل الاتصال بالخادم"
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"❌ فشل تنفيذ الطلب!\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"السبب: {error_msg}\n"
                f"تم استرداد رصيدك بالكامل.\n"
                f"💳 رصيدك: {user_data['balance']:.4f}$"
            ),
            reply_markup=main_menu_keyboard(user_id)
        )

    return MAIN_MENU

# ======================== حالة الطلبات ========================
STATUS_AR = {
    "pending": "قيد الانتظار ⏳",
    "in progress": "جاري التنفيذ 🔄",
    "processing": "قيد المعالجة 🔄",
    "completed": "مكتمل ✅",
    "partial": "مكتمل جزئياً ⚠️",
    "canceled": "ملغي ❌",
    "cancelled": "ملغي ❌",
    "refunded": "تم الاسترداد 💸",
    "fail": "فشل ❌",
}

def translate_status(s):
    if not s:
        return "غير معروف"
    return STATUS_AR.get(str(s).lower(), str(s))

async def order_status_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    u = get_user(user_id)
    orders = u.get("orders", [])
    if not orders:
        await query.edit_message_text(
            "📊 حالة الطلبات\n━━━━━━━━━━━━━━━━\n"
            "لا يوجد لديك أي طلبات سابقة.",
            reply_markup=back_button("main")
        )
        return MAIN_MENU
    keyboard = []
    for o in orders[:15]:
        label = f"#{o['order_id']} | {o['quantity']:,} | {o['cost']:.4f}$"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"order_view_{o['order_id']}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main")])
    await query.edit_message_text(
        "📊 حالة الطلبات\n━━━━━━━━━━━━━━━━\n"
        f"إجمالي طلباتك: {len(orders)}\n"
        "اختر طلباً لعرض تفاصيله الحية:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ORDER_STATUS_LIST

async def order_view_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ جاري جلب الحالة...")
    user_id = query.from_user.id
    order_id = query.data.replace("order_view_", "")
    u = get_user(user_id)
    rec = next((o for o in u.get("orders", []) if str(o["order_id"]) == order_id), None)
    if not rec:
        await query.edit_message_text("❌ لم يتم العثور على الطلب.", reply_markup=back_button("order_status"))
        return ORDER_STATUS_LIST
    info = get_order_status(order_id) or {}
    status = translate_status(info.get("status"))
    start_count = info.get("start_count", "—")
    remains = info.get("remains", "—")
    text = (
        "📋 تفاصيل الطلب\n"
        "━━━━━━━━━━━━━━━━\n"
        f"🆔 بطاقة تعريف: {rec['order_id']}\n"
        f"📅 التاريخ: {rec['date']}\n"
        f"🔗 الوصلة: {rec['link']}\n"
        f"💰 التكلفة: {rec['cost']:.4f}$\n"
        f"🔢 عداد البداية: {start_count}\n"
        f"📦 الكمية: {rec['quantity']:,}\n"
        f"🔹 الخدمة: {rec['service_name'][:60]}\n"
        f"📊 الحالة: {status}\n"
        f"⏳ البقايا: {remains}"
    )
    keyboard = [
        [InlineKeyboardButton("🔄 تحديث", callback_data=f"order_view_{order_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="order_status")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ORDER_STATUS_LIST

# ======================== لوحة الأدمن ========================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    multiplier = get_multiplier()
    data = load_data()
    users_count = len(data.get("users", {}))
    keyboard = [
        [InlineKeyboardButton("💱 تعديل ضرب السعر", callback_data="set_multiplier")],
        [InlineKeyboardButton("💵 تعديل الأسعار", callback_data="admin_prices")],
        [InlineKeyboardButton(f"👥 إدارة الحسابات ({users_count})", callback_data="admin_users")],
        [InlineKeyboardButton("📢 بث رسالة لكل المستخدمين", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🧩 إضافة أزرار", callback_data="admin_cbtns")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="main")],
    ]
    await query.edit_message_text(
        f"⚙️ لوحة الأدمن\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💱 معامل الضرب الحالي: ×{multiplier}\n"
        f"👥 عدد المستخدمين: {users_count}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_PANEL

# ======================== بث رسالة لكل المستخدمين ========================
async def admin_broadcast_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    data = load_data()
    users_count = len(data.get("users", {}))
    await query.edit_message_text(
        "📢 بث رسالة جماعية\n━━━━━━━━━━━━━━━━\n"
        f"سيتم إرسال رسالتك إلى {users_count} مستخدم.\n\n"
        "أرسل الآن نص الرسالة (يدعم النص العادي والإيموجي):\n"
        "أو أرسل /cancel للإلغاء.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")]])
    )
    return ADMIN_BROADCAST_INPUT

async def admin_broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text
    if text and text.strip().lower() == "/cancel":
        await update.message.reply_text("❌ تم إلغاء البث.", reply_markup=main_menu_keyboard(ADMIN_ID))
        return MAIN_MENU
    data = load_data()
    users = list(data.get("users", {}).keys())
    await update.message.reply_text(f"⏳ جاري الإرسال إلى {len(users)} مستخدم...")
    sent, failed = 0, 0
    msg = (
        "📢 رسالة من الإدارة\n"
        "━━━━━━━━━━━━━━━━\n"
        f"{text}"
    )
    for uid in users:
        try:
            await context.bot.send_message(chat_id=int(uid), text=msg)
            sent += 1
        except Exception as e:
            logger.error(f"Broadcast failed for {uid}: {e}")
            failed += 1
    await update.message.reply_text(
        f"✅ اكتمل البث!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📤 تم الإرسال: {sent}\n"
        f"⚠️ فشل: {failed}",
        reply_markup=main_menu_keyboard(ADMIN_ID)
    )
    return MAIN_MENU

# ======================== إدارة الأزرار المخصصة (الأدمن) ========================
async def admin_cbtns_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return ADMIN_PANEL
    await query.answer()
    buttons = get_custom_buttons()
    keyboard = [[InlineKeyboardButton("➕ إنشاء زر جديد", callback_data="cbtnnew")]]
    for b in buttons:
        loc_label = LOCATION_LABELS.get(b.get("location", "main"), b.get("location"))
        label = f"{b['name']} | {loc_label} | ({len(b.get('service_ids', []))})"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"cbtnv_{b['id']}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])
    await query.edit_message_text(
        "🧩 الأزرار المخصصة\n━━━━━━━━━━━━━━━━\n"
        f"إجمالي الأزرار: {len(buttons)}\n"
        "اختر زراً لإدارته أو أنشئ زراً جديداً:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_CBTN_LIST

async def admin_cbtn_new_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return ADMIN_PANEL
    await query.answer()
    await query.edit_message_text(
        "✏️ إنشاء زر جديد\n━━━━━━━━━━━━━━━━\n"
        "أرسل اسم الزر (الذي سيراه الزبون):\n"
        "أو /cancel للإلغاء.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_cbtns")]])
    )
    return ADMIN_CBTN_NAME

async def admin_cbtn_new_receive_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text.strip()
    if text.lower() == "/cancel":
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_keyboard(ADMIN_ID))
        return MAIN_MENU
    if len(text) < 1 or len(text) > 60:
        await update.message.reply_text("❌ الاسم يجب أن يكون بين 1 و 60 حرفاً. أعد الإرسال.")
        return ADMIN_CBTN_NAME
    btn = create_custom_button(text, location="main")
    context.user_data["cbtn_id"] = btn["id"]
    await update.message.reply_text(
        f"✅ تم إنشاء الزر «{btn['name']}» بنجاح!\n"
        f"الموقع الافتراضي: 🏠 القائمة الرئيسية\n"
        f"يمكنك تغيير الموقع وإضافة الخدمات الآن:",
        reply_markup=_cbtn_view_keyboard(btn["id"])
    )
    return ADMIN_CBTN_VIEW

def _cbtn_view_keyboard(btn_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ إضافة خدمة (معرف المزود)", callback_data=f"cbtnsvc_add_{btn_id}")],
        [InlineKeyboardButton("📋 إدارة الخدمات", callback_data=f"cbtnsvc_list_{btn_id}")],
        [InlineKeyboardButton("📍 تغيير الموقع", callback_data=f"cbtnloc_{btn_id}")],
        [InlineKeyboardButton("✏️ تعديل الاسم", callback_data=f"cbtnren_{btn_id}")],
        [InlineKeyboardButton("🗑️ حذف الزر", callback_data=f"cbtndel_{btn_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_cbtns")],
    ])

async def admin_cbtn_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return ADMIN_PANEL
    await query.answer()
    btn_id = query.data.replace("cbtnv_", "")
    btn = get_custom_button(btn_id)
    if not btn:
        await query.edit_message_text("❌ الزر غير موجود.", reply_markup=back_button("admin_cbtns"))
        return ADMIN_CBTN_LIST
    context.user_data["cbtn_id"] = btn_id
    loc_label = LOCATION_LABELS.get(btn.get("location", "main"), btn.get("location"))
    await query.edit_message_text(
        f"🧩 إدارة الزر\n━━━━━━━━━━━━━━━━\n"
        f"📛 الاسم: {btn['name']}\n"
        f"📍 الموقع: {loc_label}\n"
        f"🛒 عدد الخدمات: {len(btn.get('service_ids', []))}",
        reply_markup=_cbtn_view_keyboard(btn_id)
    )
    return ADMIN_CBTN_VIEW

async def admin_cbtn_change_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    btn_id = query.data.replace("cbtnloc_", "")
    context.user_data["cbtn_id"] = btn_id
    keyboard = []
    for loc_key, loc_label in LOCATION_LABELS.items():
        keyboard.append([InlineKeyboardButton(loc_label, callback_data=f"cbtnsetloc_{btn_id}_{loc_key}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"cbtnv_{btn_id}")])
    await query.edit_message_text(
        "📍 اختر موقع الزر:\n━━━━━━━━━━━━━━━━\n"
        "سيظهر الزر في القائمة المختارة.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_CBTN_VIEW

async def admin_cbtn_set_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.replace("cbtnsetloc_", "").split("_", 1)
    btn_id = parts[0]
    loc = parts[1]
    update_custom_button(btn_id, {"location": loc})
    btn = get_custom_button(btn_id)
    loc_label = LOCATION_LABELS.get(btn.get("location"), btn.get("location"))
    await query.edit_message_text(
        f"✅ تم تحديث الموقع إلى: {loc_label}",
        reply_markup=_cbtn_view_keyboard(btn_id)
    )
    return ADMIN_CBTN_VIEW

async def admin_cbtn_rename_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    btn_id = query.data.replace("cbtnren_", "")
    context.user_data["cbtn_id"] = btn_id
    await query.edit_message_text(
        "✏️ تعديل الاسم\n━━━━━━━━━━━━━━━━\n"
        "أرسل الاسم الجديد للزر، أو /cancel للإلغاء.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"cbtnv_{btn_id}")]])
    )
    return ADMIN_CBTN_RENAME

async def admin_cbtn_rename_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text.strip()
    btn_id = context.user_data.get("cbtn_id")
    if text.lower() == "/cancel" or not btn_id:
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_keyboard(ADMIN_ID))
        return MAIN_MENU
    if len(text) < 1 or len(text) > 60:
        await update.message.reply_text("❌ الاسم يجب أن يكون بين 1 و 60 حرفاً. أعد الإرسال.")
        return ADMIN_CBTN_RENAME
    update_custom_button(btn_id, {"name": text})
    await update.message.reply_text(
        f"✅ تم تحديث الاسم إلى: «{text}»",
        reply_markup=_cbtn_view_keyboard(btn_id)
    )
    return ADMIN_CBTN_VIEW

async def admin_cbtn_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    btn_id = query.data.replace("cbtndel_", "")
    btn = get_custom_button(btn_id)
    if not btn:
        await query.edit_message_text("❌ الزر غير موجود.", reply_markup=back_button("admin_cbtns"))
        return ADMIN_CBTN_LIST
    delete_custom_button(btn_id)
    await query.edit_message_text(f"🗑️ تم حذف الزر «{btn['name']}» بنجاح.")
    # عرض القائمة من جديد
    return await admin_cbtns_list(update, context)

async def admin_cbtn_add_svc_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    btn_id = query.data.replace("cbtnsvc_add_", "")
    context.user_data["cbtn_id"] = btn_id
    await query.edit_message_text(
        "➕ إضافة خدمة للزر\n━━━━━━━━━━━━━━━━\n"
        "أرسل معرف الخدمة (رقم) كما هو لدى المزود.\n"
        "البوت سيجلب اسمها وسعرها وحدودها تلقائياً.\n\n"
        "أو /cancel للإلغاء.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data=f"cbtnv_{btn_id}")]])
    )
    return ADMIN_CBTN_ADD_SVC

async def admin_cbtn_add_svc_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text.strip()
    btn_id = context.user_data.get("cbtn_id")
    if text.lower() == "/cancel" or not btn_id:
        await update.message.reply_text("❌ تم الإلغاء.", reply_markup=main_menu_keyboard(ADMIN_ID))
        return MAIN_MENU
    try:
        sid = int(text)
    except ValueError:
        await update.message.reply_text("❌ الرجاء إرسال رقم صحيح فقط (معرف الخدمة).")
        return ADMIN_CBTN_ADD_SVC
    info = get_provider_service(sid)
    if not info:
        await update.message.reply_text(
            f"❌ لم أجد خدمة بهذا المعرف ({sid}) لدى المزود.\n"
            "تأكد من المعرف وأعد الإرسال، أو /cancel."
        )
        return ADMIN_CBTN_ADD_SVC
    btn = get_custom_button(btn_id)
    sids = btn.get("service_ids", [])
    if sid in sids:
        await update.message.reply_text(
            f"⚠️ هذه الخدمة موجودة مسبقاً في الزر.",
            reply_markup=_cbtn_view_keyboard(btn_id)
        )
        return ADMIN_CBTN_VIEW
    sids.append(sid)
    update_custom_button(btn_id, {"service_ids": sids})
    multiplier = get_multiplier()
    customer_price = float(info.get("rate", 0)) * multiplier
    await update.message.reply_text(
        f"✅ تمت إضافة الخدمة بنجاح!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🆔 المعرف: {sid}\n"
        f"🔹 الاسم: {info.get('name', '')[:80]}\n"
        f"💰 سعر المزود: {info.get('rate')}$ / 1K\n"
        f"💵 سعر الزبون: {customer_price:.4f}$ / 1K\n"
        f"📉 الحد الأدنى: {info.get('min'):,}\n"
        f"📈 الحد الأقصى: {info.get('max'):,}",
        reply_markup=_cbtn_view_keyboard(btn_id)
    )
    return ADMIN_CBTN_VIEW

async def admin_cbtn_list_svc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    btn_id = query.data.replace("cbtnsvc_list_", "")
    btn = get_custom_button(btn_id)
    if not btn:
        await query.edit_message_text("❌ الزر غير موجود.", reply_markup=back_button("admin_cbtns"))
        return ADMIN_CBTN_LIST
    context.user_data["cbtn_id"] = btn_id
    sids = btn.get("service_ids", [])
    keyboard = []
    for sid in sids:
        info = get_provider_service(sid) or {}
        nm = info.get("name", f"#{sid}")[:35]
        keyboard.append([InlineKeyboardButton(f"🗑️ {sid} | {nm}", callback_data=f"cbtnsvc_del_{btn_id}_{sid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"cbtnv_{btn_id}")])
    text = (
        f"📋 خدمات الزر «{btn['name']}»\n━━━━━━━━━━━━━━━━\n"
        f"العدد: {len(sids)}\n"
        + ("اضغط على خدمة لحذفها." if sids else "لا توجد خدمات بعد.")
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ADMIN_CBTN_VIEW

async def admin_cbtn_del_svc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("🗑️ تم الحذف")
    rest = query.data.replace("cbtnsvc_del_", "")
    btn_id, sid_str = rest.split("_", 1)
    try:
        sid = int(sid_str)
    except ValueError:
        return ADMIN_CBTN_VIEW
    btn = get_custom_button(btn_id)
    if not btn:
        return ADMIN_CBTN_LIST
    sids = [s for s in btn.get("service_ids", []) if s != sid]
    update_custom_button(btn_id, {"service_ids": sids})
    # إعادة عرض قائمة الخدمات
    query.data = f"cbtnsvc_list_{btn_id}"
    return await admin_cbtn_list_svc(update, context)

# ======================== إدارة حسابات المستخدمين ========================
USERS_PAGE_SIZE = 10

def _user_label(uid, info):
    bal = info.get("balance", 0.0)
    name = info.get("username") or info.get("first_name") or uid
    return f"{name} | {uid} | {bal:.2f}$"

async def admin_users_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page=0):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return ADMIN_PANEL
    await query.answer()
    if query.data and query.data.startswith("users_page_"):
        try:
            page = int(query.data.replace("users_page_", ""))
        except ValueError:
            page = 0
    data = load_data()
    users = data.get("users", {})
    items = list(users.items())
    items.sort(key=lambda x: x[0])
    total = len(items)
    start = page * USERS_PAGE_SIZE
    end = start + USERS_PAGE_SIZE
    page_items = items[start:end]

    keyboard = [[InlineKeyboardButton("🔍 بحث عن مستخدم", callback_data="users_search")]]
    for uid, info in page_items:
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
        f"إجمالي المستخدمين: {total}\n"
        f"الصفحة {page+1} من {pages}\n\n"
        f"اختر مستخدماً لعرض رصيده وتعديله:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_USERS_LIST

async def admin_users_search_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(
        "🔍 بحث عن مستخدم\n━━━━━━━━━━━━━━━━\n"
        "أدخل ID المستخدم أو اسمه أو يوزرنيمه:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]])
    )
    return ADMIN_USERS_SEARCH

async def admin_users_search_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    q = update.message.text.strip().lower().lstrip("@")
    data = load_data()
    users = data.get("users", {})
    matches = []
    for uid, info in users.items():
        name = (info.get("username") or "").lower()
        first = (info.get("first_name") or "").lower()
        if q == uid or q in name or q in first:
            matches.append((uid, info))
    if not matches:
        await update.message.reply_text(
            "❌ لا توجد نتائج.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")]])
        )
        return ADMIN_USERS_LIST
    keyboard = []
    for uid, info in matches[:30]:
        keyboard.append([InlineKeyboardButton(_user_label(uid, info), callback_data=f"user_view_{uid}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")])
    await update.message.reply_text(
        f"🔍 نتائج البحث ({len(matches)}):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_USERS_LIST

async def admin_user_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    uid = query.data.replace("user_view_", "")
    info = get_user(int(uid)) if uid.isdigit() else load_data().get("users", {}).get(uid, {})
    context.user_data["managed_user_id"] = uid
    name = info.get("username") or info.get("first_name") or uid
    keyboard = [
        [InlineKeyboardButton("✏️ تعديل الرصيد", callback_data="user_edit_balance")],
        [InlineKeyboardButton("🔙 رجوع", callback_data="admin_users")],
    ]
    await query.edit_message_text(
        f"👤 بيانات المستخدم\n━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: {uid}\n"
        f"👤 الاسم/اليوزر: {name}\n"
        f"💳 الرصيد الحالي: {info.get('balance', 0.0):.4f}$\n"
        f"👥 عدد إحالاته: {len(info.get('referrals', []))}\n"
        f"🔗 محال من: {info.get('referred_by') or 'لا أحد'}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_USER_VIEW

async def admin_user_edit_balance_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    uid = context.user_data.get("managed_user_id")
    info = load_data().get("users", {}).get(str(uid), {})
    await query.edit_message_text(
        f"✏️ تعديل رصيد المستخدم {uid}\n━━━━━━━━━━━━━━━━\n"
        f"💳 الرصيد الحالي: {info.get('balance', 0.0):.4f}$\n\n"
        f"أدخل القيمة الجديدة بالدولار (رقم موجب أو سالب أو 0):\n"
        f"• قيمة موجبة بدون إشارة = ضبط الرصيد على هذا المبلغ\n"
        f"• إشارة + قبل الرقم = إضافة للرصيد (مثلاً: +5)\n"
        f"• إشارة - قبل الرقم = خصم من الرصيد (مثلاً: -3)"
    )
    return ADMIN_USER_EDIT_BALANCE

async def admin_user_edit_balance_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text.strip()
    uid = context.user_data.get("managed_user_id")
    if not uid:
        await update.message.reply_text("⚠️ خطأ: لم يتم تحديد المستخدم.")
        return ADMIN_PANEL
    info = get_user(int(uid)) if str(uid).isdigit() else load_data().get("users", {}).get(str(uid), {})
    current = info.get("balance", 0.0)
    try:
        if text.startswith("+"):
            new_balance = current + float(text[1:])
            change_label = f"+{float(text[1:]):.4f}$"
        elif text.startswith("-"):
            new_balance = current - float(text[1:])
            change_label = f"-{float(text[1:]):.4f}$"
        else:
            new_balance = float(text)
            change_label = f"ضبط على {new_balance:.4f}$"
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح.")
        return ADMIN_USER_EDIT_BALANCE

    update_user(int(uid), {"balance": new_balance})

    # إشعار المستخدم
    try:
        await context.bot.send_message(
            chat_id=int(uid),
            text=(
                f"💳 تم تحديث رصيدك من قبل الإدارة\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"💰 رصيدك الحالي: {new_balance:.4f}$"
            ),
            reply_markup=main_menu_keyboard(int(uid))
        )
    except Exception as e:
        logger.error(f"Failed to notify user balance change: {e}")

    await update.message.reply_text(
        f"✅ تم تحديث رصيد المستخدم {uid}\n"
        f"📌 العملية: {change_label}\n"
        f"💳 الرصيد الجديد: {new_balance:.4f}$",
        reply_markup=main_menu_keyboard(ADMIN_ID)
    )
    return MAIN_MENU

# ======================== تعديل أسعار الخدمات ========================
async def admin_prices_platforms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    keyboard = []
    for pkey, pdata in SERVICES.items():
        keyboard.append([InlineKeyboardButton(pdata["name"], callback_data=f"adminprice_p_{pkey}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_panel")])
    await query.edit_message_text(
        "💵 تعديل الأسعار\n━━━━━━━━━━━━━━━━\nاختر المنصة:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_PRICES_PLATFORM

async def admin_prices_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    pkey = query.data.replace("adminprice_p_", "")
    context.user_data["admin_price_platform"] = pkey
    pdata = SERVICES.get(pkey)
    keyboard = []
    for ckey, cdata in pdata["categories"].items():
        if cdata["services"]:
            keyboard.append([InlineKeyboardButton(cdata["name"], callback_data=f"adminprice_c_{ckey}")])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin_prices")])
    await query.edit_message_text(
        f"💵 {pdata['name']}\n━━━━━━━━━━━━━━━━\nاختر التصنيف:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_PRICES_CATEGORY

async def admin_prices_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    ckey = query.data.replace("adminprice_c_", "")
    context.user_data["admin_price_category"] = ckey
    pkey = context.user_data.get("admin_price_platform")
    pdata = SERVICES.get(pkey)
    cdata = pdata["categories"].get(ckey)
    keyboard = []
    for svc in cdata["services"]:
        cur = get_customer_price(svc)
        custom_mark = "✏️" if get_custom_price(svc["id"]) is not None else ""
        keyboard.append([InlineKeyboardButton(
            f"{custom_mark}{svc['name'][:35]} | {cur:.4f}$",
            callback_data=f"adminprice_s_{svc['id']}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"adminprice_p_{pkey}")])
    await query.edit_message_text(
        f"💵 {cdata['name']}\n━━━━━━━━━━━━━━━━\n"
        f"اختر الخدمة لتعديل سعرها (السعر المعروض هو سعر الزبون لكل 1000):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_PRICES_SERVICE

async def admin_price_edit_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    svc_id = query.data.replace("adminprice_s_", "")
    context.user_data["admin_price_svc_id"] = svc_id
    _, _, svc = find_service_by_id(svc_id)
    if not svc:
        await query.edit_message_text("❌ الخدمة غير موجودة.")
        return ADMIN_PANEL
    custom = get_custom_price(svc_id)
    provider_price = get_live_price(svc)
    customer_price = get_customer_price(svc)
    keyboard = [[InlineKeyboardButton("♻️ إزالة السعر المخصص (رجوع لسعر المزود × المعامل)", callback_data="adminprice_clear")]]
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"adminprice_c_{context.user_data.get('admin_price_category')}")])
    await query.edit_message_text(
        f"✏️ تعديل سعر الخدمة\n━━━━━━━━━━━━━━━━\n"
        f"🔹 {svc['name']}\n\n"
        f"📦 سعر المزود: {provider_price:.4f}$ / 1000\n"
        f"💱 المعامل: ×{get_multiplier()}\n"
        f"💰 سعر الزبون الحالي: {customer_price:.4f}$ / 1000\n"
        f"{'✏️ سعر مخصص مفعّل: ' + str(custom) + '$' if custom is not None else '⚙️ السعر تلقائي (مزود × معامل)'}\n\n"
        f"أدخل السعر الجديد للزبون لكل 1000 (مثلاً: 0.25):",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_PRICE_EDIT

async def admin_price_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer("✅ تمت إزالة السعر المخصص", show_alert=True)
    svc_id = context.user_data.get("admin_price_svc_id")
    if svc_id:
        clear_custom_price(svc_id)
    # العودة لقائمة الخدمات
    ckey = context.user_data.get("admin_price_category")
    pkey = context.user_data.get("admin_price_platform")
    pdata = SERVICES.get(pkey)
    cdata = pdata["categories"].get(ckey)
    keyboard = []
    for svc in cdata["services"]:
        cur = get_customer_price(svc)
        custom_mark = "✏️" if get_custom_price(svc["id"]) is not None else ""
        keyboard.append([InlineKeyboardButton(
            f"{custom_mark}{svc['name'][:35]} | {cur:.4f}$",
            callback_data=f"adminprice_s_{svc['id']}"
        )])
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"adminprice_p_{pkey}")])
    await query.edit_message_text(
        f"💵 {cdata['name']}\n━━━━━━━━━━━━━━━━\nاختر الخدمة لتعديل سعرها:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADMIN_PRICES_SERVICE

async def admin_price_edit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text.strip()
    try:
        new_price = float(text)
        if new_price < 0:
            await update.message.reply_text("❌ يجب أن يكون السعر أكبر من أو يساوي 0.")
            return ADMIN_PRICE_EDIT
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح.")
        return ADMIN_PRICE_EDIT

    svc_id = context.user_data.get("admin_price_svc_id")
    if not svc_id:
        await update.message.reply_text("⚠️ خطأ: لم يتم تحديد الخدمة.")
        return MAIN_MENU
    set_custom_price(svc_id, new_price)
    _, _, svc = find_service_by_id(svc_id)
    await update.message.reply_text(
        f"✅ تم تحديث السعر بنجاح!\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🔹 الخدمة: {svc['name'] if svc else svc_id}\n"
        f"💰 السعر الجديد للزبون: {new_price:.4f}$ / 1000",
        reply_markup=main_menu_keyboard(ADMIN_ID)
    )
    return MAIN_MENU

async def set_multiplier_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ غير مصرح لك!", show_alert=True)
        return
    await query.answer()
    multiplier = get_multiplier()
    await query.edit_message_text(
        f"💱 تعديل معامل ضرب السعر\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"المعامل الحالي: ×{multiplier}\n\n"
        f"أدخل القيمة الجديدة (مثلاً: 2.5):\n"
        f"السعر للزبون = سعر المزود × القيمة المدخلة"
    )
    return ADMIN_MULTIPLIER

async def receive_multiplier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text.strip()
    try:
        val = float(text)
        if val <= 0:
            await update.message.reply_text("❌ يجب أن تكون القيمة أكبر من 0.")
            return ADMIN_MULTIPLIER
        set_multiplier(val)
        await update.message.reply_text(
            f"✅ تم تحديث معامل الضرب بنجاح!\n"
            f"💱 القيمة الجديدة: ×{val}\n\n"
            f"سعر الزبون = سعر المزود × {val}",
            reply_markup=main_menu_keyboard(ADMIN_ID)
        )
        return MAIN_MENU
    except ValueError:
        await update.message.reply_text("❌ الرجاء إدخال رقم صحيح.")
        return ADMIN_MULTIPLIER

# ======================== تشغيل البوت ========================
async def post_init(application):
    """تسجيل قائمة الأوامر (Menu) في تيليجرام."""
    from telegram import BotCommand
    await application.bot.set_my_commands([
        BotCommand("start", "🚀 بدء استخدام البوت / القائمة الرئيسية"),
    ])

def main():
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(charge_menu, pattern="^charge$"),
                CallbackQueryHandler(service_menu, pattern="^service$"),
                CallbackQueryHandler(order_status_menu, pattern="^order_status$"),
                CallbackQueryHandler(referral_menu, pattern="^referral$"),
                CallbackQueryHandler(support, pattern="^support$"),
                CallbackQueryHandler(admin_panel, pattern="^admin_panel$"),
                CallbackQueryHandler(custom_button_selected, pattern="^cbtn_[a-f0-9]+$"),
                CallbackQueryHandler(show_main_menu, pattern="^main$"),
            ],
            CHARGE_MENU: [
                CallbackQueryHandler(sham_cash_menu, pattern="^sham_cash$"),
                CallbackQueryHandler(syriatel_cash_menu, pattern="^syriatel_cash$"),
                CallbackQueryHandler(show_main_menu, pattern="^main$"),
                CallbackQueryHandler(verify_payment_start, pattern="^verify_payment$"),
            ],
            SHAM_MENU: [
                CallbackQueryHandler(sham_syp, pattern="^sham_syp$"),
                CallbackQueryHandler(sham_dollar, pattern="^sham_dollar$"),
                CallbackQueryHandler(charge_menu, pattern="^charge$"),
                CallbackQueryHandler(sham_cash_menu, pattern="^sham_cash$"),
                CallbackQueryHandler(verify_payment_start, pattern="^verify_payment$"),
                CallbackQueryHandler(show_main_menu, pattern="^main$"),
            ],
            SHAM_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_amount)
            ],
            SHAM_TX_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_tx_id)
            ],
            SERVICE_PLATFORM: [
                CallbackQueryHandler(platform_selected, pattern="^platform_"),
                CallbackQueryHandler(show_main_menu, pattern="^main$"),
                CallbackQueryHandler(service_menu, pattern="^service$"),
            ],
            SERVICE_TYPE: [
                CallbackQueryHandler(category_selected, pattern="^category_"),
                CallbackQueryHandler(platform_selected, pattern="^platform_"),
                CallbackQueryHandler(custom_button_selected, pattern="^cbtn_[a-f0-9]+$"),
                CallbackQueryHandler(show_main_menu, pattern="^main$"),
                CallbackQueryHandler(service_menu, pattern="^service$"),
            ],
            SERVICE_SELECT: [
                CallbackQueryHandler(service_selected, pattern="^svc_"),
                CallbackQueryHandler(proceed_order, pattern="^proceed_order$"),
                CallbackQueryHandler(category_selected, pattern="^category_"),
                CallbackQueryHandler(platform_selected, pattern="^platform_"),
                CallbackQueryHandler(custom_button_selected, pattern="^cbtn_[a-f0-9]+$"),
                CallbackQueryHandler(show_main_menu, pattern="^main$"),
            ],
            ORDER_QUANTITY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_quantity)
            ],
            ORDER_LINK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)
            ],
            ORDER_CONFIRM: [
                CallbackQueryHandler(confirm_order, pattern="^confirm_order$"),
                CallbackQueryHandler(show_main_menu, pattern="^main$"),
            ],
            ADMIN_PANEL: [
                CallbackQueryHandler(set_multiplier_prompt, pattern="^set_multiplier$"),
                CallbackQueryHandler(admin_users_list, pattern="^admin_users$"),
                CallbackQueryHandler(admin_prices_platforms, pattern="^admin_prices$"),
                CallbackQueryHandler(admin_broadcast_prompt, pattern="^admin_broadcast$"),
                CallbackQueryHandler(admin_cbtns_list, pattern="^admin_cbtns$"),
                CallbackQueryHandler(admin_panel, pattern="^admin_panel$"),
                CallbackQueryHandler(show_main_menu, pattern="^main$"),
            ],
            ADMIN_CBTN_LIST: [
                CallbackQueryHandler(admin_cbtn_new_prompt, pattern="^cbtnnew$"),
                CallbackQueryHandler(admin_cbtn_view, pattern="^cbtnv_"),
                CallbackQueryHandler(admin_cbtns_list, pattern="^admin_cbtns$"),
                CallbackQueryHandler(admin_panel, pattern="^admin_panel$"),
            ],
            ADMIN_CBTN_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_cbtn_new_receive_name),
                CallbackQueryHandler(admin_cbtns_list, pattern="^admin_cbtns$"),
                CommandHandler("cancel", show_main_menu),
            ],
            ADMIN_CBTN_VIEW: [
                CallbackQueryHandler(admin_cbtn_add_svc_prompt, pattern="^cbtnsvc_add_"),
                CallbackQueryHandler(admin_cbtn_list_svc, pattern="^cbtnsvc_list_"),
                CallbackQueryHandler(admin_cbtn_del_svc, pattern="^cbtnsvc_del_"),
                CallbackQueryHandler(admin_cbtn_change_loc, pattern="^cbtnloc_"),
                CallbackQueryHandler(admin_cbtn_set_loc, pattern="^cbtnsetloc_"),
                CallbackQueryHandler(admin_cbtn_rename_prompt, pattern="^cbtnren_"),
                CallbackQueryHandler(admin_cbtn_delete, pattern="^cbtndel_"),
                CallbackQueryHandler(admin_cbtn_view, pattern="^cbtnv_"),
                CallbackQueryHandler(admin_cbtns_list, pattern="^admin_cbtns$"),
            ],
            ADMIN_CBTN_RENAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_cbtn_rename_receive),
                CallbackQueryHandler(admin_cbtn_view, pattern="^cbtnv_"),
                CommandHandler("cancel", show_main_menu),
            ],
            ADMIN_CBTN_ADD_SVC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_cbtn_add_svc_receive),
                CallbackQueryHandler(admin_cbtn_view, pattern="^cbtnv_"),
                CommandHandler("cancel", show_main_menu),
            ],
            ADMIN_BROADCAST_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast_send),
                CallbackQueryHandler(admin_panel, pattern="^admin_panel$"),
                CommandHandler("cancel", show_main_menu),
            ],
            ORDER_STATUS_LIST: [
                CallbackQueryHandler(order_view_detail, pattern="^order_view_"),
                CallbackQueryHandler(order_status_menu, pattern="^order_status$"),
                CallbackQueryHandler(show_main_menu, pattern="^main$"),
            ],
            ADMIN_MULTIPLIER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_multiplier)
            ],
            ADMIN_CONFIRM_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_dollar_amount)
            ],
            ADMIN_USERS_LIST: [
                CallbackQueryHandler(admin_users_list, pattern="^admin_users$"),
                CallbackQueryHandler(admin_users_list, pattern="^users_page_"),
                CallbackQueryHandler(admin_users_search_prompt, pattern="^users_search$"),
                CallbackQueryHandler(admin_user_view, pattern="^user_view_"),
                CallbackQueryHandler(admin_panel, pattern="^admin_panel$"),
            ],
            ADMIN_USERS_SEARCH: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_users_search_receive),
                CallbackQueryHandler(admin_users_list, pattern="^admin_users$"),
            ],
            ADMIN_USER_VIEW: [
                CallbackQueryHandler(admin_user_edit_balance_prompt, pattern="^user_edit_balance$"),
                CallbackQueryHandler(admin_users_list, pattern="^admin_users$"),
            ],
            ADMIN_USER_EDIT_BALANCE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_user_edit_balance_receive)
            ],
            ADMIN_PRICES_PLATFORM: [
                CallbackQueryHandler(admin_prices_categories, pattern="^adminprice_p_"),
                CallbackQueryHandler(admin_panel, pattern="^admin_panel$"),
            ],
            ADMIN_PRICES_CATEGORY: [
                CallbackQueryHandler(admin_prices_services, pattern="^adminprice_c_"),
                CallbackQueryHandler(admin_prices_platforms, pattern="^admin_prices$"),
            ],
            ADMIN_PRICES_SERVICE: [
                CallbackQueryHandler(admin_price_edit_prompt, pattern="^adminprice_s_"),
                CallbackQueryHandler(admin_prices_categories, pattern="^adminprice_p_"),
            ],
            ADMIN_PRICE_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_price_edit_receive),
                CallbackQueryHandler(admin_price_clear, pattern="^adminprice_clear$"),
                CallbackQueryHandler(admin_prices_services, pattern="^adminprice_c_"),
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    # محادثة منفصلة لتأكيد الدفع من قبل الأدمن (تبدأ بضغط زر التأكيد)
    admin_payment_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_approve_payment, pattern="^admin_approve_")],
        states={
            ADMIN_CONFIRM_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_receive_dollar_amount)
            ],
        },
        fallbacks=[CommandHandler("start", start)],
        per_user=True,
        per_chat=True,
        allow_reentry=True,
    )

    application.add_handler(admin_payment_conv)
    application.add_handler(conv_handler)

    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_subscription$"))
    application.add_handler(CallbackQueryHandler(admin_reject_payment, pattern="^admin_reject_"))
    application.add_handler(CallbackQueryHandler(my_referrals, pattern="^my_referrals$"))

    print("🤖 البوت يعمل الآن...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
