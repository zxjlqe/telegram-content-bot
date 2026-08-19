import os
import sqlite3
import logging
from html import escape

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputFile
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters, ConversationHandler
)

TOKEN = os.getenv("BOT_TOKEN", "PUT_BOT_TOKEN_HERE")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",") if x.strip().isdigit()}
DB = "bot.db"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

ADD_CAT, ADD_CONTENT, EDIT_CAT, BROADCAST = range(4)


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        parent_id INTEGER DEFAULT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS contents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        kind TEXT NOT NULL,
        value TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
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


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def save_user(update: Update):
    u = update.effective_user
    if not u:
        return
    con = db()
    con.execute(
        "INSERT OR REPLACE INTO users(user_id, first_name, username) VALUES(?,?,?)",
        (u.id, u.first_name or "", u.username or "")
    )
    con.commit()
    con.close()


def main_menu():
    con = db()
    cats = con.execute(
        "SELECT id,name FROM categories WHERE parent_id IS NULL ORDER BY id"
    ).fetchall()
    con.close()

    rows = []
    for i in range(0, len(cats), 2):
        row = []
        for c in cats[i:i+2]:
            row.append(InlineKeyboardButton(c["name"], callback_data=f"cat:{c['id']}"))
        rows.append(row)

    rows.append([InlineKeyboardButton("🔎 البحث", callback_data="search_info")])
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update)
    text = (
        "✨ <b>مرحبًا بك</b>\n\n"
        "اختر القسم الذي تريد تصفحه من القائمة بالأسفل 👇"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu())


async def categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def open_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cid = int(q.data.split(":")[1])

    con = db()
    cat = con.execute("SELECT * FROM categories WHERE id=?", (cid,)).fetchone()
    subs = con.execute(
        "SELECT id,name FROM categories WHERE parent_id=? ORDER BY id", (cid,)
    ).fetchall()
    contents = con.execute(
        "SELECT id,title FROM contents WHERE category_id=? ORDER BY id", (cid,)
    ).fetchall()
    con.close()

    if not cat:
        return

    rows = []
    for s in subs:
        rows.append([InlineKeyboardButton("📁 " + s["name"], callback_data=f"cat:{s['id']}")])
    for c in contents:
        rows.append([InlineKeyboardButton("📄 " + c["title"], callback_data=f"content:{c['id']}")])

    back = "main" if cat["parent_id"] is None else f"cat:{cat['parent_id']}"
    rows.append([InlineKeyboardButton("↩️ رجوع", callback_data=back)])

    await q.edit_message_text(
        f"📂 <b>{escape(cat['name'])}</b>\n\nاختر من القائمة:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows)
    )


async def open_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    cid = int(q.data.split(":")[1])

    con = db()
    item = con.execute("""
        SELECT c.*, cat.name AS cat_name
        FROM contents c JOIN categories cat ON cat.id=c.category_id
        WHERE c.id=?
    """, (cid,)).fetchone()
    con.close()

    if not item:
        return

    title = escape(item["title"])
    kind = item["kind"]
    value = item["value"]

    if kind == "text":
        await q.message.reply_text(f"📄 <b>{title}</b>\n\n{value}", parse_mode=ParseMode.HTML)
    elif kind == "document":
        await q.message.reply_document(document=value, caption=title)
    elif kind == "photo":
        await q.message.reply_photo(photo=value, caption=title)
    elif kind == "video":
        await q.message.reply_video(video=value, caption=title)
    elif kind == "audio":
        await q.message.reply_audio(audio=value, caption=title)
    elif kind == "link":
        await q.message.reply_text(f"🔗 <b>{title}</b>\n{escape(value)}", parse_mode=ParseMode.HTML)

    await q.message.reply_text(
        "تم فتح المحتوى.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("↩️ رجوع للقسم", callback_data=f"cat:{item['category_id']}")]
        ])
    )


async def search_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.message.reply_text(
        "🔎 البحث متاح في النسخة الأساسية كواجهة جاهزة.\n"
        "يمكن توسيعه ليبحث في أسماء الأقسام والملفات والمحتوى."
    )


# ---------------- ADMIN PANEL ----------------

