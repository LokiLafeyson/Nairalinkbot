import os
import json
import hmac
import hashlib
import threading
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv
from helpers import (
    init_db, get_user, create_user, get_wallet_address,
    verify_pin, increment_failed_attempts, reset_failed_attempts,
    get_failed_attempts, save_transaction, get_usdc_balance,
    generate_transaction_id, NAIRA_TO_USD,
    get_bank_code, get_user_balance, update_user_balance,
    generate_transak_link, calculate_send_cost, get_exchange_rate,
    get_user_by_wallet, generate_moonpay_url,
    get_pending_topup, delete_pending_topup
)
from paystack import initiate_paystack_transfer
from commands import (
    balance, history, wallet_command, fund,
    help_command, reset, topup, topup_currency, topup_amount,
    get_main_menu
)
from admin import add_funds, get_balance_admin, list_users, cmd_check_balance

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
MOONPAY_WEBHOOK_SECRET = os.getenv("MOONPAY_WEBHOOK_SECRET", "")

# ─── Conversation States ──────────────────────────────────────────────────────
SET_PIN = 1
CONFIRM_PIN = 2
VERIFY_PIN = 3
SEND_AMOUNT = 4
SEND_RECIPIENT = 5
SEND_BANK = 6
SEND_ACCOUNT = 7
SEND_CONFIRM = 8
TOPUP_CURRENCY = 10
TOPUP_AMOUNT = 11


# ─── Keep-Alive HTTP Server ───────────────────────────────────────────────────

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"NairaLink is alive")

    def do_POST(self):
        if self.path == "/moonpay/webhook":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            sig_header = self.headers.get("Moonpay-Signature-V2", "")
            expected = hmac.new(
                MOONPAY_WEBHOOK_SECRET.encode(),
                body,
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(expected, sig_header):
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"Unauthorized")
                return

            try:
                data = json.loads(body)
                if data.get("type") == "transaction_updated":
                    txn = data.get("data", {})
                    if txn.get("status") == "completed":
                        wallet = txn.get("walletAddress")
                        amount = float(txn.get("quoteCurrencyAmount", 0))
                        naira_amount = int(amount * NAIRA_TO_USD)
                        user = get_user_by_wallet(wallet)
                        if user:
                            telegram_id = user[0]
                            update_user_balance(telegram_id, naira_amount, "add")
                            print(f"[MoonPay Webhook] ₦{naira_amount:,} credited to {telegram_id}")
            except Exception as e:
                print(f"[MoonPay Webhook Error] {e}")

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def run_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()


def keep_alive():
    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()


# ─── Registration Flow ────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    first_name = update.effective_user.first_name
    if get_user(telegram_id):
        await update.message.reply_text(
            f"👋 Welcome back, {first_name}!\n\nWhat would you like to do?",
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END
    await update.message.reply_text(
        f"👋 Welcome to NairaLink, {first_name}!\n\n"
        f"Send money home instantly — your family receives "
        f"naira directly in their bank account.\n\n"
        f"🔐 Set a 4-digit PIN to secure your account:"
    )
    return SET_PIN


async def set_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    if not pin.isdigit() or len(pin) != 4:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ PIN must be exactly 4 digits. Try again:"
        )
        return SET_PIN
    context.user_data["temp_pin"] = pin
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ Got it.\n\n🔐 Confirm your PIN:"
    )
    return CONFIRM_PIN


async def confirm_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pin = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    temp_pin = context.user_data.get("temp_pin")
    if pin != temp_pin:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="❌ PINs don't match. Enter a new 4-digit PIN:"
        )
        return SET_PIN

    telegram_id = update.effective_user.id
    first_name = update.effective_user.first_name
    wallet_address = create_user(telegram_id, first_name, pin)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            f"🎉 *Account created!*\n\n"
            f"Welcome to NairaLink, {first_name}.\n\n"
            f"Your Solana wallet:\n`{wallet_address}`\n\n"
            f"What would you like to do?"
        ),
        parse_mode="Markdown",
        reply_markup=get_main_menu()
    )

    # Send PIN to user privately and delete it from chat
    await context.bot.send_message(
        chat_id=telegram_id,
        text=(
            f"🔐 *Your NairaLink PIN — Save This Securely*\n\n"
            f"PIN: `{temp_pin}`\n\n"
            f"⚠️ Never share this. NairaLink staff will never ask for it.\n"
            f"Store it somewhere safe — you need it to send money."
        ),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ─── Send Flow ────────────────────────────────────────────────────────────────

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
    try:
        await update.message.delete()
    except Exception:
        pass
    if not verify_pin(telegram_id, pin):
        increment_failed_attempts(telegram_id)
        remaining = 3 - get_failed_attempts(telegram_id)
        if remaining <= 0:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="🔒 Account locked after 3 failed attempts. Contact support."
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Wrong PIN. {remaining} attempt(s) left."
            )
        return ConversationHandler.END
    reset_failed_attempts(telegram_id)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "✅ PIN verified.\n\n"
            "💸 How much do you want to send?\n\n"
            "Enter amount in naira (minimum ₦500):\nExample: 50000"
        )
    )
    return SEND_AMOUNT


