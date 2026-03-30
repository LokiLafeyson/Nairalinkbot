import os
import sqlite3
import threading
import hashlib
import random
import string
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
from solders.pubkey import Pubkey
from solana.rpc.api import Client

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Solana devnet client
SOLANA_CLIENT = Client(
    "https://api.devnet.solana.com",
    timeout=10
)

# USDC devnet mint address
USDC_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"

# Naira to USDC rate (simulated)
NAIRA_TO_USD = 1650

# ---- CONVERSATION STATES ----
SET_PIN = 1
CONFIRM_PIN = 2
VERIFY_PIN = 3
SEND_AMOUNT = 4
SEND_RECIPIENT = 5
SEND_BANK = 6
SEND_ACCOUNT = 7
SEND_CONFIRM = 8
REDEEM_CODE = 9

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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            recipient_name TEXT,
            recipient_bank TEXT,
            recipient_account TEXT,
            naira_amount INTEGER,
            usdc_amount REAL,
            redemption_code TEXT,
            transaction_id TEXT,
            status TEXT DEFAULT 'pending',
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

def generate_redemption_code():
    letters = ''.join(random.choices(string.ascii_uppercase, k=4))
    numbers = ''.join(random.choices(string.digits, k=4))
    return f"NL-{letters}-{numbers}"

def generate_transaction_id():
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=44))

def save_transaction(sender_id, recipient_name, recipient_bank,
                     recipient_account, naira_amount, usdc_amount,
                     redemption_code, transaction_id):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO transactions
        (sender_id, recipient_name, recipient_bank, recipient_account,
        naira_amount, usdc_amount, redemption_code, transaction_id, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed')""",
        (sender_id, recipient_name, recipient_bank, recipient_account,
         naira_amount, usdc_amount, redemption_code, transaction_id)
    )
    conn.commit()
    conn.close()

def get_transaction_by_code(code):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM transactions WHERE redemption_code = ?",
        (code.upper(),)
    )
    result = cursor.fetchone()
    conn.close()
    return result

def mark_redeemed(code):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE transactions SET status = 'redeemed' WHERE redemption_code = ?",
        (code.upper(),)
    )
    conn.commit()
    conn.close()

def get_usdc_balance(wallet_address):
    try:
        pubkey = Pubkey.from_string(wallet_address)
        from solana.rpc.types import TokenAccountOpts
        opts = TokenAccountOpts(mint=Pubkey.from_string(USDC_MINT))
        response = SOLANA_CLIENT.get_token_accounts_by_owner(pubkey, opts)
        if response.value:
            amount = response.value[0].account.data.parsed[
                "info"]["tokenAmount"]["uiAmount"]
            return amount if amount else 0.0
        return 0.0
    except Exception:
        return 0.0

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
            f"🧾 /redeem — Redeem a cash code\n"
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
            "⚠️ PIN must be exactly 4 digits.\n\nPlease enter a 4-digit PIN:"
        )
        return SET_PIN
    context.user_data["temp_pin"] = pin
    await update.message.reply_text(
        "✅ Got it.\n\n🔐 Please confirm your PIN by entering it again:"
    )
    return CONFIRM_PIN

# ---- CONFIRM PIN ----
async def confirm_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    temp_pin = context.user_data.get("temp_pin")
    if pin != temp_pin:
        await update.message.reply_text(
            "❌ PINs do not match.\n\nPlease start again. Enter a new 4-digit PIN:"
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
        f"👛 /wallet — View your wallet\n"
        f"🧾 /redeem — Redeem a cash code\n\n"
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
            "⚠️ You need an account first.\n\nType /start to create one."
        )
        return
    wallet_address = get_wallet_address(telegram_id)
    await update.message.reply_text(
        f"👛 Your NairaLink Wallet\n\n"
        f"Solana Address:\n`{wallet_address}`\n\n"
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
            "⚠️ You need an account first.\n\nType /start to create one."
        )
        return ConversationHandler.END
    failed = get_failed_attempts(telegram_id)
    if failed >= 3:
        await update.message.reply_text(
            "🔒 Your account is locked.\n\nPlease contact support to unlock."
        )
        return ConversationHandler.END
    await update.message.reply_text("🔐 Enter your PIN to continue:")
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
                "🔒 Too many wrong attempts.\n\nYour account is now locked.\n"
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
        "💸 How much do you want to send?\n\n"
        "Type the amount in naira:\nExample: 50000"
    )
    return SEND_AMOUNT

# ---- GET AMOUNT ----
async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    if not amount_text.isdigit():
        await update.message.reply_text(
            "⚠️ Please enter numbers only.\n\nExample: 50000"
        )
        return SEND_AMOUNT
    amount = int(amount_text)
    if amount < 500:
        await update.message.reply_text(
            "⚠️ Minimum send amount is ₦500.\n\nPlease enter a higher amount:"
        )
        return SEND_AMOUNT
    context.user_data["naira_amount"] = amount
    await update.message.reply_text(
        f"💵 Amount: ₦{amount:,}\n\n"
        f"Who are you sending to?\n\nType the recipient's name:\nExample: Mum"
    )
    return SEND_RECIPIENT

# ---- GET RECIPIENT ----
async def get_recipient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    recipient = update.message.text.strip().title()
    context.user_data["recipient_name"] = recipient
    await update.message.reply_text(
        f"👤 Recipient: {recipient}\n\n"
        f"🏦 What is their bank name?\n\nExample: Access Bank"
    )
    return SEND_BANK

