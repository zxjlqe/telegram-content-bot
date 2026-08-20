import os
import sqlite3
import logging
from html import escape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("BOT_TOKEN", "PUT_BOT_TOKEN_HERE")
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

DB = "bot.db"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


# =========================
# DATABASE
# =========================

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def init_db():
    con = db()

    con.executescript("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        parent_id INTEGER DEFAULT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(parent_id)
            REFERENCES categories(id)
            ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS contents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        kind TEXT NOT NULL,
        value TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(category_id)
            REFERENCES categories(id)
            ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        username TEXT,
        joined_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    """)

    con.commit()
    con.close()


def is_admin(user_id):
    return user_id in ADMIN_IDS


def save_user(update):
    user = update.effective_user

    if not user:
        return

    con = db()

    con.execute("""
        INSERT INTO users(user_id, first_name, username)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            first_name=excluded.first_name,
            username=excluded.username
    """, (
        user.id,
        user.first_name or "",
        user.username or ""
    ))

    con.commit()
    con.close()


# =========================
# USER INTERFACE
# =========================

def welcome_text():

    return (
        "🌑 <b>الظل الرقمي | SHADOW DIGITAL</b>\n\n"
        "مرحباً بك 🖤\n\n"
        "أهلاً بك في البوت.\n"
        "تصفح الأقسام واختر المحتوى الذي تريده بسهولة وسرعة.\n\n"
        "📚 الأقسام\n"
        "📂 الملفات والمحتوى\n"
        "🔎 البحث\n"
        "💬 الدعم\n"
        "ℹ️ معلومات البوت\n\n"
        "👇 <b>اختر القسم الذي تريد تصفحه:</b>"
    )


def main_menu():

    con = db()

    categories = con.execute("""
        SELECT id, name
        FROM categories
        WHERE parent_id IS NULL
        ORDER BY id
    """).fetchall()

    con.close()

    rows = []

    # 3 أزرار في الصف
    for i in range(0, len(categories), 3):

        row = []

        for category in categories[i:i + 3]:

            row.append(
                InlineKeyboardButton(
                    category["name"],
                    callback_data=f"cat:{category['id']}"
                )
            )

        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            "🔎 البحث",
            callback_data="search"
        ),
        InlineKeyboardButton(
            "💬 الدعم",
            callback_data="support"
        ),
        InlineKeyboardButton(
            "ℹ️ عن البوت",
            callback_data="about"
        )
    ])

    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    save_user(update)

    if not update.message:
        return

    await update.message.reply_text(
        welcome_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu()
    )


# =========================
# CATEGORIES
# =========================

async def open_category(update, context):

    query = update.callback_query

    await query.answer()

    try:
        category_id = int(
            query.data.split(":")[1]
        )
    except Exception:
        return

    con = db()

    category = con.execute("""
        SELECT id, name, parent_id
        FROM categories
        WHERE id=?
    """, (category_id,)).fetchone()

    if not category:
        con.close()
        return

    subcategories = con.execute("""
        SELECT id, name
        FROM categories
        WHERE parent_id=?
        ORDER BY id
    """, (category_id,)).fetchall()

    contents = con.execute("""
        SELECT id, title
        FROM contents
        WHERE category_id=?
        ORDER BY id
    """, (category_id,)).fetchall()

    con.close()

    buttons = []

    # الأقسام الفرعية
    for sub in subcategories:

        buttons.append(
            InlineKeyboardButton(
                "📁 " + sub["name"],
                callback_data=f"cat:{sub['id']}"
            )
        )

    # المحتوى
    for content in contents:

        buttons.append(
            InlineKeyboardButton(
                "📄 " + content["title"],
                callback_data=f"content:{content['id']}"
            )
        )

    rows = []

    # زرين في الصف
    for i in range(0, len(buttons), 2):

        rows.append(
            buttons[i:i + 2]
        )

    if category["parent_id"] is None:

        back = "main"

    else:

        back = f"cat:{category['parent_id']}"

    rows.append([
        InlineKeyboardButton(
            "↩️ رجوع",
            callback_data=back
        )
    ])

    if not buttons:

        text = (
            f"📂 <b>{escape(category['name'])}</b>\n\n"
            "لا يوجد محتوى داخل هذا القسم حالياً."
        )

    else:

        text = (
            f"📂 <b>{escape(category['name'])}</b>\n\n"
            "اختر من القائمة:"
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows)
    )


# =========================
# CONTENT
# =========================

async def open_content(update, context):

    query = update.callback_query

    await query.answer()

    try:

        content_id = int(
            query.data.split(":")[1]
        )

    except Exception:

        return

    con = db()

    item = con.execute("""
        SELECT
            c.*,
            cat.name AS category_name
        FROM contents c
        JOIN categories cat
            ON cat.id = c.category_id
        WHERE c.id=?
    """, (content_id,)).fetchone()

    con.close()

    if not item:

        await query.answer(
            "المحتوى غير موجود.",
            show_alert=True
        )

        return

    title = escape(item["title"])
    kind = item["kind"]
    value = item["value"]

    try:

        if kind == "text":

            await query.message.reply_text(
                f"📄 <b>{title}</b>\n\n"
                f"{escape(value)}",
                parse_mode=ParseMode.HTML
            )

        elif kind == "document":

            await query.message.reply_document(
                document=value,
                caption=title,
                parse_mode=ParseMode.HTML
            )

        elif kind == "photo":

            await query.message.reply_photo(
                photo=value,
                caption=title,
                parse_mode=ParseMode.HTML
            )

        elif kind == "video":

            await query.message.reply_video(
                video=value,
                caption=title,
                parse_mode=ParseMode.HTML
            )

        elif kind == "audio":

            await query.message.reply_audio(
                audio=value,
                caption=title,
                parse_mode=ParseMode.HTML
            )

        elif kind == "link":

            await query.message.reply_text(
                f"🔗 <b>{title}</b>\n\n"
                f"{escape(value)}",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False
            )

        else:

            await query.message.reply_text(
                escape(value),
                parse_mode=ParseMode.HTML
            )

        await query.message.reply_text(
            "اختر ماذا تريد:",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "↩️ رجوع للقسم",
                        callback_data=
                        f"cat:{item['category_id']}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏠 الرئيسية",
                        callback_data="main"
                    )
                ]
            ])
        )

    except Exception:

        log.exception(
            "Error opening content"
        )

        await query.message.reply_text(
            "⚠️ تعذر فتح المحتوى حالياً."
        )


# =========================
# SEARCH
# =========================

async def search_start(update, context):

    query = update.callback_query

    await query.answer()

    context.user_data.clear()
    context.user_data["state"] = "search"

    await query.message.reply_text(
        "🔎 <b>البحث</b>\n\n"
        "أرسل اسم القسم أو اسم المحتوى الذي تريد البحث عنه.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ إلغاء",
                    callback_data="cancel"
                )
            ]
        ])
    )


async def search_text(update, context):

    if not update.message.text:
        return

    text = update.message.text.strip()

    if not text:
        return

    like = f"%{text}%"

    con = db()

    categories = con.execute("""
        SELECT id, name
        FROM categories
        WHERE name LIKE ?
        ORDER BY id
        LIMIT 30
    """, (like,)).fetchall()

    contents = con.execute("""
        SELECT
            c.id,
            c.title,
            c.category_id
        FROM contents c
        WHERE c.title LIKE ?
           OR c.value LIKE ?
        ORDER BY c.id DESC
        LIMIT 30
    """, (like, like)).fetchall()

    con.close()

    rows = []

    for category in categories:

        rows.append([
            InlineKeyboardButton(
                "📁 " + category["name"],
                callback_data=f"cat:{category['id']}"
            )
        ])

    for content in contents:

        rows.append([
            InlineKeyboardButton(
                "📄 " + content["title"],
                callback_data=f"content:{content['id']}"
            )
        ])

    rows.append([
        InlineKeyboardButton(
            "🏠 الرئيسية",
            callback_data="main"
        )
    ])

    context.user_data.clear()

    if not categories and not contents:

        result_text = (
            f"🔎 لا توجد نتائج لـ:\n\n"
            f"<b>{escape(text)}</b>"
        )

    else:

        result_text = (
            f"🔎 نتائج البحث عن:\n\n"
            f"<b>{escape(text)}</b>\n\n"
            "اختر النتيجة:"
        )

    await update.message.reply_text(
        result_text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows)
    )


# =========================
# SUPPORT
# =========================

async def support_info(update, context):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(
        "💬 <b>الدعم</b>\n\n"
        "إذا واجهتك مشكلة أو عندك اقتراح، "
        "تواصل معنا عبر الزر بالأسفل.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💚 التواصل عبر واتساب",
                    url="https://wa.me/967734647071"
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ القائمة الرئيسية",
                    callback_data="main"
                )
            ]
        ])
    )


# =========================
# ABOUT
# =========================

async def about_info(update, context):

    query = update.callback_query

    await query.answer()

    await query.edit_message_text(
        "🌑 <b>الظل الرقمي | SHADOW DIGITAL</b>\n\n"
        "بوت لتنظيم المحتوى والأقسام "
        "والملفات والمصادر بطريقة سهلة وسريعة.\n\n"
        "⚡ بسيط\n"
        "🚀 سريع\n"
        "📂 منظم",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "↩️ القائمة الرئيسية",
                    callback_data="main"
                )
            ]
        ])
    )


# =========================
# ADMIN PANEL
# =========================

def admin_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "➕ قسم جديد",
                callback_data="a:addcat"
            ),
            InlineKeyboardButton(
                "🗂️ إدارة الأقسام",
                callback_data="a:cats"
            )
        ],

        [
            InlineKeyboardButton(
                "📤 إضافة محتوى",
                callback_data="a:addcontent"
            ),
            InlineKeyboardButton(
                "🗃️ إدارة المحتوى",
                callback_data="a:content"
            )
        ],

        [
            InlineKeyboardButton(
                "📊 الإحصائيات",
                callback_data="a:stats"
            ),
            InlineKeyboardButton(
                "📢 إذاعة",
                callback_data="a:broadcast"
            )
        ],

        [
            InlineKeyboardButton(
                "👥 المستخدمون",
                callback_data="a:users"
            )
        ]

    ])


async def admin(update, context):

    if not update.effective_user:

        return

    if not is_admin(
        update.effective_user.id
    ):

        await update.message.reply_text(
            "⛔ هذا القسم للإدارة فقط."
        )

        return

    context.user_data.clear()

    await update.message.reply_text(
        "👑 <b>لوحة التحكم الرئيسية</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_menu()
    )


# =========================
# ADMIN CALLBACKS
# =========================

async def admin_callback(update, context):

    query = update.callback_query

    if not is_admin(
        query.from_user.id
    ):

        await query.answer(
            "غير مصرح لك.",
            show_alert=True
        )

        return

    await query.answer()

    action = query.data

    # إضافة قسم
    if action == "a:addcat":

        context.user_data.clear()
        context.user_data["state"] = "addcat"

        await query.message.reply_text(
            "➕ <b>إضافة قسم</b>\n\n"
            "أرسل اسم القسم فقط.\n\n"
            "مثال:\n"
            "📱 واتساب",
            parse_mode=ParseMode.HTML
        )

    # إدارة الأقسام
    elif action == "a:cats":

        con = db()

        categories = con.execute("""
            SELECT
                c.id,
                c.name,
                c.parent_id
            FROM categories c
            ORDER BY c.id
        """).fetchall()

        con.close()

        rows = []

        for category in categories:

            icon = (
                "📁"
                if category["parent_id"]
                else "🗂️"
            )

            rows.append([
                InlineKeyboardButton(
                    f"{icon} {category['name']}",
                    callback_data=
                    f"editcat:{category['id']}"
                )
            ])

        rows.append([
            InlineKeyboardButton(
                "↩️ لوحة التحكم",
                callback_data="a:home"
            )
        ])

        await query.message.reply_text(
            "🗂️ <b>إدارة الأقسام</b>\n\n"
            "اختر القسم:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows)
        )

    # إضافة محتوى
    elif action == "a:addcontent":

        con = db()

        categories = con.execute("""
            SELECT id, name
            FROM categories
            ORDER BY id
        """).fetchall()

        con.close()

        if not categories:

            await query.message.reply_text(
                "⚠️ لا توجد أقسام حالياً.\n"
                "أنشئ قسمًا أولاً."
            )

            return

        rows = []

        for category in categories:

            rows.append([
                InlineKeyboardButton(
                    category["name"],
                    callback_data=
                    f"choosecat:{category['id']}"
                )
            ])

        rows.append([
            InlineKeyboardButton(
                "↩️ لوحة التحكم",
                callback_data="a:home"
            )
        ])

        await query.message.reply_text(
            "📤 اختر القسم الذي سيُحفظ فيه المحتوى:",
            reply_markup=InlineKeyboardMarkup(rows)
        )

    # إدارة المحتوى
    elif action == "a:content":

        con = db()

        contents = con.execute("""
            SELECT
                contents.id,
                contents.title,
                categories.name AS category_name
            FROM contents
            JOIN categories
                ON categories.id =
                   contents.category_id
            ORDER BY contents.id DESC
            LIMIT 100
        """).fetchall()

        con.close()

        rows = []

        for content in contents:

            rows.append([
                InlineKeyboardButton(
                    f"📄 {content['title']} — "
                    f"{content['category_name']}",
                    callback_data=
                    f"deletecontent:{content['id']}"
                )
            ])

        rows.append([
            InlineKeyboardButton(
                "↩️ لوحة التحكم",
                callback_data="a:home"
            )
        ])

        await query.message.reply_text(
            "🗃️ <b>إدارة المحتوى</b>\n\n"
            "اضغط على المحتوى لحذفه:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows)
        )

    # الإحصائيات
    elif action == "a:stats":

        con = db()

        users = con.execute(
            "SELECT COUNT(*) n FROM users"
        ).fetchone()["n"]

        categories = con.execute(
            "SELECT COUNT(*) n FROM categories"
        ).fetchone()["n"]

        contents = con.execute(
            "SELECT COUNT(*) n FROM contents"
        ).fetchone()["n"]

        con.close()

        await query.message.reply_text(
            "📊 <b>إحصائيات البوت</b>\n\n"
            f"👥 المستخدمون: <b>{users}</b>\n"
            f"📁 الأقسام: <b>{categories}</b>\n"
            f"📄 المحتوى: <b>{contents}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu()
        )

    # المستخدمون
    elif action == "a:users":

        con = db()

        users = con.execute("""
            SELECT
                user_id,
                first_name,
                username
            FROM users
            ORDER BY joined_at DESC
            LIMIT 50
        """).fetchall()

        con.close()

        if not users:

            await query.message.reply_text(
                "👥 لا يوجد مستخدمون حتى الآن.",
                reply_markup=admin_menu()
            )

            return

        text = "👥 <b>المستخدمون</b>\n\n"

        for user in users:

            username = (
                f"@{escape(user['username'])}"
                if user["username"]
                else "بدون معرف"
            )

            text += (
                f"• {escape(user['first_name'])}\n"
                f"  {username}\n"
                f"  <code>{user['user_id']}</code>\n\n"
            )

        await query.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu()
        )

    # إذاعة
    elif action == "a:broadcast":

        context.user_data.clear()
        context.user_data["state"] = "broadcast"

        await query.message.reply_text(
            "📢 أرسل الآن الرسالة أو الملف أو الصورة "
            "أو الفيديو الذي تريد إرساله للمستخدمين."
        )

    # الرئيسية
    elif action == "a:home":

        context.user_data.clear()

        await query.message.reply_text(
            "👑 <b>لوحة التحكم</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu()
        )

    # تعديل قسم
    elif action.startswith("editcat:"):

        category_id = int(
            action.split(":")[1]
        )

        con = db()

        category = con.execute("""
            SELECT id, name
            FROM categories
            WHERE id=?
        """, (category_id,)).fetchone()

        con.close()

        if not category:
            return

        await query.message.reply_text(
            f"🗂️ <b>{escape(category['name'])}</b>\n\n"
            "اختر العملية:",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([

                [
                    InlineKeyboardButton(
                        "✏️ إعادة تسمية",
                        callback_data=
                        f"rename:{category_id}"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "➕ قسم فرعي",
                        callback_data=
                        f"subcat:{category_id}"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "🗑️ حذف القسم",
                        callback_data=
                        f"deletecat:{category_id}"
                    )
                ],

                [
                    InlineKeyboardButton(
                        "↩️ الأقسام",
                        callback_data="a:cats"
                    )
                ]

            ])
        )

    # قسم فرعي
    elif action.startswith("subcat:"):

        parent_id = int(
            action.split(":")[1]
        )

        context.user_data.clear()

        context.user_data["state"] = "addsubcat"
        context.user_data["parent_id"] = parent_id

        await query.message.reply_text(
            "➕ <b>إضافة قسم فرعي</b>\n\n"
            "أرسل اسم القسم الفرعي.",
            parse_mode=ParseMode.HTML
        )

    # إعادة تسمية
    elif action.startswith("rename:"):

        category_id = int(
            action.split(":")[1]
        )

        context.user_data.clear()

        context.user_data["state"] = "rename"
        context.user_data["category_id"] = category_id

        await query.message.reply_text(
            "✏️ أرسل الاسم الجديد للقسم."
        )

    # حذف القسم
    elif action.startswith("deletecat:"):

        category_id = int(
            action.split(":")[1]
        )

        con = db()

        category = con.execute("""
            SELECT name
            FROM categories
            WHERE id=?
        """, (category_id,)).fetchone()

        con.close()

        if not category:
            return

        await query.message.reply_text(
            f"⚠️ هل تريد حذف القسم:\n\n"
            f"<b>{escape(category['name'])}</b>\n\n"
            "سيتم حذف المحتوى الموجود داخله أيضاً.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🗑️ نعم، احذف",
                        callback_data=
                        f"confirmcat:{category_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ إلغاء",
                        callback_data="a:cats"
                    )
                ]
            ])
        )

    # تأكيد حذف القسم
    elif action.startswith("confirmcat:"):

        category_id = int(
            action.split(":")[1]
        )

        con = db()

        con.execute(
            "DELETE FROM categories WHERE id=?",
            (category_id,)
        )

        con.commit()
        con.close()

        await query.message.reply_text(
            "✅ تم حذف القسم ومحتواه.",
            reply_markup=admin_menu()
        )

    # اختيار قسم للمحتوى
    elif action.startswith("choosecat:"):

        category_id = int(
            action.split(":")[1]
        )

        context.user_data.clear()

        context.user_data["state"] = "addcontent"
        context.user_data["category_id"] = category_id

        await query.message.reply_text(
            "📤 <b>إضافة محتوى</b>\n\n"
            "أرسل الآن المحتوى الذي تريد حفظه.\n\n"
            "يدعم:\n"
            "📎 الملفات\n"
            "🖼️ الصور\n"
            "🎬 الفيديو\n"
            "🎵 الصوت\n"
            "📝 النصوص\n"
            "🔗 الروابط\n\n"
            "يمكنك كتابة العنوان في Caption "
            "للملفات والصور والفيديو والصوت.",
            parse_mode=ParseMode.HTML
        )

    # حذف محتوى
    elif action.startswith("deletecontent:"):

        content_id = int(
            action.split(":")[1]
        )

        con = db()

        content = con.execute("""
            SELECT title
            FROM contents
            WHERE id=?
        """, (content_id,)).fetchone()

        con.close()

        if not content:
            return

        await query.message.reply_text(
            f"⚠️ هل تريد حذف:\n\n"
            f"📄 <b>{escape(content['title'])}</b>؟",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🗑️ نعم، احذف",
                        callback_data=
                        f"confirmcontent:{content_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ إلغاء",
                        callback_data="a:content"
                    )
                ]
            ])
        )

    # تأكيد حذف المحتوى
    elif action.startswith("confirmcontent:"):

        content_id = int(
            action.split(":")[1]
        )

        con = db()

        con.execute(
            "DELETE FROM contents WHERE id=?",
            (content_id,)
        )

        con.commit()
        con.close()

        await query.message.reply_text(
            "🗑️ تم حذف المحتوى.",
            reply_markup=admin_menu()
        )


# =========================
# ADMIN MESSAGES
# =========================

async def admin_messages(update, context):

    if not update.effective_user:
        return

    if not is_admin(
        update.effective_user.id
    ):
        return

    state = context.user_data.get("state")

    message = update.message

    # إضافة قسم
    if state == "addcat":

        if not message.text:
            await message.reply_text(
                "⚠️ أرسل اسم القسم كنص."
            )
            return

        name = message.text.strip()

        if not name:
            return

        con = db()

        con.execute("""
            INSERT INTO categories(name, parent_id)
            VALUES (?, NULL)
        """, (name,))

        con.commit()
        con.close()

        context.user_data.clear()

        await message.reply_text(
            f"✅ تم إنشاء القسم:\n\n"
            f"<b>{escape(name)}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu()
        )

    # إضافة قسم فرعي
    elif state == "addsubcat":

        if not message.text:
            await message.reply_text(
                "⚠️ أرسل اسم القسم كنص."
            )
            return

        name = message.text.strip()
        parent_id = context.user_data.get(
            "parent_id"
        )

        if not name or not parent_id:
            context.user_data.clear()
            return

        con = db()

        con.execute("""
            INSERT INTO categories(name, parent_id)
            VALUES (?, ?)
        """, (name, parent_id))

        con.commit()
        con.close()

        context.user_data.clear()

        await message.reply_text(
            f"✅ تم إنشاء القسم الفرعي:\n\n"
            f"<b>{escape(name)}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu()
        )

    # إعادة تسمية
    elif state == "rename":

        if not message.text:
            await message.reply_text(
                "⚠️ أرسل الاسم الجديد."
            )
            return

        name = message.text.strip()

        category_id = context.user_data.get(
            "category_id"
        )

        if not name or not category_id:
            context.user_data.clear()
            return

        con = db()

        con.execute("""
            UPDATE categories
            SET name=?
            WHERE id=?
        """, (name, category_id))

        con.commit()
        con.close()

        context.user_data.clear()

        await message.reply_text(
            "✅ تم تغيير اسم القسم.",
            reply_markup=admin_menu()
        )

    # إضافة محتوى
    elif state == "addcontent":

        category_id = context.user_data.get(
            "category_id"
        )

        if not category_id:

            context.user_data.clear()

            await message.reply_text(
                "⚠️ انتهت جلسة الإضافة."
            )

            return

        kind = None
        value = None
        title = "محتوى جديد"

        if message.document:

            kind = "document"
            value = message.document.file_id

            title = (
                message.caption.strip()
                if message.caption
                else
                message.document.file_name
                or "ملف"
            )

        elif message.photo:

            kind = "photo"
            value = message.photo[-1].file_id

            title = (
                message.caption.strip()
                if message.caption
                else "صورة"
            )

        elif message.video:

            kind = "video"
            value = message.video.file_id

            title = (
                message.caption.strip()
                if message.caption
                else "فيديو"
            )

        elif message.audio:

            kind = "audio"
            value = message.audio.file_id

            title = (
                message.caption.strip()
                if message.caption
                else "صوت"
            )

        elif message.text:

            value = message.text.strip()

            if value.startswith(
                ("http://", "https://", "www.")
            ):

                kind = "link"
                title = "رابط"

            else:

                kind = "text"
                title = "نص"

        else:

            await message.reply_text(
                "⚠️ نوع المحتوى هذا غير مدعوم حالياً."
            )

            return

        con = db()

        con.execute("""
            INSERT INTO contents(
                category_id,
                title,
                kind,
                value
            )
            VALUES (?, ?, ?, ?)
        """, (
            category_id,
            title,
            kind,
            value
        ))

        con.commit()
        con.close()

        context.user_data.clear()

        await message.reply_text(
            "✅ <b>تم حفظ المحتوى بنجاح.</b>\n\n"
            "تقدر تضيف محتوى آخر من لوحة التحكم.",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu()
        )

    # البحث
    elif state == "search":

        await search_text(
            update,
            context
        )

    # الإذاعة
    elif state == "broadcast":

        con = db()

        users = [
            row["user_id"]
            for row in con.execute(
                "SELECT user_id FROM users"
            ).fetchall()
        ]

        con.close()

        sent = 0
        failed = 0

        for user_id in users:

            try:

                await context.bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=message.chat_id,
                    message_id=message.message_id
                )

                sent += 1

            except Exception:

                failed += 1

        context.user_data.clear()

        await message.reply_text(
            f"📢 <b>انتهت الإذاعة</b>\n\n"
            f"✅ تم الإرسال: {sent}\n"
            f"⚠️ فشل الإرسال: {failed}",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu()
        )


# =========================
# BUTTON ROUTER
# =========================

async def button_router(update, context):

    query = update.callback_query

    data = query.data or ""

    if data.startswith("cat:"):

        return await open_category(
            update,
            context
        )

    if data.startswith("content:"):

        return await open_content(
            update,
            context
        )

    if data == "main":

        await query.answer()

        context.user_data.clear()

        await query.edit_message_text(
            welcome_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu()
        )

        return

    if data == "search":

        return await search_start(
            update,
            context
        )

    if data == "cancel":

        await query.answer()

        context.user_data.clear()

        await query.edit_message_text(
            welcome_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu()
        )

        return

    if data == "support":

        return await support_info(
            update,
            context
        )

    if data == "about":

        return await about_info(
            update,
            context
        )

    if data.startswith((
        "a:",
        "editcat:",
        "subcat:",
        "rename:",
        "deletecat:",
        "confirmcat:",
        "choosecat:",
        "deletecontent:",
        "confirmcontent:"
    )):

        return await admin_callback(
            update,
            context
        )


# =========================
# ERROR HANDLER
# =========================

async def error_handler(update, context):

    log.exception(
        "Unhandled exception",
        exc_info=context.error
    )


# =========================
# MAIN
# =========================

def main():

    if TOKEN == "PUT_BOT_TOKEN_HERE":

        raise SystemExit(
            "ضع BOT_TOKEN في متغير البيئة قبل التشغيل."
        )

    if not ADMIN_IDS:

        raise SystemExit(
            "ضع ADMIN_IDS في متغير البيئة."
        )

    init_db()

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

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
            button_router
        )
    )

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            admin_messages
        )
    )

    app.add_error_handler(
        error_handler
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()