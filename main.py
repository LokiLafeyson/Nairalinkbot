import os
import threading
import traceback
import sys
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
from helpers import (
    init_db, get_user, create_user, get_wallet_address,
    verify_pin, increment_failed_attempts, reset_failed_attempts,
    get_failed_attempts, save_transaction, get_transaction_by_code,
    mark_redeemed, get_usdc_balance, generate_redemption_code,
    generate_transaction_id, NAIRA_TO_USD
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

SET_PIN = 1
CONFIRM_PIN = 2
VERIFY_PIN = 3
SEND_AMOUNT = 4
SEND_RECIPIENT = 5
SEND_BANK = 6
SEND_ACCOUNT = 7
SEND_CONFIRM = 8
REDEEM_CODE = 9

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    first_name = update.effective_user.first_name
    user = get_user(telegram_id)
    if user:
        await update.message.reply_text(
            f"👋 Welcome back, {first_name}!\n\n"
            f"💸 /send — Send money home\n"
            f"💰 /balance — Check your balance\n"
            f"👛 /wallet — View your wallet\n"
            f"🧾 /redeem — Redeem a cash code\n"
            f"📖 /help — How NairaLink works"
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            f"👋 Welcome to NairaLink, {first_name}!\n\n"
            f"Send money home instantly — your family receives "
            f"naira cash, no bank account needed.\n\n"
            f"🔐 Please set a 4-digit PIN:"
        )
        return SET_PIN

async def set_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    if not pin.isdigit() or len(pin) != 4:
        await update.message.reply_text(
            "⚠️ PIN must be exactly 4 digits.\n\nPlease enter a 4-digit PIN:"
        )
        return SET_PIN
    context.user_data["temp_pin"] = pin
    await update.message.reply_text(
        "✅ Got it.\n\n🔐 Confirm your PIN by entering it again:"
    )
    return CONFIRM_PIN

async def confirm_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    temp_pin = context.user_data.get("temp_pin")
    if pin != temp_pin:
        await update.message.reply_text(
            "❌ PINs do not match.\n\nEnter a new 4-digit PIN:"
        )
        return SET_PIN
    telegram_id = update.effective_user.id
    first_name = update.effective_user.first_name
    wallet_address = create_user(telegram_id, first_name, pin)
    await update.message.reply_text(
        f"🎉 Account created!\n\n"
        f"Welcome to NairaLink, {first_name}.\n\n"
        f"Your Solana wallet:\n`{wallet_address}`\n\n"
        f"💸 /send — Send money home\n"
        f"💰 /balance — Check balance\n"
        f"👛 /wallet — View wallet\n"
        f"🧾 /redeem — Redeem cash code",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    wallet_address = get_wallet_address(telegram_id)
    await update.message.reply_text(
        f"👛 Your Solana Wallet:\n`{wallet_address}`\n\n"
        f"Send USDC here to fund your account.",
        parse_mode="Markdown"
    )

async def send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return ConversationHandler.END
    if get_failed_attempts(telegram_id) >= 3:
        await update.message.reply_text("🔒 Account locked. Contact support.")
        return ConversationHandler.END
    await update.message.reply_text("🔐 Enter your PIN to continue:")
    return VERIFY_PIN

async def verify_pin_for_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    pin = update.message.text.strip()
    if not verify_pin(telegram_id, pin):
        increment_failed_attempts(telegram_id)
        remaining = 3 - get_failed_attempts(telegram_id)
        if remaining <= 0:
            await update.message.reply_text("🔒 Account locked. Contact support.")
        else:
            await update.message.reply_text(f"❌ Wrong PIN. {remaining} attempt(s) left.")
        return ConversationHandler.END
    reset_failed_attempts(telegram_id)
    await update.message.reply_text(
        "✅ PIN verified.\n\n💸 How much do you want to send?\n\nExample: 50000"
    )
    return SEND_AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    if not amount_text.isdigit() or int(amount_text) < 500:
        await update.message.reply_text(
            "⚠️ Enter a valid amount (minimum ₦500):\nExample: 50000"
        )
        return SEND_AMOUNT
    context.user_data["naira_amount"] = int(amount_text)
    await update.message.reply_text(
        f"💵 Amount: ₦{int(amount_text):,}\n\nWho are you sending to?\nExample: Mum"
    )
    return SEND_RECIPIENT

async def get_recipient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    recipient = update.message.text.strip().title()
    context.user_data["recipient_name"] = recipient
    await update.message.reply_text(
        f"👤 Recipient: {recipient}\n\n🏦 What is their bank name?\nExample: Access Bank"
    )
    return SEND_BANK

async def get_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bank = update.message.text.strip().title()
    context.user_data["recipient_bank"] = bank
    await update.message.reply_text(
        f"🏦 Bank: {bank}\n\n🔢 Enter their 10-digit account number:"
    )
    return SEND_ACCOUNT

async def get_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    account = update.message.text.strip()
    if not account.isdigit() or len(account) != 10:
        await update.message.reply_text(
            "⚠️ Must be exactly 10 digits.\n\nEnter account number again:"
        )
        return SEND_ACCOUNT
    context.user_data["recipient_account"] = account
    naira_amount = context.user_data["naira_amount"]
    recipient = context.user_data["recipient_name"]
    bank = context.user_data["recipient_bank"]
    usdc_amount = round(naira_amount / NAIRA_TO_USD, 2)
    await update.message.reply_text(
        f"📋 Confirm your transfer:\n\n"
        f"Amount: ₦{naira_amount:,}\n"
        f"USDC Value: ${usdc_amount}\n"
        f"Recipient: {recipient}\n"
        f"Bank: {bank}\n"
        f"Account: {account}\n"
        f"Rate: ₦{NAIRA_TO_USD:,} / $1\n\n"
        f"Type YES to confirm or NO to cancel:"
    )
    return SEND_CONFIRM

async def confirm_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response = update.message.text.strip().upper()
    if response == "NO":
        await update.message.reply_text("❌ Cancelled. Type /send to start again.")
        return ConversationHandler.END
    if response != "YES":
        await update.message.reply_text("Type YES to confirm or NO to cancel:")
        return SEND_CONFIRM
    naira_amount = context.user_data["naira_amount"]
    recipient = context.user_data["recipient_name"]
    bank = context.user_data["recipient_bank"]
    account = context.user_data["recipient_account"]
    usdc_amount = round(naira_amount / NAIRA_TO_USD, 2)
    redemption_code = generate_redemption_code()
    transaction_id = generate_transaction_id()
    save_transaction(
        update.effective_user.id, recipient, bank, account,
        naira_amount, usdc_amount, redemption_code, transaction_id
    )
    await update.message.reply_text(
        f"✅ Transfer Successful!\n\n"
        f"Amount: ₦{naira_amount:,}\n"
        f"USDC: ${usdc_amount}\n"
        f"Recipient: {recipient}\n"
        f"Bank: {bank}\n"
        f"Account: {account}\n\n"
        f"Transaction ID:\n`{transaction_id}`\n\n"
        f"Cash Pickup Code:\n🔑 `{redemption_code}`\n\n"
        f"Share this code with {recipient}.\n"
        f"They redeem it at any OPay or PalmPay agent.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🧾 Enter your redemption code:\n\nExample: NL-ABCD-1234"
    )
    return REDEEM_CODE

async def process_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    transaction = get_transaction_by_code(code)
    if not transaction:
        await update.message.reply_text("❌ Invalid code. Type /redeem to try again.")
        return ConversationHandler.END
    if transaction[9] == 'redeemed':
        await update.message.reply_text("⚠️ This code has already been redeemed.")
        return ConversationHandler.END
    mark_redeemed(code)
    await update.message.reply_text(
        f"✅ Code Redeemed!\n\n"
        f"Recipient: {transaction[2]}\n"
        f"Amount: ₦{transaction[5]:,}\n"
        f"Bank: {transaction[3]}\n"
        f"Account: {transaction[4]}\n\n"
        f"Visit any OPay or PalmPay agent to collect cash.\n\n"
        f"Thank you for using NairaLink! 🇳🇬"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled. Type /start to begin again.")
    return ConversationHandler.END

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    wallet_address = get_wallet_address(telegram_id)
    await update.message.reply_text("⏳ Checking your balance on Solana...")
    usdc_balance = get_usdc_balance(wallet_address)
    await update.message.reply_text(
        f"💰 USDC Balance: ${usdc_balance:.2f}\n\n"
        f"Wallet:\n`{wallet_address}`\n\n"
        f"Type /fund to add USDC.",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 How NairaLink Works\n\n"
        "1️⃣ Create account with /start\n"
        "2️⃣ Fund wallet with USDC\n"
        "3️⃣ Type /send and follow steps\n"
        "4️⃣ Enter recipient name, bank, account\n"
        "5️⃣ Confirm with PIN\n"
        "6️⃣ Recipient gets cash pickup code\n"
        "7️⃣ Redeem at OPay or PalmPay agent\n\n"
        "💡 Fees under 1 percent. Arrives in seconds."
    )

async def fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    wallet_address = get_wallet_address(telegram_id)
    if not wallet_address:
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    await update.message.reply_text(
        f"💳 Fund Your Wallet\n\n"
        f"1️⃣ Buy USDC on Quidax or Yellow Card\n"
        f"2️⃣ Send USDC to:\n`{wallet_address}`\n"
        f"3️⃣ Balance updates automatically\n\n"
        f"Type /balance to check.",
        parse_mode="Markdown"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    import sqlite3
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text("🗑️ Account reset. Type /start to create a new one.")

def main():
    init_db()
    keep_alive()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    registration_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SET_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_pin)],
            CONFIRM_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_pin)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    send_handler = ConversationHandler(
        entry_points=[CommandHandler("send", send)],
        states={
            VERIFY_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_pin_for_send)],
            SEND_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
            SEND_RECIPIENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_recipient)],
            SEND_BANK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bank)],
            SEND_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_account)],
            SEND_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_send)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    redeem_handler = ConversationHandler(
        entry_points=[CommandHandler("redeem", redeem)],
        states={
            REDEEM_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_redeem)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(registration_handler)
    app.add_handler(send_handler)
    app.add_handler(redeem_handler)
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("fund", fund))
    app.add_handler(CommandHandler("wallet", wallet))
    app.add_handler(CommandHandler("reset", reset))

    print("NairaLink bot is running...")
    app.run_polling()

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
                            
                