async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    if not amount_text.isdigit() or int(amount_text) < 500:
        await update.message.reply_text(
            "⚠️ Minimum ₦500. Enter a valid amount:\nExample: 50000"
        )
        return SEND_AMOUNT
    context.user_data["naira_amount"] = int(amount_text)
    await update.message.reply_text(
        f"💵 Amount: ₦{int(amount_text):,}\n\n"
        f"👤 Recipient's name?\nExample: Mum"
    )
    return SEND_RECIPIENT


async def get_recipient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    recipient = update.message.text.strip().title()
    context.user_data["recipient_name"] = recipient
    await update.message.reply_text(
        f"👤 Recipient: {recipient}\n\n"
        f"🏦 Their bank?\nExample: Access Bank, GTBank, Opay, Kuda"
    )
    return SEND_BANK


async def get_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bank = update.message.text.strip()
    bank_code = get_bank_code(bank)
    if bank_code == "000":
        await update.message.reply_text(
            "⚠️ Bank not recognised.\n\n"
            "Supported: Access Bank, GTBank, Zenith, First Bank, UBA, "
            "Opay, Kuda, PalmPay, Moniepoint"
        )
        return SEND_BANK
    context.user_data["recipient_bank"] = bank.title()
    await update.message.reply_text(
        f"🏦 Bank: {bank.title()}\n\n🔢 Their 10-digit account number:"
    )
    return SEND_ACCOUNT


async def get_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    account = update.message.text.strip()
    if not account.isdigit() or len(account) != 10:
        await update.message.reply_text(
            "⚠️ Must be exactly 10 digits. Try again:"
        )
        return SEND_ACCOUNT
    context.user_data["recipient_account"] = account
    naira_amount = context.user_data["naira_amount"]
    recipient = context.user_data["recipient_name"]
    bank = context.user_data["recipient_bank"]
    usdc_amount = round(naira_amount / NAIRA_TO_USD, 2)
    fee = round(naira_amount * 0.008)
    total = naira_amount + fee
    await update.message.reply_text(
        f"📋 *Confirm Transfer*\n\n"
        f"Recipient: {recipient}\n"
        f"Bank: {bank}\n"
        f"Account: {account}\n\n"
        f"Amount: ₦{naira_amount:,}\n"
        f"Fee (0.8%): ₦{fee:,}\n"
        f"Total: ₦{total:,}\n"
        f"USDC value: ${usdc_amount}\n\n"
        f"Type *YES* to confirm or *NO* to cancel:",
        parse_mode="Markdown"
    )
    return SEND_CONFIRM


async def confirm_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response = update.message.text.strip().upper()
    if response == "NO":
        await update.message.reply_text(
            "❌ Cancelled.",
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END
    if response != "YES":
        await update.message.reply_text("Type YES to confirm or NO to cancel:")
        return SEND_CONFIRM

    naira_amount = context.user_data["naira_amount"]
    recipient = context.user_data["recipient_name"]
    bank = context.user_data["recipient_bank"]
    account = context.user_data["recipient_account"]
    usdc_amount = round(naira_amount / NAIRA_TO_USD, 2)
    transaction_id = generate_transaction_id()
    sender_id = update.effective_user.id

    user_bal = get_user_balance(sender_id)
    if user_bal < naira_amount:
        await update.message.reply_text(
            f"❌ Insufficient balance.\n\n"
            f"Your balance: ₦{user_bal:,}\n"
            f"Amount needed: ₦{naira_amount:,}\n\n"
            f"Use /topup to add funds.",
            reply_markup=get_main_menu()
        )
        return ConversationHandler.END

    await update.message.reply_text("⏳ Processing transfer...")
    result = initiate_paystack_transfer(recipient, bank, account, naira_amount)

    if result["status"] == "success":
        save_transaction(
            sender_id, recipient, bank, account,
            naira_amount, usdc_amount,
            result["reference"], transaction_id
        )
        update_user_balance(sender_id, naira_amount, "deduct")
        await update.message.reply_text(
            f"✅ *Transfer Successful!*\n\n"
            f"₦{naira_amount:,} sent to:\n\n"
            f"Recipient: {recipient}\n"
            f"Bank: {bank}\n"
            f"Account: {account}\n\n"
            f"Paystack Ref: `{result['reference']}`\n"
            f"Transaction ID: `{transaction_id}`\n\n"
            f"💡 {recipient} will receive a bank alert shortly.\n\n"
            f"_Powered by Paystack + Solana_",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )
    else:
        await update.message.reply_text(
            f"❌ Transfer failed.\n\n"
            f"Reason: {result.get('message', 'Unknown error')}\n\n"
            f"Type /send to try again.",
            reply_markup=get_main_menu()
        )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Cancelled.",
        reply_markup=get_main_menu()
    )
    return ConversationHandler.END