def admin_menu():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ قسم جديد", callback_data="a:addcat"),
            InlineKeyboardButton("🗂️ إدارة الأقسام", callback_data="a:cats"),
        ],
        [
            InlineKeyboardButton("📤 إضافة محتوى", callback_data="a:addcontent"),
            InlineKeyboardButton("🗃️ إدارة المحتوى", callback_data="a:content"),
        ],
        [
            InlineKeyboardButton("📊 الإحصائيات", callback_data="a:stats"),
            InlineKeyboardButton("📢 إذاعة", callback_data="a:broadcast"),
        ],
        [
            InlineKeyboardButton("👥 المستخدمون", callback_data="a:users"),
        ],
    ])


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ هذا القسم للإدارة فقط.")
        return
    await update.message.reply_text("👑 <b>لوحة التحكم الرئيسية</b>", parse_mode=ParseMode.HTML, reply_markup=admin_menu())


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if not is_admin(q.from_user.id):
        await q.answer("غير مصرح لك.", show_alert=True)
        return

    action = q.data

    if action == "a:addcat":
        context.user_data.clear()
        context.user_data["state"] = "addcat"
        await q.message.reply_text(
            "➕ <b>إضافة قسم</b>\n\nأرسل اسم القسم فقط.\nمثال: 📱 واتساب",
            parse_mode=ParseMode.HTML
        )

    elif action == "a:cats":
        con = db()
        cats = con.execute("SELECT id,name,parent_id FROM categories ORDER BY id").fetchall()
        con.close()
        rows = [[InlineKeyboardButton(f"🗂️ {c['name']}", callback_data=f"ae:{c['id']}")] for c in cats]
        rows.append([InlineKeyboardButton("↩️ لوحة التحكم", callback_data="a:home")])
        await q.message.reply_text("🗂️ <b>إدارة الأقسام</b>", parse_mode=ParseMode.HTML,
                                   reply_markup=InlineKeyboardMarkup(rows))

    elif action == "a:addcontent":
        con = db()
        cats = con.execute("SELECT id,name FROM categories ORDER BY id").fetchall()
        con.close()
        rows = [[InlineKeyboardButton(c["name"], callback_data=f"acat:{c['id']}")] for c in cats]
        await q.message.reply_text("📤 اختر القسم الذي سيُحفظ فيه المحتوى:",
                                   reply_markup=InlineKeyboardMarkup(rows))

    elif action == "a:content":
        con = db()
        items = con.execute("""
            SELECT contents.id, contents.title, categories.name cat
            FROM contents JOIN categories ON categories.id=contents.category_id
            ORDER BY contents.id DESC LIMIT 50
        """).fetchall()
        con.close()
        rows = [[InlineKeyboardButton(
            f"📄 {x['title']} — {x['cat']}", callback_data=f"delc:{x['id']}"
        )] for x in items]
        rows.append([InlineKeyboardButton("↩️ لوحة التحكم", callback_data="a:home")])
        await q.message.reply_text("🗃️ اضغط على محتوى لحذفه:",
                                   reply_markup=InlineKeyboardMarkup(rows))

    elif action == "a:stats":
        con = db()
        users = con.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
        cats = con.execute("SELECT COUNT(*) n FROM categories").fetchone()["n"]
        items = con.execute("SELECT COUNT(*) n FROM contents").fetchone()["n"]
        con.close()
        await q.message.reply_text(
            f"📊 <b>إحصائيات البوت</b>\n\n"
            f"👥 المستخدمون: <b>{users}</b>\n"
            f"📁 الأقسام: <b>{cats}</b>\n"
            f"📄 المحتويات: <b>{items}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_menu()
        )

    elif action == "a:users":
        con = db()
        rows = con.execute("SELECT user_id,first_name,username FROM users ORDER BY joined_at DESC LIMIT 30").fetchall()
        con.close()
        text = "👥 <b>آخر المستخدمين</b>\n\n"
        for x in rows:
            uname = f"@{x['username']}" if x["username"] else "بدون معرف"
            text += f"• {escape(x['first_name'])} — {uname} — <code>{x['user_id']}</code>\n"
        await q.message.reply_text(text or "لا يوجد مستخدمون.", parse_mode=ParseMode.HTML)

    elif action == "a:broadcast":
        context.user_data["state"] = "broadcast"
        await q.message.reply_text("📢 أرسل الآن الرسالة التي تريد إرسالها لكل المستخدمين.")

    elif action == "a:home":
        await q.message.reply_text("👑 <b>لوحة التحكم</b>", parse_mode=ParseMode.HTML, reply_markup=admin_menu())

    elif action.startswith("ae:"):
        cid = int(action.split(":")[1])
        con = db()
        c = con.execute("SELECT * FROM categories WHERE id=?", (cid,)).fetchone()
        con.close()
        if c:
            await q.message.reply_text(
                f"🗂️ <b>{escape(c['name'])}</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ إعادة تسمية", callback_data=f"rename:{cid}")],
                    [InlineKeyboardButton("🗑️ حذف القسم", callback_data=f"delcat:{cid}")],
                ])
            )

    elif action.startswith("rename:"):
        cid = int(action.split(":")[1])
        context.user_data["state"] = "rename"
        context.user_data["cid"] = cid
        await q.message.reply_text("✏️ أرسل الاسم الجديد للقسم.")

    elif action.startswith("delcat:"):
        cid = int(action.split(":")[1])
        con = db()
        con.execute("DELETE FROM contents WHERE category_id=?", (cid,))
        con.execute("DELETE FROM categories WHERE id=?", (cid,))
        con.commit()
        con.close()
        await q.message.reply_text("✅ تم حذف القسم ومحتواه.")

    elif action.startswith("acat:"):
        cid = int(action.split(":")[1])
        context.user_data["state"] = "addcontent"
        context.user_data["cid"] = cid
        await q.message.reply_text(
            "📤 أرسل المحتوى الآن.\n\n"
            "يدعم: ملف 📎 / صورة 🖼️ / فيديو 🎬 / صوت 🎵 / نص 📝 / رابط 🔗\n"
            "وسيتم حفظه في القسم المختار."
        )

    elif action.startswith("delc:"):
        iid = int(action.split(":")[1])
        con = db()
        con.execute("DELETE FROM contents WHERE id=?", (iid,))
        con.commit()
        con.close()
        await q.message.reply_text("🗑️ تم حذف المحتوى.")