# ---- GET BANK ----
async def get_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bank = update.message.text.strip().title()
    context.user_data["recipient_bank"] = bank
    await update.message.reply_text(
        f"🏦 Bank: {bank}\n\n"
        f"🔢 What is their account number?\n\nType the 10-digit account number:"
    )
    return SEND_ACCOUNT

# ---- GET ACCOUNT NUMBER ----
async def get_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    account = update.message.text.strip()
    if not account.isdigit() or len(account) != 10:
        await update.message.reply_text(
            "⚠️ Account number must be exactly 10 digits.\n\n"
            "Please enter the account number again:"
        )
        return SEND_ACCOUNT
    context.user_data["recipient_account"] = account
    naira_amount = context.user_data["naira_amount"]
    recipient = context.user_data["recipient_name"]
    bank = context.user_data["recipient_bank"]
    usdc_amount = round(naira_amount / NAIRA_TO_USD, 2)
    await update.message.reply_text(
        f"📋 Please confirm your transfer:\n\n"
        f"Amount: ₦{naira_amount:,}\n"
        f"USDC Value: ${usdc_amount}\n"
        f"Recipient: {recipient}\n"
        f"Bank: {bank}\n"
        f"Account: {account}\n"
        f"Rate: ₦{NAIRA_TO_USD:,} / $1\n"
        f"Fee: Under 1%\n\n"
        f"Type YES to confirm or NO to cancel:"
    )
    return SEND_CONFIRM

# ---- CONFIRM SEND ----
async def confirm_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response = update.message.text.strip().upper()
    if response == "NO":
        await update.message.reply_text(
            "❌ Transfer cancelled.\n\nType /send to start again."
        )
        return ConversationHandler.END
    if response != "YES":
        await update.message.reply_text(
            "Please type YES to confirm or NO to cancel:"
        )
        return SEND_CONFIRM
    naira_amount = context.user_data["naira_amount"]
    recipient = context.user_data["recipient_name"]
    bank = context.user_data["recipient_bank"]
    account = context.user_data["recipient_account"]
    usdc_amount = round(naira_amount / NAIRA_TO_USD, 2)
    redemption_code = generate_redemption_code()
    transaction_id = generate_transaction_id()
    sender_id = update.effective_user.id
    save_transaction(
        sender_id, recipient, bank, account,
        naira_amount, usdc_amount, redemption_code, transaction_id
    )
    await update.message.reply_text(
        f"✅ Transfer Successful!\n\n"
        f"Amount: ₦{naira_amount:,}\n"
        f"USDC Value: ${usdc_amount}\n"
        f"Recipient: {recipient}\n"
        f"Bank: {bank}\n"
        f"Account: {account}\n\n"
        f"Transaction ID:\n`{transaction_id}`\n\n"
        f"Cash Pickup Code:\n🔑 `{redemption_code}`\n\n"
        f"Share this code with {recipient}.\n"
        f"They can redeem it at any OPay or "
        f"PalmPay agent to receive their cash.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ---- /redeem ----
async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧾 Redeem Your Cash\n\n"
        "Enter your redemption code:\n\nExample: NL-ABCD-1234"
    )
    return REDEEM_CODE

async def process_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    transaction = get_transaction_by_code(code)
    if not transaction:
        await update.message.reply_text(
            "❌ Invalid code.\n\n"
            "Please check the code and try again.\n\nType /redeem to try again."
        )
        return ConversationHandler.END
    if transaction[9] == 'redeemed':
        await update.message.reply_text(
            "⚠️ This code has already been redeemed.\n\n"
            "Contact support if you think this is an error."
        )
        return ConversationHandler.END
    mark_redeemed(code)
    naira_amount = transaction[5]
    recipient_name = transaction[2]
    bank = transaction[3]
    account = transaction[4]
    await update.message.reply_text(
        f"✅ Code Redeemed Successfully!\n\n"
        f"Recipient: {recipient_name}\n"
        f"Amount: ₦{naira_amount:,}\n"
        f"Bank: {bank}\n"
        f"Account: {account}\n\n"
        f"Please visit your nearest OPay or PalmPay "
        f"agent to collect your cash.\n\n"
        f"Show them this confirmation message.\n\n"
        f"Thank you for using NairaLink! 🇳🇬"
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
            "⚠️ You need an account first.\n\nType /start to create one."
        )
        return
    wallet_address = get_wallet_address(telegram_id)
    await update.message.reply_text("⏳ Checking your balance on Solana...")
    usdc_balance = get_usdc_balance(wallet_address)
    await update.message.reply_text(
        f"💰 Your NairaLink Balance\n\n"
        f"USDC Balance: ${usdc_balance:.2f}\n\n"
        f"Wallet:\n`{wallet_address}`\n\n"
        f"Type /fund to add USDC to your wallet.",
        parse_mode="Markdown"
    )

# ---- /help ----
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 How NairaLink Works\n\n"
        "1️⃣ Create your account with /start\n"
        "2️⃣ Fund your wallet with USDC\n"
        "3️⃣ Type /send and follow the steps\n"
        "4️⃣ Enter recipient name, bank and account number\n"
        "5️⃣ Confirm with your PIN\n"
        "6️⃣ Recipient gets a cash pickup code\n"
        "7️⃣ They redeem at any OPay or PalmPay agent\n\n"
        "💡 Fees under 1 percent. Arrives in seconds."
    )

# ---- /fund ----
async def fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    wallet_address = get_wallet_address(telegram_id)
    if not wallet_address:
        await update.message.reply_text(
            "⚠️ You need an account first.\n\nType /start to create one."
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

# ---- RESET (testing only) ----
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    conn = sqlite3.conn