# ─── Callback Handler ─────────────────────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    # ── Main menu buttons ──
    if data == "menu_send":
        await query.message.reply_text("💸 Use /send to start a transfer.")
        return

    if data == "menu_receive":
        wallet = get_wallet_address(user_id)
        await query.message.reply_text(
            f"📥 *Your Solana Wallet:*\n\n`{wallet}`\n\n"
            f"Share this address to receive USDC.",
            parse_mode="Markdown"
        )
        return

    if data == "menu_balance":
        bal = get_user_balance(user_id)
        await query.message.reply_text(f"💰 Your balance: ₦{bal:,}")
        return

    if data == "menu_wallet":
        wallet = get_wallet_address(user_id)
        await query.message.reply_text(
            f"👛 *Your Wallet:*\n\n`{wallet}`",
            parse_mode="Markdown"
        )
        return

    if data == "menu_history":
        await query.message.reply_text("📋 Use /history to view your transactions.")
        return

    if data == "menu_topup":
        await query.message.reply_text("➕ Use /topup to fund your wallet.")
        return

    if data == "menu_help":
        await query.message.reply_text("📖 Use /help to learn how NairaLink works.")
        return

    # ── Topup confirm ──
    # callback_data format: topup_confirm_{topup_id}_{telegram_id}_{naira_amount}
    if data.startswith("topup_confirm_"):
        parts = data.split("_")
        # ["topup", "confirm", topup_id, telegram_id, naira_amount]
        if len(parts) != 5:
            await query.edit_message_text("⚠️ Invalid confirmation. Use /topup to start again.")
            return

        topup_id = int(parts[2])
        owner_id = int(parts[3])
        naira_amount = int(parts[4])

        # Security: only the owner can confirm
        if user_id != owner_id:
            await query.answer("⛔ This isn't your topup.", show_alert=True)
            return

        # Verify the pending topup still exists (prevents double-tap)
        pending = get_pending_topup(topup_id)
        if not pending:
            await query.edit_message_text(
                "⚠️ This topup has already been processed or expired.\n\n"
                "Use /topup to start a new one."
            )
            return

        update_user_balance(owner_id, naira_amount, "add")
        delete_pending_topup(topup_id)
        new_bal = get_user_balance(owner_id)

        await query.edit_message_text(
            f"✅ *Top Up Confirmed!*\n\n"
            f"₦{naira_amount:,} added to your wallet.\n"
            f"New balance: ₦{new_bal:,}\n\n"
            f"Use /send to transfer money to Nigeria.",
            parse_mode="Markdown"
        )
        return

    # ── Topup cancel ──
    # callback_data format: topup_cancel_{topup_id}
    if data.startswith("topup_cancel_"):
        parts = data.split("_")
        if len(parts) == 3:
            topup_id = int(parts[2])
            delete_pending_topup(topup_id)
        await query.edit_message_text(
            "❌ Top up cancelled.\n\nUse /topup to start again.",
        )
        return


# ─── App Entry Point ──────────────────────────────────────────────────────────

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

    topup_handler = ConversationHandler(
        entry_points=[CommandHandler("topup", topup)],
        states={
            TOPUP_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_currency)],
            TOPUP_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(registration_handler)
    app.add_handler(send_handler)
    app.add_handler(topup_handler)
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("fund", fund))
    app.add_handler(CommandHandler("wallet", wallet_command))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("add_funds", add_funds))
    app.add_handler(CommandHandler("get_balance", get_balance_admin))
    app.add_handler(CommandHandler("list_users", list_users))
    app.add_handler(CommandHandler("check_balance", cmd_check_balance))
    app.add_handler(CallbackQueryHandler(button_callback))

    print("NairaLink bot is running...")
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