async def admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    state = context.user_data.get("state")

    if state == "addcat":
        name = update.message.text.strip()
        con = db()
        con.execute("INSERT INTO categories(name) VALUES(?)", (name,))
        con.commit()
        con.close()
        context.user_data.clear()
        await update.message.reply_text("✅ تم إنشاء القسم.", reply_markup=admin_menu())

    elif state == "rename":
        cid = context.user_data["cid"]
        con = db()
        con.execute("UPDATE categories SET name=? WHERE id=?", (update.message.text.strip(), cid))
        con.commit()
        con.close()
        context.user_data.clear()
        await update.message.reply_text("✅ تم تغيير الاسم.", reply_markup=admin_menu())

    elif state == "broadcast":
        con = db()
        users = [r["user_id"] for r in con.execute("SELECT user_id FROM users").fetchall()]
        con.close()
        sent = 0
        for uid in users:
            try:
                await context.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id
                )
                sent += 1
            except Exception:
                pass
        context.user_data.clear()
        await update.message.reply_text(f"📢 انتهت الإذاعة.\nتم الإرسال إلى {sent} مستخدم.", reply_markup=admin_menu())

    elif state == "addcontent":
        cid = context.user_data["cid"]
        msg = update.message
        kind = None
        value = None
        title = "محتوى جديد"

        if msg.document:
            kind, value, title = "document", msg.document.file_id, msg.document.file_name or title
        elif msg.photo:
            kind, value = "photo", msg.photo[-1].file_id
            title = msg.caption or title
        elif msg.video:
            kind, value = "video", msg.video.file_id, msg.caption or title
        elif msg.audio:
            kind, value = "audio", msg.audio.file_id, msg.caption or title
        elif msg.text:
            kind, value = "text", msg.text, "نص"
        else:
            await msg.reply_text("⚠️ نوع المحتوى هذا غير مدعوم حاليًا.")
            return

        con = db()
        con.execute(
            "INSERT INTO contents(category_id,title,kind,value) VALUES(?,?,?,?)",
            (cid, title, kind, value)
        )
        con.commit()
        con.close()
        context.user_data.clear()
        await msg.reply_text("✅ تم حفظ المحتوى داخل القسم.", reply_markup=admin_menu())


async def button_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.data.startswith("cat:"):
        return await open_category(update, context)
    if q.data.startswith("content:"):
        return await open_content(update, context)
    if q.data == "main":
        await q.answer()
        await q.edit_message_text("🏠 <b>القائمة الرئيسية</b>", parse_mode=ParseMode.HTML, reply_markup=main_menu())
        return
    if q.data == "search_info":
        return await search_info(update, context)
    if q.data.startswith(("a:", "ae:", "rename:", "delcat:", "acat:", "delc:")):
        return await admin_callback(update, context)


def main():
    if TOKEN == "PUT_BOT_TOKEN_HERE":
        raise SystemExit("ضع BOT_TOKEN في متغير البيئة قبل التشغيل.")
    init_db()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(button_router))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, admin_text))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
