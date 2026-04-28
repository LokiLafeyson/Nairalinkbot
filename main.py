print("STARTING UP", flush=True)
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
    get_pending_topup, delete_pending_topup,
    TOTAL_FEE_PERCENT
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
SET_PIN      = 1
CONFIRM_PIN  = 2
VERIFY_PIN   = 3
SEND_AMOUNT  = 4
SEND_RECIPIENT = 5
SEND_BANK    = 6
SEND_ACCOUNT = 7
SEND_CONFIRM = 8
TOPUP_CURRENCY = 10
TOPUP_AMOUNT   = 11


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
        f"🔐 First, set a 4-digit PIN to secure your account:"
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
        text="✅ Got it.\n\n🔐 Re-enter your PIN to confirm:"
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
        await update.message.reply_text(
            "⚠️ You don't have an account yet.\n\nType /start to get set up."
        )
        return ConversationHandler.END
    if get_failed_attempts(telegram_id) >= 3:
        await update.message.reply_text(
            "🔒 Your account is locked after too many failed PIN attempts.\n\n"
            "Please contact support to unlock it."
        )
        return ConversationHandler.END
    await update.message.reply_text("🔐 Enter your 4-digit PIN to continue:")
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
                text=(
                    "🔒 Account locked after 3 failed PIN attempts.\n\n"
                    "Please contact support to unlock your account."
                )
            )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ Incorrect PIN. You have {remaining} attempt(s) remaining."
            )
        return ConversationHandler.END

    reset_failed_attempts(telegram_id)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=(
            "✅ PIN verified.\n\n"
            "💸 How much would you like to send?\n\n"
            "Enter the amount in naira (minimum ₦500):\n"
            "Example: 50000"
        )
    )
    return SEND_AMOUNT


async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    if not amount_text.isdigit() or int(amount_text) < 500:
        await update.message.reply_text(
            "⚠️ Minimum transfer is ₦500. Enter a valid amount:\nExample: 50000"
        )
        return SEND_AMOUNT
    context.user_data["naira_amount"] = int(amount_text)
    await update.message.reply_text(
        f"💵 Amount: ₦{int(amount_text):,}\n\n"
        f"👤 What's the recipient's name?\nExample: Mum"
    )
    return SEND_RECIPIENT


async def get_recipient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    recipient = update.message.text.strip().title()
    context.user_data["recipient_name"] = recipient
    await update.message.reply_text(
        f"👤 Recipient: {recipient}\n\n"
        f"🏦 Which bank do they use?\n"
        f"Example: Access Bank, GTBank, Opay, Kuda"
    )
    return SEND_BANK


async def get_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bank = update.message.text.strip()
    bank_code = get_bank_code(bank)
    if bank_code == "000":
        await update.message.reply_text(
            "⚠️ We couldn't find that bank.\n\n"
            "Supported banks include: Access Bank, GTBank, Zenith, First Bank, UBA, "
            "Opay, Kuda, PalmPay, Moniepoint.\n\n"
            "Please check the name and try again."
        )
        return SEND_BANK
    context.user_data["recipient_bank"] = bank.title()
    await update.message.reply_text(
        f"🏦 Bank: {bank.title()}\n\n"
        f"🔢 Enter their 10-digit account number:"
    )
    return SEND_ACCOUNT


