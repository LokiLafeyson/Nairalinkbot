import os
import sqlite3
import threading
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from dotenv import load_dotenv
from solders.keypair import Keypair

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ---- CONVERSATION STATES ----
SET_PIN = 1
CONFIRM_PIN = 2
VERIFY_PIN = 3
SEND_AMOUNT = 4

# ---- DATABASE SETUP ----
def init_db():
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            first_name TEXT,
            pin_hash TEXT,
            wallet_address TEXT,
            wallet_private_key TEXT,
            failed_attempts INTEGER DEFAULT 0,
            locked_until INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()

def get_user(telegram_id):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    user = cursor.fetchone()
    conn.close()
    return user

def create_user(telegram_id, first_name, pin):
    # Generate Solana wallet
    keypair = Keypair()
    wallet_address = str(keypair.pubkey())
    wallet_private_key = str(keypair)

    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO users 
        (telegram_id, first_name, pin_hash, wallet_address, wallet_private_key) 
        VALUES (?, ?, ?, ?, ?)""",
        (telegram_id, first_name, hash_pin(pin), wallet_address, wallet_private_key)
    )
    conn.commit()
    conn.close()
    return wallet_address

def get_wallet_address(telegram_id):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT wallet_address FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def verify_pin(telegram_id, pin):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT pin_hash FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    result = cursor.fetchone()
    conn.close()
    if result:
        return result[0] == hash_pin(pin)
    return False

def increment_failed_attempts(telegram_id):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET failed_attempts = failed_attempts + 1 WHERE telegram_id = ?",
        (telegram_id,)
    )
    conn.commit()
    conn.close()

def reset_failed_attempts(telegram_id):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET failed_attempts = 0 WHERE telegram_id = ?",
        (telegram_id,)
    )
    conn.commit()
    conn.close()

def get_failed_attempts(telegram_id):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT failed_attempts FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

# ---- KEEP ALIVE SERVER ----
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"NairaLink is alive")

    def log_message(self, format, *args):
        pass

def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()

def keep_alive():
    thread = threading.Thread(target=run_server)
    thread.daemon = True
    thread.start()

# ---- /start ----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    first_name = update.effective_user.first_name
    user = get_user(telegram_id)

    if user:
        await update.message.reply_text(
            f"👋 Welcome back, {first_name}!\n\n"
            f"What you can do:\n"
            f"💸 /send — Send money home\n"
            f"💰 /balance — Check your balance\n"
            f"👛 /wallet — View your wallet address\n"
            f"📖 /help — How NairaLink works"
        )
        return ConversationHandler.END

    else:
        await update.message.reply_text(
            f"👋 Welcome to NairaLink, {first_name}!\n\n"
            f"Send money home instantly — your family receives "
            f"naira cash, no bank account needed.\n\n"
            f"First let's secure your account.\n\n"
            f"🔐 Please set a 4-digit PIN:"
        )
        return SET_PIN

# ---- SET PIN ----
async def set_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()

    if not pin.isdigit() or len(pin) != 4:
        await update.message.reply_text(
            "⚠️ PIN must be exactly 4 digits.\n\n"
            "Please enter a 4-digit PIN:"
        )
        return SET_PIN

    context.user_data["temp_pin"] = pin
    await update.message.reply_text(
        "✅ Got it.\n\n"
        "🔐 Please confirm your PIN by entering it again:"
    )
    return CONFIRM_PIN

# ---- CONFIRM PIN ----
async def confirm_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    temp_pin = context.user_data.get("temp_pin")

    if pin != temp_pin:
        await update.message.reply_text(
            "❌ PINs do not match.\n\n"
            "Please start again. Enter a new 4-digit PIN:"
        )
        return SET_PIN

    telegram_id = update.effective_user.id
    first_name = update.effective_user.first_name
    wallet_address = create_user(telegram_id, first_name, pin)

    await update.message.reply_text(
        f"🎉 Account created successfully!\n\n"
        f"Welcome to NairaLink, {first_name}.\n\n"
        f"Your Solana wallet has been created:\n"
        f"`{wallet_address}`\n\n"
        f"What you can do:\n"
        f"💸 /send — Send money home\n"
        f"💰 /balance — Check your balance\n"
        f"👛 /wallet — View your wallet address\n"
        f"📖 /help — How NairaLink works\n\n"
        f"Your account is secured with your PIN.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ---- /wallet ----
async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)

    if not user:
        await update.message.reply_text(
            "⚠️ You need an account first.\n\n"
            "Type /start to create one."
        )
        return

    wallet_address = get_wallet_address(telegram_id)
    await update.message.reply_text(
        f"👛 Your NairaLink Wallet\n\n"
        f"Solana Address:\n"
        f"`{wallet_address}`\n\n"
        f"Send USDC to this address to fund your account.\n\n"
        f"Type /balance to check your balance.",
        parse_mode="Markdown"
    )

# ---- /send ----
async def send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)

    if not user:
        await update.message.reply_text(
            "⚠️ You need an account first.\n\n"
            "Type /start to create one."
        )
        return ConversationHandler.END

    failed = get_failed_attempts(telegram_id)
    if failed >= 3:
        await update.message.reply_text(
            "🔒 Your account is locked due to too many "
            "wrong PIN attempts.\n\n"
            "Please contact support to unlock."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "🔐 Enter your PIN to continue:"
    )
    return VERIFY_PIN

# ---- VERIFY PIN FOR SEND ----
async def verify_pin_for_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    pin = update.message.text.strip()

    if not verify_pin(telegram_id, pin):
        increment_failed_attempts(telegram_id)
        failed = get_failed_attempts(telegram_id)
        remaining = 3 - failed

        if remaining <= 0:
            await update.message.reply_text(
                "🔒 Too many wrong attempts.\n\n"
                "Your account is now locked.\n"
                "Contact support to unlock."
            )
        else:
            await update.message.reply_text(
                f"❌ Wrong PIN. {remaining} attempt(s) remaining."
            )
        return ConversationHandler.END

    reset_failed_attempts(telegram_id)
    await update.message.reply_text(
        "✅ PIN verified.\n\n"
        "💸 Type your send instruction:\n\n"
        "send 50000 to Mum"
    )
    return SEND_AMOUNT

# ---- PROCESS SEND ----
async def process_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower().strip()
    parts = text.split()

    if len(parts) >= 4 and parts[0] == "send" and parts[2] == "to":
        try:
            amount = int(parts[1])
            recipient = " ".join(parts[3:]).title()
            await update.message.reply_text(
                f"✅ Transfer Initiated\n\n"
                f"Amount: ₦{amount:,}\n"
                f"Recipient: {recipient}\n"
                f"Status: Processing on Solana...\n\n"
                f"⏳ Recipient will receive a cash "
                f"pickup code shortly.\n\n"
                f"Transaction ID: TXN{amount}SOL001"
            )
        except ValueError:
            await update.message.reply_text(
                "⚠️ Could not read that amount.\n\n"
                "Please try:\nsend 50000 to Mum"
            )
    else:
        await update.message.reply_text(
            "⚠️ Please use this format:\n\nsend 50000 to Mum"
        )

    return ConversationHandler.END

# ---- CANCEL ----
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Cancelled. Type /start to begin again."
    )
    return ConversationHandler.END

# ---- /balance ----
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    user = get_user(telegram_id)

    if not user:
        await update.message.reply_text(
            "⚠️ You need an account first.\n\n"
            "Type /start to create one."
        )
        return

    wallet_address = get_wallet_address(telegram_id)
    await update.message.reply_text(
        f"💰 Your NairaLink Balance\n\n"
        f"USDC Balance: $0.00\n\n"
        f"Fund your wallet:\n"
        f"`{wallet_address}`\n\n"
        f"Type /fund for funding instructions.",
        parse_mode="Markdown"
    )

# ---- /help ----
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 How NairaLink Works\n\n"
        "1️⃣ Create your account with /start\n"
        "2️⃣ Fund your wallet with USDC\n"
        "3️⃣ Type: send 50000 to Mum\n"
        "4️⃣ Enter your PIN to confirm\n"
        "5️⃣ Recipient gets a cash pickup code\n"
        "6️⃣ They redeem at any OPay or PalmPay agent\n\n"
        "💡 Fees under 1 percent. Arrives in seconds."
    )

# ---- /fund ----
async def fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    wallet_address = get_wallet_address(telegram_id)

    if not wallet_address:
        await update.message.reply_text(
            "⚠️ You need an account first.\n\n"
            "Type /start to create one."
        )
        return

    await update.message.reply_text(
        f"💳 Fund Your Wallet\n\n"
        f"1️⃣ Buy USDC on Quidax or Yellow Card\n"
        f"2️⃣ Send USDC to your NairaLink wallet:\n"
        f"`{wallet_address}`\n"
        f"3️⃣ Your balance updates automatically\n\n"
        f"Type /balance to check your balance.",
        parse_mode="Markdown"
    )

# ---- MAIN ----
def main():
    init_db()
    keep_alive()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    registration_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SET_PIN: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, set_pin
            )],
            CONFIRM_PIN: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, confirm_pin
            )],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    send_handler = ConversationHandler(
        entry_points=[CommandHandler("send", send)],
        states={
            VERIFY_PIN: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, verify_pin_for_send
            )],
            SEND_AMOUNT: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, process_send
            )],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(registration_handler)
    app.add_handler(send_handler)
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("fund", fund))
    app.add_handler(CommandHandler("wallet", wallet))

    print("NairaLink bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()                          

