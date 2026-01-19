import logging
import sqlite3
import random
import string
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================== LOGGING ==================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== CONFIG ==================
TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN"
ADMIN_ID = 5443203423  # Change this to your ID

# ================== DATABASE ==================
conn = sqlite3.connect("files.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS files (
    code TEXT PRIMARY KEY,
    file_id TEXT,
    file_type TEXT,
    user_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    is_premium INTEGER DEFAULT 0,
    expiry_date TIMESTAMP
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
)
""")
conn.commit()

# Ensure schema is up to date
def update_schema():
    try:
        cur.execute("ALTER TABLE files ADD COLUMN file_type TEXT")
        conn.commit()
    except sqlite3.OperationalError: pass
    try:
        cur.execute("ALTER TABLE files ADD COLUMN user_id INTEGER")
        conn.commit()
    except sqlite3.OperationalError: pass
    try:
        cur.execute("ALTER TABLE files ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        conn.commit()
    except sqlite3.OperationalError: pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN expiry_date TIMESTAMP")
        conn.commit()
    except sqlite3.OperationalError: pass

update_schema()

# ================== UTIL ==================
def get_setting(key, default):
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    return row[0] if row else default

def set_setting(key, value):
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()

def is_premium(user_id):
    cur.execute("SELECT is_premium, expiry_date FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row or row[0] == 0:
        return False
    if row[1]:
        try:
            expiry = datetime.fromisoformat(row[1])
            if datetime.now() > expiry:
                cur.execute("UPDATE users SET is_premium = 0 WHERE user_id = ?", (user_id,))
                conn.commit()
                return False
        except ValueError:
            return False
    return True

def get_credits_used(user_id):
    # This function counts how many files the user has uploaded today.
    # Since we check against date(created_at) = date('now'), 
    # it naturally resets every day at 12:00 AM (UTC).
    cur.execute("""
        SELECT COUNT(*) FROM files 
        WHERE user_id = ? AND date(created_at) = date('now')
    """, (user_id,))
    return cur.fetchone()[0]

def generate_code(length=8):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))

# ================== COMMANDS ==================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 **How to use this Bot**\n"
        "1. Send any file (photo, video, audio, or document) to the bot.\n"
        "2. The bot will generate a unique shareable link for you.\n"
        "3. Share that link with anyone! When they click it and start the bot, they get the file.\n\n"
        "🛠 **Commands:**\n"
        "/start - Start the bot & check status\n"
        "/help - Show this help message\n"
        "/status - Check your plan and remaining credits\n"
        "/plan - View premium subscription plans\n"
        "/myid - Get your Telegram User ID"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text(
            "⚙️ **Admin Settings**\n"
            "Usage:\n"
            "`/settings credits [number]` - Set daily free credits\n"
            "`/settings upi [id]` - Change UPI ID\n"
            "`/settings username [name]` - Change Admin Username",
            parse_mode='Markdown'
        )
        return
    
    cmd = context.args[0].lower()
    val = " ".join(context.args[1:])
    if cmd == "credits":
        set_setting("free_credits", val)
        await update.message.reply_text(f"✅ Daily free credits set to: {val}")
    elif cmd == "upi":
        set_setting("upi_id", val)
        await update.message.reply_text(f"✅ UPI ID updated to: `{val}`", parse_mode='Markdown')
    elif cmd == "username":
        set_setting("admin_username", val)
        await update.message.reply_text(f"✅ Admin username updated to: @{val}")

async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 Your User ID: `{update.effective_user.id}`")

async def plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upi = get_setting("upi_id", os.getenv("UPI_ID", "yourname@upi"))
    username = get_setting("admin_username", os.getenv("ADMIN_USERNAME", "your_telegram_username"))
    
    # Remove @ if it was added by mistake in the setting
    clean_username = username.lstrip("@")
    
    default_plans = (
        "✨ **Premium Subscription Plans** ✨\n\n"
        "1️⃣ 1 Month: ₹XX\n"
        "2️⃣ 3 Months: ₹XX\n"
        "3️⃣ 6 Months: ₹XX\n"
        "4️⃣ 1 Year: ₹XX\n\n"
        "🚀 **Benefits:**\n"
        "✅ Unlimited File Links\n"
        "✅ No Daily Limits\n\n"
        f"📱 UPI ID: `{upi}`\n"
        f"👤 Admin: @{clean_username}\n\n"
        "📩 Send screenshot to Admin to activate!"
    )
    plans_text = get_setting("plans_text", default_plans)
    
    # Force replace upi and username tags in custom text
    plans_text = plans_text.replace("{upi}", upi).replace("{username}", f"@{clean_username}")
    
    keyboard = [[InlineKeyboardButton("📩 Contact Admin", url=f"https://t.me/{clean_username}")]]
    await update.message.reply_text(plans_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def edit_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("Usage: /editplan [new plans text]\n\nTip: Use {upi} and {username} in your text to auto-fill your settings.")
        return
    new_text = " ".join(context.args)
    set_setting("plans_text", new_text)
    await update.message.reply_text("✅ Plans details updated!")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("SELECT is_premium, expiry_date FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row and row[0] == 1:
        expiry_str = row[1] if row[1] else "Lifetime"
        await update.message.reply_text(f"🌟 **Premium Status: Active**\n📅 Expiry: `{expiry_str}`", parse_mode='Markdown')
    else:
        used = get_credits_used(user_id)
        limit = int(get_setting("free_credits", 2))
        await update.message.reply_text(f"🆓 **Plan: Free**\n📊 Credits: `{max(0, limit-used)}/{limit} left today`", parse_mode='Markdown')

async def end_premium_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("Usage: /endpremium [user_id]")
        return
    try:
        target_id = int(context.args[0])
        cur.execute("UPDATE users SET is_premium = 0 WHERE user_id = ?", (target_id,))
        conn.commit()
        await update.message.reply_text(f"✅ User {target_id} Premium access has been canceled.")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID.")

async def set_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setpremium [user_id] [months]")
        return
    try:
        target_id = int(context.args[0])
        months = int(context.args[1])
        expiry_date = datetime.now() + timedelta(days=30 * months)
        cur.execute("INSERT OR REPLACE INTO users (user_id, is_premium, expiry_date) VALUES (?, 1, ?)", 
                   (target_id, expiry_date.isoformat()))
        conn.commit()
        await update.message.reply_text(f"✅ User {target_id} is now Premium for {months} months!\n📅 Expiry: {expiry_date.strftime('%Y-%m-%d')}")
    except ValueError:
        await update.message.reply_text("❌ Invalid Input.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        code = context.args[0]
        cur.execute("SELECT file_id, file_type FROM files WHERE code=?", (code,))
        row = cur.fetchone()
        if row:
            file_id, file_type = row
            try:
                if file_type == 'photo': await update.message.reply_photo(file_id)
                elif file_type == 'video': await update.message.reply_video(file_id)
                elif file_type == 'audio': await update.message.reply_audio(file_id)
                else: await update.message.reply_document(file_id)
            except Exception:
                await update.message.reply_document(file_id)
        else:
            await update.message.reply_text("❌ File not found.")
    else:
        premium = is_premium(update.effective_user.id)
        used = get_credits_used(update.effective_user.id)
        limit = int(get_setting("free_credits", 2))
        status_text = "⭐ Premium" if premium else f"🆓 Free ({max(0, limit-used)}/{limit} credits left)"
        await update.message.reply_text(
            f"📂 Send me any file.\n🔗 I will give you a shareable link.\n\n"
            f"Status: {status_text}\n"
            "✨ Premium users get unlimited links!\n"
            "Use /help to learn how to use the bot."
        )

# ================== FILE HANDLER ==================
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message
    if not is_premium(user_id):
        used = get_credits_used(user_id)
        limit = int(get_setting("free_credits", 2))
        if used >= limit:
            username = get_setting("admin_username", os.getenv("ADMIN_USERNAME", "your_telegram_username")).lstrip("@")
            upi = get_setting("upi_id", os.getenv("UPI_ID", "yourname@upi"))
            keyboard = [[InlineKeyboardButton(f"🚀 Buy Premium (Contact @{username})", url=f"https://t.me/{username}")]]
            await msg.reply_text(
                f"❌ Your credits are expired (used {used}/{limit}).\n\n"
                f"💰 To get unlimited links, buy Premium!\n"
                f"Use /plan to see our subscription plans.\n"
                f"📱 UPI: `{upi}`\n"
                f"👤 Admin: @{username}\n"
                f"📩 Send screenshot to Admin below.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
    
    file_id = None
    file_type = 'document'
    if msg.document: file_id, file_type = msg.document.file_id, 'document'
    elif msg.video: file_id, file_type = msg.video.file_id, 'video'
    elif msg.audio: file_id, file_type = msg.audio.file_id, 'audio'
    elif msg.photo: file_id, file_type = msg.photo[-1].file_id, 'photo'
    if not file_id:
        await msg.reply_text("❌ Unsupported file type.")
        return

    code = generate_code()
    cur.execute("INSERT INTO files (code, file_id, file_type, user_id) VALUES (?, ?, ?, ?)",
               (code, file_id, file_type, user_id))
    conn.commit()

    link = f"https://t.me/{context.bot.username}?start={code}"
    if not is_premium(user_id):
        new_used = get_credits_used(user_id)
        limit = int(get_setting("free_credits", 2))
        credit_msg = f"\n\n📊 Credits: {new_used}/{limit} used."
    else:
        credit_msg = "\n\n⭐ Premium User (Unlimited)"

    await msg.reply_text(f"✅ File uploaded!\n\n🔗 Share link:\n{link}{credit_msg}")

# ================== MAIN ==================
def main():
    if not TOKEN or TOKEN == "YOUR_BOT_TOKEN":
        logger.error("No BOT_TOKEN found!")
        return
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("plan", plan))
    app.add_handler(CommandHandler("editplan", edit_plan))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("setpremium", set_premium))
    app.add_handler(CommandHandler("endpremium", end_premium_admin))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.AUDIO | filters.PHOTO, handle_file))
    logger.info("✅ Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