async def get_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    account = update.message.text.strip()
    if not account.isdigit() or len(account) != 10:
        await update.message.reply_text(
            "⚠️ Account number must be exactly 10 digits. Please try again:"
        )
        return SEND_ACCOUNT

    context.user_data["recipient_account"] = account
    naira_amount = context.user_data["naira_amount"]
    recipient = context.user_data["recipient_name"]
    bank = context.user_data["recipient_bank"]

    # Calculate fees using config
    fee_naira = round(naira_amount * TOTAL_FEE_PERCENT / 100)
    total_naira = naira_amount + fee_naira
    usdc_amount = round(naira_amount / NAIRA_TO_USD, 2)

    # Store for confirm step
    context.user_data["fee_naira"] = fee_naira
    context.user_data["total_naira"] = total_naira

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm & Send", callback_data="send_confirm_yes"),
            InlineKeyboardButton("❌ Cancel", callback_data="send_confirm_no"),
        ]
    ])

    await update.message.reply_text(
        f"📋 *Confirm Transfer*\n"
        f"{'─' * 22}\n"
        f"To:       {recipient}\n"
        f"Bank:     {bank}\n"
        f"Account:  {account}\n"
        f"{'─' * 22}\n"
        f"Amount:   ₦{naira_amount:,}\n"
        f"Fee ({TOTAL_FEE_PERCENT}%): ₦{fee_naira:,}\n"
        f"Total:    ₦{total_naira:,}\n"
        f"{'─' * 22}\n\n"
        f"Tap *Confirm & Send* to proceed:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    return SEND_CONFIRM


async def confirm_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles typed YES/NO as fallback — inline buttons are preferred."""
    response = update.message.text.strip().upper()
    if response == "NO":
        await update.message.reply_text("❌ Transfer cancelled.", reply_markup=get_main_menu())
        return ConversationHandler.END
    if response != "YES":
        await update.message.reply_text("Please tap Confirm & Send or Cancel above.")
        return SEND_CONFIRM
    await _execute_send(update, context, update.message.reply_text)
    return ConversationHandler.END


async def _execute_send(update, context, reply_func):
    """Shared send execution logic used by both button and text confirm."""
    naira_amount = context.user_data["naira_amount"]
    recipient    = context.user_data["recipient_name"]
    bank         = context.user_data["recipient_bank"]
    account      = context.user_data["recipient_account"]
    usdc_amount  = round(naira_amount / NAIRA_TO_USD, 2)
    transaction_id = generate_transaction_id()
    sender_id    = update.effective_user.id

    user_bal = get_user_balance(sender_id)
    if user_bal < naira_amount:
        await reply_func(
            f"❌ *Insufficient balance*\n\n"
            f"Your balance: ₦{user_bal:,}\n"
            f"Amount needed: ₦{naira_amount:,}\n\n"
            f"Use /topup to add funds.",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )
        return

    await reply_func("⏳ Processing your transfer...")
    result = initiate_paystack_transfer(recipient, bank, account, naira_amount)

    if result["status"] == "success":
        save_transaction(
            sender_id, recipient, bank, account,
            naira_amount, usdc_amount,
            result["reference"], transaction_id
        )
        update_user_balance(sender_id, naira_amount, "deduct")
        await reply_func(
            f"✅ *Transfer Successful!*\n\n"
            f"₦{naira_amount:,} sent to *{recipient}*\n\n"
            f"Bank:    {bank}\n"
            f"Account: {account}\n\n"
            f"Ref: `{result['reference']}`\n\n"
            f"💡 {recipient} will receive a bank alert shortly.",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )
    else:
        error_msg = result.get("message", "")
        # Human-readable error mapping
        if "insufficient" in error_msg.lower():
            friendly = "Your NairaLink balance is too low for this transfer. Use /topup to add funds."
        elif "invalid account" in error_msg.lower() or "account" in error_msg.lower():
            friendly = "The recipient's account number couldn't be verified. Please check the details and try again."
        elif "bank" in error_msg.lower():
            friendly = "The recipient's bank is temporarily unavailable. Please try again in a few minutes."
        elif "timeout" in error_msg.lower() or "network" in error_msg.lower():
            friendly = "Network timeout. Your funds were not deducted. Please try again."
        else:
            friendly = "Something went wrong on our end. Your funds were not deducted. Please try again shortly."

        await reply_func(
            f"❌ *Transfer Failed*\n\n"
            f"{friendly}\n\n"
            f"If this keeps happening, contact support.",
            parse_mode="Markdown",
            reply_markup=get_main_menu()
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.", reply_markup=get_main_menu())
    return ConversationHandler.END


# ─── Callback Handler ─────────────────────────────────────────────────────────

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # Always answer immediately to clear loading state
    data = query.data
    user_id = update.effective_user.id

    # ── Main menu ──
    if data == "menu_send":
        await query.message.reply_text(
            "💸 Use /send to start a transfer."
        )
        return

    if data == "menu_receive":
        wallet = get_wallet_address(user_id)
        await query.message.reply_text(
            f"📥 *Your Solana Wallet:*\n\n`{wallet}`\n\n"
            f"Share this address to receive USDC (Solana network).",
            parse_mode="Markdown"
        )
        return

    if data == "menu_balance":
        bal = get_user_balance(user_id)
        wallet = get_wallet_address(user_id)
        usdc_bal = get_usdc_balance(wallet) if wallet else 0.0
        await query.message.reply_text(
            f"💰 *Your Balance*\n\n"
            f"🇳🇬 Naira: ₦{bal:,}\n"
            f"💎 USDC: ${usdc_bal:.2f}",
            parse_mode="Markdown"
        )
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

    # ── Send flow — inline confirm ──
    if data == "send_confirm_yes":
        await query.edit_message_reply_markup(reply_markup=None)  # Remove buttons
        await _execute_send(update, context, query.message.reply_text)
        return

    if data == "send_confirm_no":
        await query.edit_message_text("❌ Transfer cancelled.")
        await query.message.reply_text("What would you like to do?", reply_markup=get_main_menu())
        return

    # ── Topup currency selection via inline button ──
    if data.startswith("topup_cur_"):
        currency = data.replace("topup_cur_", "")
        context.user_data["topup_currency"] = currency
        from commands import CURRENCY_SYMBOLS, TOPUP_AMOUNT
        symbol = CURRENCY_SYMBOLS.get(currency, "")
        await query.edit_message_text(
            f"💱 Currency: *{currency}*\n\n"
            f"How much {currency} would you like to top up?\n"
            f"Minimum: {symbol}5\n\n"
            f"Type the amount (numbers only):",
            parse_mode="Markdown"
        )
        return

    # ── Topup confirm ──
    if data.startswith("topup_confirm_"):
        parts = data.split("_")
        if len(parts) != 5:
            await query.edit_message_text(
                "⚠️ Something went wrong with this top-up.\n\nUse /topup to start a new one."
            )
            return

        topup_id    = int(parts[2])
        owner_id    = int(parts[3])
        naira_amount = int(parts[4])

        if user_id != owner_id:
            await query.answer("⛔ This top-up belongs to another account.", show_alert=True)
            return

        pending = get_pending_topup(topup_id)
        if not pending:
            await query.edit_message_text(
                "⚠️ This top-up has already been processed.\n\nUse /topup to start a new one."
            )
            return

        update_user_balance(owner_id, naira_amount, "add")
        delete_pending_topup(topup_id)
        new_bal = get_user_balance(owner_id)

        await query.edit_message_text(
            f"✅ *Top Up Successful!*\n\n"
            f"₦{naira_amount:,} added to your wallet.\n"
            f"New balance: ₦{new_bal:,}\n\n"
            f"Use /send to transfer money.",
            parse_mode="Markdown"
        )
        return

    # ── Topup cancel ──
    if data.startswith("topup_cancel_"):
        parts = data.split("_")
        if len(parts) == 3:
            topup_id = int(parts[2])
            delete_pending_topup(topup_id)
        await query.edit_message_text(
            "❌ Top-up cancelled.\n\nUse /topup whenever you're ready."
        )
        return


# ─── App Entry Point ──────────────────────────
