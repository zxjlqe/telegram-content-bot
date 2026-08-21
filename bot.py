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

# =========================================================
# قاعدة البيانات
# =========================================================

db = sqlite3.connect(DB_NAME, check_same_thread=False)
db.row_factory = sqlite3.Row


def init_db():
    cur = db.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER NOT NULL,
            title TEXT,
            body TEXT NOT NULL
        )
    """)

    defaults = {
        "welcome": "أهلاً وسهلاً بك 👋\n\nاختر القسم الذي تريد الدخول إليه:",
        "support_type": "whatsapp",
        "support_value": ""
    }

    for key, value in defaults.items():
        cur.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
            (key, value)
        )

    db.commit()


def get_setting(key):
    row = db.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()

    return row["value"] if row else ""


def set_setting(key, value):
    db.execute("""
        INSERT INTO settings(key,value)
        VALUES(?,?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
    """, (key, value))

    db.commit()


# =========================================================
# المستخدمين
# =========================================================

def save_user(user):
    if not user:
        return

    db.execute("""
        INSERT OR REPLACE INTO users
        (user_id, username, first_name)
        VALUES (?, ?, ?)
    """, (
        user.id,
        user.username or "",
        user.first_name or ""
    ))

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

def get_categories():
    return db.execute(
        "SELECT * FROM categories ORDER BY id"
    ).fetchall()


def get_category(category_id):
    return db.execute(
        "SELECT * FROM categories WHERE id=?",
        (category_id,)
    ).fetchone()


def get_contents(category_id):
    return db.execute("""
        SELECT *
        FROM contents
        WHERE category_id=?
        ORDER BY id
    """, (category_id,)).fetchall()


# =========================================================
# القوائم
# =========================================================

def main_menu():
    buttons = []

    for category in get_categories():
        buttons.append([
            InlineKeyboardButton(
                category["name"],
                callback_data=f"category_{category['id']}"
            )
        ])

    support = get_setting("support_value")

    if support:
        buttons.append([
            InlineKeyboardButton(
                "🤝 الدعم",
                callback_data="support"
            )
        ])

    return InlineKeyboardMarkup(buttons)


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
        save_user(update.effective_user)

    if not update.message:
        return

    await update.message.reply_text(
        get_setting("welcome"),
        reply_markup=main_menu()
    )


# =========================================================
# لوحة التحكم
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
# الأزرار
# =========================================================

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    await query.answer()

    data = query.data

    # -----------------------------------------------------
    # الأقسام للمستخدم
    # -----------------------------------------------------

    if data.startswith("category_"):
        category_id = int(
            data.replace("category_", "")
        )

        category = get_category(category_id)

        if not category:
            return

        contents = get_contents(category_id)

        if not contents:
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 رجوع",
                        callback_data="home"
                    )
                ]
            ])

            await query.edit_message_text(
                "لا يوجد محتوى في هذا القسم حالياً.",
                reply_markup=keyboard
            )

            return

        message = ""

        for item in contents:
            title = item["title"] or ""
            body = item["body"]

            if title.strip():
                message += (
                    f"📌 {title}\n\n"
                    f"{body}\n\n"
                )
            else:
                message += f"{body}\n\n"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🔙 رجوع",
                    callback_data="home"
                )
            ]
        ])

        await query.edit_message_text(
            message.strip(),
            reply_markup=keyboard
        )

        return

    # -----------------------------------------------------
    # رجوع
    # -----------------------------------------------------

    if data == "home":
        await query.edit_message_text(
            get_setting("welcome"),
            reply_markup=main_menu()
        )

        return

    # -----------------------------------------------------
    # الدعم
    # -----------------------------------------------------

    if data == "support":
        support_type = get_setting("support_type")
        support_value = get_setting("support_value")

        if not support_value:
            return

        if support_type == "instagram":
            if support_value.startswith("http"):
                url = support_value
            else:
                url = (
                    "https://instagram.com/"
                    + support_value.replace("@", "")
                )

            text = "📸 للتواصل معي عبر إنستجرام:"
            button_text = "📸 إنستجرام"

        else:
            clean_number = (
                support_value
                .replace("+", "")
                .replace(" ", "")
                .replace("-", "")
            )

            if support_value.startswith("http"):
                url = support_value
            else:
                url = f"https://wa.me/{clean_number}"

            text = "📱 للتواصل معي عبر واتساب:"
            button_text = "📱 واتساب"

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    button_text,
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
            text,
            reply_markup=keyboard
        )

        return

    # =====================================================
    # لوحة التحكم
    # =====================================================

    if not query.from_user:
        return

    if query.from_user.id != ADMIN_ID:
        return

    # -----------------------------------------------------
    # عدد المستخدمين
    # -----------------------------------------------------

    if data == "admin_users":
        await query.edit_message_text(
            "👥 إحصائيات البوت\n\n"
            f"👤 عدد مستخدمي البوت: {users_count()}",
            reply_markup=admin_menu()
        )

        return

    # -----------------------------------------------------
    # تعديل الترحيب
    # -----------------------------------------------------

    if data == "admin_welcome":
        context.user_data["action"] = "welcome"

        await query.edit_message_text(
            "📝 أرسل الآن رسالة الترحيب الجديدة:"
        )

        return

    # -----------------------------------------------------
    # الإذاعة
    # -----------------------------------------------------

    if data == "admin_broadcast":
        context.user_data["action"] = "broadcast"

        await query.edit_message_text(
            "📢 أرسل الآن الرسالة التي تريد إرسالها لجميع مستخدمي البوت:"
        )

        return

    # -----------------------------------------------------
    # إعدادات الدعم
    # -----------------------------------------------------

    if data == "admin_support":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📱 واتساب",
                    callback_data="support_whatsapp"
                )
            ],
            [
                InlineKeyboardButton(
                    "📸 إنستجرام",
                    callback_data="support_instagram"
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
            "🤝 إعدادات الدعم\n\nاختر طريقة التواصل:",
            reply_markup=keyboard
        )

        return

    # -----------------------------------------------------
    # واتساب
    # -----------------------------------------------------

    if data == "support_whatsapp":
        context.user_data["action"] = "support_whatsapp"

        await query.edit_message_text(
            "📱 أرسل رقم الواتساب مع مفتاح الدولة.\n\n"
            "مثال:\n"
            "9677XXXXXXXX"
        )

        return

    # -----------------------------------------------------
    # إنستجرام
    # -----------------------------------------------------

    if data == "support_instagram":
        context.user_data["action"] = "support_instagram"

        await query.edit_message_text(
            "📸 أرسل يوزر الإنستجرام أو رابط حسابك.\n\n"
            "مثال:\n"
            "@username"
        )

        return

    # -----------------------------------------------------
    # تعطيل الدعم
    # -----------------------------------------------------

    if data == "support_disable":
        set_setting("support_value", "")

        await query.edit_message_text(
            "✅ تم تعطيل زر الدعم.",
            reply_markup=admin_menu()
        )

        return

    # -----------------------------------------------------
    # إدارة الأقسام
    # -----------------------------------------------------

    if data == "admin_categories":
        await categories_admin(query)
        return

    # -----------------------------------------------------
    # إضافة قسم
    # -----------------------------------------------------

    if data == "add_category":
        context.user_data["action"] = "add_category"

        await query.edit_message_text(
            "📂 أرسل اسم القسم الجديد:"
        )

        return

    # -----------------------------------------------------
    # حذف قسم
    # -----------------------------------------------------

    if data.startswith("delete_category_"):
        category_id = int(
            data.replace("delete_category_", "")
        )

        db.execute(
            "DELETE FROM contents WHERE category_id=?",
            (category_id,)
        )

        db.execute(
            "DELETE FROM categories WHERE id=?",
            (category_id,)
        )

        db.commit()

        await categories_admin(query)

        return

    # -----------------------------------------------------
    # إدارة المحتوى
    # -----------------------------------------------------

    if data == "admin_content":
        await content_admin(query)
        return

    # -----------------------------------------------------
    # إضافة محتوى
    # -----------------------------------------------------

    if data.startswith("add_content_"):
        category_id = int(
            data.replace("add_content_", "")
        )

        context.user_data["action"] = (
            f"add_content_{category_id}"
        )

        await query.edit_message_text(
            "📚 أرسل المحتوى الآن.\n\n"
            "إذا تريد عنوان:\n"
            "السطر الأول يكون العنوان\n"
            "والأسطر التي بعده تكون المحتوى.\n\n"
            "مثال:\n"
            "ثغرات فنش\n"
            "هنا تكتب الشرح كامل...\n\n"
            "وإذا ما تريد عنوان، أرسل المحتوى مباشرة."
        )

        return

    # -----------------------------------------------------
    # رجوع لوحة التحكم
    # -----------------------------------------------------

    if data == "admin_back":
        await query.edit_message_text(
            "🛠️ لوحة التحكم\n\n"
            f"👥 عدد مستخدمي البوت: {users_count()}",
            reply_markup=admin_menu()
        )

        return


# =========================================================
# إدارة الأقسام
# =========================================================

async def categories_admin(query):
    keyboard = []

    keyboard.append([
        InlineKeyboardButton(
            "➕ إضافة قسم",
            callback_data="add_category"
        )
    ])

    for category in get_categories():
        keyboard.append([
            InlineKeyboardButton(
                f"📂 {category['name']}",
                callback_data=f"add_content_{category['id']}"
            ),
            InlineKeyboardButton(
                "🗑️",
                callback_data=f"delete_category_{category['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data="admin_back"
        )
    ])

    await query.edit_message_text(
        "📂 إدارة الأقسام\n\n"
        "اضغط على اسم القسم لإضافة محتوى داخله.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# إدارة المحتوى
# =========================================================

async def content_admin(query):
    keyboard = []

    for category in get_categories():
        count = len(
            get_contents(category["id"])
        )

        keyboard.append([
            InlineKeyboardButton(
                f"📂 {category['name']} ({count})",
                callback_data=f"add_content_{category['id']}"
            )
        ])

    keyboard.append([
        InlineKeyboardButton(
            "🔙 رجوع",
            callback_data="admin_back"
        )
    ])

    await query.edit_message_text(
        "📚 إدارة المحتوى\n\n"
        "اختر القسم الذي تريد إضافة المحتوى إليه:",
        reply_markup=InlineKeyboardMarkup(keyboard)
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

    action = context.user_data.get("action")

    if not action:
        return

    text = update.message.text

    if not text:
        return

    # -----------------------------------------------------
    # رسالة الترحيب
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # الدعم واتساب
    # -----------------------------------------------------

    if action == "support_whatsapp":
        set_setting(
            "support_type",
            "whatsapp"
        )

        set_setting(
            "support_value",
            text.strip()
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ تم حفظ رقم الواتساب.\n\n"
            "سيظهر للمستخدمين زر الدعم.",
            reply_markup=admin_menu()
        )

        return

    # -----------------------------------------------------
    # الدعم إنستجرام
    # -----------------------------------------------------

    if action == "support_instagram":
        set_setting(
            "support_type",
            "instagram"
        )

        set_setting(
            "support_value",
            text.strip()
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ تم حفظ حساب الإنستجرام.",
            reply_markup=admin_menu()
        )

        return

    # -----------------------------------------------------
    # إضافة قسم
    # -----------------------------------------------------

    if action == "add_category":
        db.execute(
            "INSERT INTO categories(name) VALUES(?)",
            (text.strip(),)
        )

        db.commit()

        context.user_data.clear()

        await update.message.reply_text(
            "✅ تم إضافة القسم بنجاح.",
            reply_markup=admin_menu()
        )

        return

    # -----------------------------------------------------
    # إضافة محتوى
    # -----------------------------------------------------

    if action.startswith("add_content_"):
        category_id = int(
            action.replace("add_content_", "")
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

        db.execute("""
            INSERT INTO contents
            (category_id,title,body)
            VALUES(?,?,?)
        """, (
            category_id,
            title,
            body
        ))

        db.commit()

        context.user_data.clear()

        await update.message.reply_text(
            "✅ تم حفظ المحتوى.\n\n"
            "المستخدم سيظهر له المحتوى مباشرة عند ضغط القسم.",
            reply_markup=admin_menu()
        )

        return

    # -----------------------------------------------------
    # الإذاعة
    # -----------------------------------------------------

    if action == "broadcast":
        context.user_data.clear()

        users = get_users()

        sent = 0
        failed = 0

        await update.message.reply_text(
            f"📢 بدأت الإذاعة...\n\n"
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

            await asyncio.sleep(0.05)

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
            "BOT_TOKEN غير موجود في متغيرات البيئة."
        )

    if ADMIN_ID == 0:
        raise RuntimeError(
            "ADMIN_IDS غير موجود في متغيرات البيئة."
        )

    # التأكد من وجود مجلد البيانات
    os.makedirs("/data", exist_ok=True)

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

    print("BOT IS RUNNING...")

    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()