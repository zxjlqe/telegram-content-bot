import sqlite3
import asyncio
import os

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================================================
# إعدادات البوت
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_IDS", "0"))

DB_NAME = "/data/bot.db"

os.makedirs("/data", exist_ok=True)

# =========================================================
# قاعدة البيانات
# =========================================================

db = sqlite3.connect(DB_NAME, check_same_thread=False)
db.row_factory = sqlite3.Row


def init_db():

    cur = db.cursor()

    # المستخدمين
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT
        )
    """)

    # الإعدادات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # الأقسام
    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            parent_id INTEGER
        )
    """)

    # ترقية قاعدة البيانات القديمة إذا كانت categories موجودة
    try:
        cur.execute(
            "SELECT parent_id FROM categories LIMIT 1"
        )
    except sqlite3.OperationalError:
        cur.execute(
            "ALTER TABLE categories ADD COLUMN parent_id INTEGER"
        )

    # المحتوى
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            title TEXT,
            body TEXT NOT NULL
        )
    """)

    # الإعدادات الافتراضية
    defaults = {
        "welcome": "أهلاً وسهلاً بك 👋\n\nاختر القسم الذي تريد الدخول إليه:",
        "support_value": ""
    }

    for key, value in defaults.items():

        cur.execute(
            """
            INSERT OR IGNORE INTO settings(key,value)
            VALUES(?,?)
            """,
            (key, value)
        )

    db.commit()


# =========================================================
# الإعدادات
# =========================================================

def get_setting(key):

    row = db.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()

    return row["value"] if row else ""


def set_setting(key, value):

    db.execute(
        """
        INSERT INTO settings(key,value)
        VALUES(?,?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
        """,
        (key, value)
    )

    db.commit()


# =========================================================
# المستخدمين
# =========================================================

def save_user(user):

    if not user:
        return

    db.execute(
        """
        INSERT OR REPLACE INTO users
        (user_id, username, first_name)
        VALUES (?, ?, ?)
        """,
        (
            user.id,
            user.username or "",
            user.first_name or ""
        )
    )

    db.commit()


def get_users():

    return db.execute(
        "SELECT user_id FROM users"
    ).fetchall()


def users_count():

    return db.execute(
        "SELECT COUNT(*) AS total FROM users"
    ).fetchone()["total"]


# =========================================================
# الأقسام
# =========================================================

def get_categories(parent_id=None):

    if parent_id is None:

        return db.execute(
            """
            SELECT *
            FROM categories
            WHERE parent_id IS NULL
            ORDER BY id
            """
        ).fetchall()

    return db.execute(
        """
        SELECT *
        FROM categories
        WHERE parent_id=?
        ORDER BY id
        """,
        (parent_id,)
    ).fetchall()


def get_category(category_id):

    return db.execute(
        """
        SELECT *
        FROM categories
        WHERE id=?
        """,
        (category_id,)
    ).fetchone()


def add_category(name, parent_id=None):

    cur = db.cursor()

    cur.execute(
        """
        INSERT INTO categories(name,parent_id)
        VALUES(?,?)
        """,
        (name, parent_id)
    )

    db.commit()

    return cur.lastrowid


def delete_category(category_id):

    children = get_categories(category_id)

    for child in children:
        delete_category(child["id"])

    db.execute(
        "DELETE FROM contents WHERE category_id=?",
        (category_id,)
    )

    db.execute(
        "DELETE FROM categories WHERE id=?",
        (category_id,)
    )

    db.commit()


# =========================================================
# المحتوى
# =========================================================

def get_contents(category_id):

    return db.execute(
        """
        SELECT *
        FROM contents
        WHERE category_id=?
        ORDER BY id
        """,
        (category_id,)
    ).fetchall()


def get_content(content_id):

    return db.execute(
        """
        SELECT *
        FROM contents
        WHERE id=?
        """,
        (content_id,)
    ).fetchone()


def add_content(category_id, title, body):

    db.execute(
        """
        INSERT INTO contents
        (category_id,title,body)
        VALUES(?,?,?)
        """,
        (
            category_id,
            title,
            body
        )
    )

    db.commit()


def delete_content(content_id):

    db.execute(
        "DELETE FROM contents WHERE id=?",
        (content_id,)
    )

    db.commit()


# =========================================================
# زر الرجوع للمستخدم
# =========================================================

def user_back_button(parent_id):

    if parent_id is None:

        return InlineKeyboardButton(
            "🔙 الرئيسية",
            callback_data="home"
        )

    return InlineKeyboardButton(
        "🔙 رجوع",
        callback_data=f"category_{parent_id}"
    )


# =========================================================
# عرض القسم للمستخدم
# =========================================================

async def show_category(query, category_id):

    category = get_category(category_id)

    if not category:
        return

    children = get_categories(category_id)
    contents = get_contents(category_id)

    buttons = []

    # الأقسام الفرعية
    for child in children:

        buttons.append([
            InlineKeyboardButton(
                f"📁 {child['name']}",
                callback_data=f"category_{child['id']}"
            )
        ])

    # المحتوى الموجود مباشرة داخل القسم
    for item in contents:

        title = item["title"] or ""

        if title.strip():
            button_text = f"📄 {title}"
        else:
            button_text = "📄 محتوى"

        buttons.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"content_{item['id']}"
            )
        ])

    # إذا القسم فاضي
    if not buttons:

        buttons.append([
            InlineKeyboardButton(
                "لا يوجد محتوى حالياً",
                callback_data="nothing"
            )
        ])

    # زر الرجوع
    parent_id = category["parent_id"]

    buttons.append([
        user_back_button(parent_id)
    ])

    await query.edit_message_text(
        f"📂 {category['name']}",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# =========================================================
# عرض المحتوى
# =========================================================

async def show_content(query, content_id):

    content = get_content(content_id)

    if not content:
        return

    category = get_category(
        content["category_id"]
    )

    body = content["body"]

    title = content["title"] or ""

    if title.strip():

        text = (
            f"📌 {title}\n\n"
            f"{body}"
        )

    else:

        text = body

    keyboard = InlineKeyboardMarkup([
        [
            user_back_button(
                category["id"]
            )
        ]
    ])

    await query.edit_message_text(
        text,
        reply_markup=keyboard
    )


# =========================================================
# القائمة الرئيسية
# =========================================================

def main_menu():

    buttons = []

    categories = get_categories()

    for category in categories:

        buttons.append([
            InlineKeyboardButton(
                f"📁 {category['name']}",
                callback_data=f"category_{category['id']}"
            )
        ])

    support = get_setting(
        "support_value"
    )

    if support:

        buttons.append([
            InlineKeyboardButton(
                "🤝 الدعم",
                callback_data="support"
            )
        ])

    return InlineKeyboardMarkup(buttons)


# =========================================================
# لوحة التحكم
# =========================================================

def admin_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "👥 عدد المستخدمين",
                callback_data="admin_users"
            )
        ],

        [
            InlineKeyboardButton(
                "📢 الإذاعة",
                callback_data="admin_broadcast"
            )
        ],

        [
            InlineKeyboardButton(
                "📝 تعديل رسالة الترحيب",
                callback_data="admin_welcome"
            )
        ],

        [
            InlineKeyboardButton(
                "🤝 إعدادات الدعم",
                callback_data="admin_support"
            )
        ],

        [
            InlineKeyboardButton(
                "📂 إدارة الأقسام",
                callback_data="admin_categories"
            )
        ],

        [
            InlineKeyboardButton(
                "📚 إدارة المحتوى",
                callback_data="admin_content"
            )
        ],

    ])


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user:
        save_user(
            update.effective_user
        )

    await update.message.reply_text(
        get_setting("welcome"),
        reply_markup=main_menu()
    )


# =========================================================
# ADMIN
# =========================================================

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.effective_user:
        return

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.clear()

    await update.message.reply_text(
        "🛠️ لوحة التحكم\n\n"
        f"👥 عدد مستخدمي البوت: {users_count()}",
        reply_markup=admin_menu()
    )


# =========================================================
# أزرار البوت
# =========================================================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query

    await query.answer()

    data = query.data

    # =====================================================
    # لا يوجد شيء
    # =====================================================

    if data == "nothing":
        return

    # =====================================================
    # الرئيسية
    # =====================================================

    if data == "home":

        await query.edit_message_text(
            get_setting("welcome"),
            reply_markup=main_menu()
        )

        return

    # =====================================================
    # قسم
    # =====================================================

    if data.startswith("category_"):

        category_id = int(
            data.replace(
                "category_",
                ""
            )
        )

        await show_category(
            query,
            category_id
        )

        return

    # =====================================================
    # محتوى
    # =====================================================

    if data.startswith("content_"):

        content_id = int(
            data.replace(
                "content_",
                ""
            )
        )

        await show_content(
            query,
            content_id
        )

        return

    # =====================================================
    # الدعم - تيليجرام
    # =====================================================

    if data == "support":

        username = get_setting(
            "support_value"
        ).strip()

        if not username:
            return

        username_clean = username.replace(
            "@",
            ""
        )

        if username.startswith("http"):

            url = username

        else:

            url = (
                "https://t.me/"
                + username_clean
            )

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "💬 تواصل معي على تيليجرام",
                    url=url
                )
            ],

            [
                InlineKeyboardButton(
                    "🔙 رجوع",
                    callback_data="home"
                )
            ]

        ])

        await query.edit_message_text(
            "🤝 للتواصل مع الدعم:",
            reply_markup=keyboard
        )

        return

    # =====================================================
    # حماية لوحة التحكم
    # =====================================================

    if not query.from_user:
        return

    if query.from_user.id != ADMIN_ID:
        return

    # =====================================================
    # عدد المستخدمين
    # =====================================================

    if data == "admin_users":

        await query.edit_message_text(

            "👥 إحصائيات البوت\n\n"
            f"👤 عدد مستخدمي البوت: {users_count()}",

            reply_markup=admin_menu()
        )

        return

    # =====================================================
    # تعديل الترحيب
    # =====================================================

    if data == "admin_welcome":

        context.user_data["action"] = "welcome"

        await query.edit_message_text(
            "📝 أرسل الآن رسالة الترحيب الجديدة:"
        )

        return

    # =====================================================
    # الإذاعة
    # =====================================================

    if data == "admin_broadcast":

        context.user_data["action"] = "broadcast"

        await query.edit_message_text(
            "📢 أرسل الآن الرسالة التي تريد إرسالها لجميع مستخدمي البوت:"
        )

        return

    # =====================================================
    # إعدادات الدعم
    # =====================================================

    if data == "admin_support":

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "💬 حساب تيليجرام للدعم",
                    callback_data="support_telegram"
                )
            ],

            [
                InlineKeyboardButton(
                    "❌ تعطيل الدعم",
                    callback_data="support_disable"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔙 رجوع",
                    callback_data="admin_back"
                )
            ]

        ])

        await query.edit_message_text(
            "🤝 إعدادات الدعم\n\n"
            "اختر إعداد الدعم:",
            reply_markup=keyboard
        )

        return

    # =====================================================
    # دعم تيليجرام
    # =====================================================

    if data == "support_telegram":

        context.user_data[
            "action"
        ] = "support_telegram"

        await query.edit_message_text(

            "💬 أرسل يوزر حسابك في تيليجرام.\n\n"

            "مثال:\n"
            "@username\n\n"

            "أو أرسل رابط حسابك مباشرة."

        )

        return

    # =====================================================
    # تعطيل الدعم
    # =====================================================

    if data == "support_disable":

        set_setting(
            "support_value",
            ""
        )

        await query.edit_message_text(
            "✅ تم تعطيل زر الدعم.",
            reply_markup=admin_menu()
        )

        return

    # =====================================================
    # إدارة الأقسام
    # =====================================================

    if data == "admin_categories":

        await admin_categories_root(
            query
        )

        return

    # =====================================================
    # فتح قسم في لوحة التحكم
    # =====================================================

    if data.startswith("admin_cat_"):

        category_id = int(
            data.replace(
                "admin_cat_",
                ""
            )
        )

        await admin_category(
            query,
            category_id
        )

        return

    # =====================================================
    # إضافة قسم فرعي
    # =====================================================

    if data.startswith("add_subcategory_"):

        parent_id = int(
            data.replace(
                "add_subcategory_",
                ""
            )
        )

        context.user_data[
            "action"
        ] = f"add_category_{parent_id}"

        await query.edit_message_text(
            "📂 أرسل اسم القسم الفرعي الجديد:"
        )

        return

    # =====================================================
    # إضافة قسم رئيسي
    # =====================================================

    if data == "add_root_category":

        context.user_data[
            "action"
        ] = "add_category_root"

        await query.edit_message_text(
            "📂 أرسل اسم القسم الرئيسي الجديد:"
        )

        return

    # =====================================================
    # حذف قسم
    # =====================================================

    if data.startswith("delete_category_"):

        category_id = int(
            data.replace(
                "delete_category_",
                ""
            )
        )

        delete_category(
            category_id
        )

        await admin_categories_root(
            query
        )

        return

    # =====================================================
    # إدارة المحتوى
    # =====================================================

    if data == "admin_content":

        await admin_content_root(
            query
        )

        return

    # =====================================================
    # إضافة محتوى داخل قسم
    # =====================================================

    if data.startswith("add_content_"):

        category_id = int(
            data.replace(
                "add_content_",
                ""
            )
        )

        context.user_data[
            "action"
        ] = f"add_content_{category_id}"

        await query.edit_message_text(

            "📄 أرسل المحتوى الآن.\n\n"

            "إذا تريد عنوانًا:\n"
            "السطر الأول = العنوان\n"
            "والأسطر التالية = المحتوى.\n\n"

            "مثال:\n"
            "بنود الحظر\n"
            "هنا تكتب المحتوى كاملًا...\n\n"

            "وإذا لا تريد عنوانًا، أرسل المحتوى مباشرة."

        )

        return

    # =====================================================
    # حذف محتوى
    # =====================================================

    if data.startswith("delete_content_"):

        content_id = int(
            data.replace(
                "delete_content_",
                ""
            )
        )

        content = get_content(
            content_id
        )

        if content:

            category_id = content[
                "category_id"
            ]

            delete_content(
                content_id
            )

            await admin_category(
                query,
                category_id
            )

        return

    # =====================================================
    # رجوع لوحة التحكم
    # =====================================================

    if data == "admin_back":

        await query.edit_message_text(

            "🛠️ لوحة التحكم\n\n"
            f"👥 عدد مستخدمي البوت: {users_count()}",

            reply_markup=admin_menu()
        )

        return


# =========================================================
# لوحة إدارة الأقسام الرئيسية
# =========================================================

async def admin_categories_root(query):

    buttons = []

    buttons.append([

        InlineKeyboardButton(
            "➕ إضافة قسم رئيسي",
            callback_data="add_root_category"
        )

    ])

    categories = get_categories()

    for category in categories:

        buttons.append([

            InlineKeyboardButton(
                f"📂 {category['name']}",
                callback_data=f"admin_cat_{category['id']}"
            )

        ])

    buttons.append([

        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data="admin_back"
        )

    ])

    await query.edit_message_text(

        "📂 إدارة الأقسام\n\n"
        "هنا تستطيع بناء الأقسام بالشكل الذي تريده.",

        reply_markup=InlineKeyboardMarkup(
            buttons
        )
    )


# =========================================================
# إدارة قسم معين
# =========================================================

async def admin_category(query, category_id):

    category = get_category(
        category_id
    )

    if not category:
        return

    buttons = []

    # إضافة قسم فرعي
    buttons.append([

        InlineKeyboardButton(
            "➕ إضافة قسم فرعي",
            callback_data=f"add_subcategory_{category_id}"
        )

    ])

    # إضافة محتوى مباشر
    buttons.append([

        InlineKeyboardButton(
            "📄 إضافة محتوى هنا",
            callback_data=f"add_content_{category_id}"
        )

    ])

    # الأقسام الفرعية
    children = get_categories(
        category_id
    )

    for child in children:

        buttons.append([

            InlineKeyboardButton(
                f"📁 {child['name']}",
                callback_data=f"admin_cat_{child['id']}"
            ),

            InlineKeyboardButton(
                "🗑️",
                callback_data=f"delete_category_{child['id']}"
            )

        ])

    # المحتوى المباشر
    contents = get_contents(
        category_id
    )

    for item in contents:

        title = item["title"] or "محتوى"

        buttons.append([

            InlineKeyboardButton(
                f"📄 {title}",
                callback_data=f"delete_content_{item['id']}"
            )

        ])

    # حذف القسم الحالي
    buttons.append([

        InlineKeyboardButton(
            "🗑️ حذف هذا القسم",
            callback_data=f"delete_category_{category_id}"
        )

    ])

    # رجوع
    parent_id = category["parent_id"]

    if parent_id is None:

        back = "admin_categories"

    else:

        back = f"admin_cat_{parent_id}"

    buttons.append([

        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data=back
        )

    ])

    await query.edit_message_text(

        f"📂 {category['name']}\n\n"
        "يمكنك هنا إضافة أقسام فرعية أو محتوى مباشرة.",

        reply_markup=InlineKeyboardMarkup(
            buttons
        )
    )


# =========================================================
# إدارة المحتوى
# =========================================================

async def admin_content_root(query):

    categories = get_categories()

    buttons = []

    for category in categories:

        buttons.append([

            InlineKeyboardButton(
                f"📂 {category['name']}",
                callback_data=f"admin_cat_{category['id']}"
            )

        ])

    buttons.append([

        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data="admin_back"
        )

    ])

    await query.edit_message_text(

        "📚 إدارة المحتوى\n\n"
        "اختر القسم الذي تريد إضافة المحتوى إليه.",

        reply_markup=InlineKeyboardMarkup(
            buttons
        )
    )


# =========================================================
# استقبال رسائل الأدمن
# =========================================================

async def admin_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.effective_user:
        return

    if update.effective_user.id != ADMIN_ID:
        return

    if not update.message:
        return

    action = context.user_data.get(
        "action"
    )

    if not action:
        return

    text = update.message.text

    if not text:
        return

    # =====================================================
    # الترحيب
    # =====================================================

    if action == "welcome":

        set_setting(
            "welcome",
            text
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ تم تعديل رسالة الترحيب بنجاح.",
            reply_markup=admin_menu()
        )

        return

    # =====================================================
    # دعم تيليجرام
    # =====================================================

    if action == "support_telegram":

        set_setting(
            "support_value",
            text.strip()
        )

        context.user_data.clear()

        await update.message.reply_text(

            "✅ تم حفظ حساب الدعم في تيليجرام.\n\n"
            "سيظهر زر الدعم للمستخدمين.",

            reply_markup=admin_menu()
        )

        return

    # =====================================================
    # إضافة قسم رئيسي
    # =====================================================

    if action == "add_category_root":

        add_category(
            text.strip(),
            None
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ تم إضافة القسم الرئيسي.",
            reply_markup=admin_menu()
        )

        return

    # =====================================================
    # إضافة قسم فرعي
    # =====================================================

    if action.startswith(
        "add_category_"
    ):

        parent_id = int(
            action.replace(
                "add_category_",
                ""
            )
        )

        add_category(
            text.strip(),
            parent_id
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ تم إضافة القسم الفرعي بنجاح.",
            reply_markup=admin_menu()
        )

        return

    # =====================================================
    # إضافة محتوى
    # =====================================================

    if action.startswith(
        "add_content_"
    ):

        category_id = int(
            action.replace(
                "add_content_",
                ""
            )
        )

        lines = text.splitlines()

        if len(lines) >= 2:

            title = lines[0].strip()

            body = "\n".join(
                lines[1:]
            ).strip()

        else:

            title = ""

            body = text.strip()

        add_content(
            category_id,
            title,
            body
        )

        context.user_data.clear()

        await update.message.reply_text(

            "✅ تم حفظ المحتوى.\n\n"
            "سيظهر داخل القسم الذي اخترته.",

            reply_markup=admin_menu()
        )

        return

    # =====================================================
    # الإذاعة
    # =====================================================

    if action == "broadcast":

        context.user_data.clear()

        users = get_users()

        sent = 0
        failed = 0

        await update.message.reply_text(

            "📢 بدأت الإذاعة...\n\n"
            f"👥 المستهدفون: {len(users)}"

        )

        for user in users:

            try:

                await context.bot.send_message(
                    chat_id=user["user_id"],
                    text=text
                )

                sent += 1

            except Exception:

                failed += 1

            await asyncio.sleep(
                0.05
            )

        await update.message.reply_text(

            "✅ انتهت الإذاعة.\n\n"

            f"📨 تم الإرسال: {sent}\n"
            f"❌ فشل الإرسال: {failed}\n"
            f"👥 الإجمالي: {len(users)}",

            reply_markup=admin_menu()
        )

        return


# =========================================================
# تشغيل البوت
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN غير موجود في Deployka."
        )

    if ADMIN_ID == 0:

        raise RuntimeError(
            "ADMIN_IDS غير موجود في Deployka."
        )

    init_db()

    app = Application.builder().token(
        BOT_TOKEN
    ).build()

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            buttons
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            admin_messages
        )
    )

    print(
        "BOT IS RUNNING..."
    )

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":

    main()