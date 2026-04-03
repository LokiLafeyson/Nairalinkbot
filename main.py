.ext import os
import threading
import sys
import httpx
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv
from helpers import (
    init_db, get_user, create_user, get_wallet_address,
    verify_pin, increment_failed_attempts, reset_failed_attempts,
    get_failed_attempts, save_transaction, get_usdc_balance,
    generate_transaction_id, NAIRA_TO_USD,
    simulate_paystack_transfer, get_bank_code,
    generate_transak_link, calculate_send_cost, get_exchange_rate
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
TOPUP_CURRENCY = 10
TOPUP_AMOUNT = 11

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
            f"💱 /topup — Fund wallet with GBP/USD/EUR\n"
            f"💸 /send — Send money home\n"
            f"💰 /balance — Check your balance\n"
            f"👛 /wallet — View your wallet\n"
            f"📖 /help — How NairaLink works"
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            f"👋 Welcome to NairaLink, {first_name}!\n\n"
            f"Send money home instantly — your family receives "
            f"naira directly in their bank account.\n\n"
            f"🔐 Please set a 4-digit PIN:"
        )
        return SET_PIN

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
        f"💱 /topup — Fund wallet\n"
        f"💸 /send — Send money home\n"
        f"💰 /balance — Check balance\n"
        f"👛 /wallet — View wallet",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text(
            "⚠️ Type /start to create an account."
        )
        return
    wallet_address = get_wallet_address(telegram_id)
    await update.message.reply_text(
        f"👛 Your Solana Wallet:\n`{wallet_address}`\n\n"
        f"Send USDC here to fund your account.",
        parse_mode="Markdown"
    )

async def topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    if not amount_text.replace(".", "").isdigit():
        await update.message.reply_text(
            "⚠️ Please enter a valid amount:\nExample: 50"
        )
        return TOPUP_AMOUNT

    amount = float(amount_text)
    if amount < 5:
        await update.message.reply_text(
            "⚠️ Minimum amount is 5.\n\nPlease enter a higher amount:"
        )
        return TOPUP_AMOUNT

    currency = context.user_data["topup_currency"]
    telegram_id = update.effective_user.id
    wallet_address = get_wallet_address(telegram_id)

    # Send loading message and keep reference to edit it
    loading_msg = await update.message.reply_text(
        "⏳ Getting live exchange rate..."
    )

    # Fetch live NGN rate
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://open.er-api.com/v6/latest/{currency}"
            )
            data = resp.json()
            if data.get("result") == "success":
                rate = data["rates"]["NGN"]
            else:
                raise ValueError("Bad response")
    except Exception:
        # Fallback to hardcoded rate if API fails
        fallback_rates = {
            "GBP": 2050, "USD": 1620, "EUR": 1750, "CAD": 1190
        }
        rate = fallback_rates[currency]

    naira_equivalent = int(amount * rate)
    costs = calculate_send_cost(naira_equivalent, currency)

    currency_symbols = {"GBP": "£", "USD": "$", "EUR": "€", "CAD": "CA$"}
    symbol = currency_symbols[currency]

    transak_key = os.getenv("TRANSAK_API_KEY", "demo")
    payment_link = generate_transak_link(
        transak_key, amount, currency, wallet_address
    )

    # Edit the loading message instead of sending a new one
    await loading_msg.edit_text(
        f"💱 Live Exchange Rate\n\n"
        f"You send: {symbol}{amount} {currency}\n"
        f"Fee: {symbol}{costs['fee_foreign']} (0.8%)\n"
        f"Total: {symbol}{costs['total_foreign']} {currency}\n\n"
        f"Recipient gets: ₦{costs['naira_amount']:,}\n"
        f"USDC Value: ${costs['usdc_amount']}\n"
        f"Rate: {symbol}1 = ₦{rate:,.0f}\n\n"
        f"💳 Complete payment here:\n"
        f"{payment_link}\n\n"
        f"After payment your wallet will be funded "
        f"with USDC automatically.\n\n"
        f"Then type /send to transfer to Nigeria."
    )
    return ConversationHandler.END

async def send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text(
            "⚠️ Type /start to create an account."
        )
        return ConversationHandler.END
    if get_failed_attempts(telegram_id) >= 3:
        await update.message.reply_text(
            "🔒 Account locked. Contact support."
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "🔐 Enter your PIN to continue:"
    )
    return VERIFY_PIN

async def verify_pin_for_send(
        update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    pin = update.message.text.strip()
    if not verify_pin(telegram_id, pin):
        increment_failed_attempts(telegram_id)
        remaining = 3 - get_failed_attempts(telegram_id)
        if remaining <= 0:
            await update.message.reply_text(
                "🔒 Account locked. Contact support."
            )
        else:
            await update.message.reply_text(
                f"❌ Wrong PIN. {remaining} attempt(s) left."
            )
        return ConversationHandler.END
    reset_failed_attempts(telegram_id)
    await update.message.reply_text(
        "✅ PIN verified.\n\n"
        "💸 How much do you want to send?\n\n"
        "Type amount in naira:\nExample: 50000"
    )
    return SEND_AMOUNT

async def get_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    if not amount_text.isdigit() or int(amount_text) < 500:
        await update.message.reply_text(
            "⚠️ Enter a valid amount (minimum ₦500):\n"
            "Example: 50000"
        )
        return SEND_AMOUNT
    context.user_data["naira_amount"] = int(amount_text)
    await update.message.reply_text(
        f"💵 Amount: ₦{int(amount_text):,}\n\n"
        f"👤 Who are you sending to?\n\n"
        f"Type recipient's name:\nExample: Mum"
    )
    return SEND_RECIPIENT

async def get_recipient(
        update: Update, context: ContextTypes.DEFAULT_TYPE):
    recipient = update.message.text.strip().title()
    context.user_data["recipient_name"] = recipient
    await update.message.reply_text(
        f"👤 Recipient: {recipient}\n\n"
        f"🏦 What is their bank name?\n\n"
        f"Example: Access Bank, GTBank, Opay, Kuda"
    )
    return SEND_BANK

async def get_bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bank = update.message.text.strip()
    bank_code = get_bank_code(bank)
    if bank_code == "000":
        await update.message.reply_text(
            f"⚠️ Bank not recognized.\n\n"
            f"Please enter a valid Nigerian bank:\n"
            f"Access Bank, GTBank, Zenith Bank, "
            f"First Bank, UBA, Opay, Kuda, PalmPay"
        )
        return SEND_BANK
    context.user_data["recipient_bank"] = bank.title()
    await update.message.reply_text(
        f"🏦 Bank: {bank.title()}\n\n"
        f"🔢 Enter their 10-digit account number:"
    )
    return SEND_ACCOUNT

async def get_account(
        update: Update, context: ContextTypes.DEFAULT_TYPE):
    account = update.message.text.strip()
    if not account.isdigit() or len(account) != 10:
        await update.message.reply_text(
            "⚠️ Must be exactly 10 digits.\n\n"
            "Enter account number again:"
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
        f"📋 Confirm your transfer:\n\n"
        f"Recipient: {recipient}\n"
        f"Bank: {bank}\n"
        f"Account: {account}\n\n"
        f"Amount: ₦{naira_amount:,}\n"
        f"Fee: ₦{fee:,}\n"
        f"Total: ₦{total:,}\n"
        f"USDC Value: ${usdc_amount}\n\n"
        f"Money goes directly to their bank account.\n\n"
        f"Type YES to confirm or NO to cancel:"
    )
    return SEND_CONFIRM

async def confirm_send(
        update: Update, context: ContextTypes.DEFAULT_TYPE):
    response = update.message.text.strip().upper()
    if response == "NO":
        await update.message.reply_text(
            "❌ Cancelled. Type /send to start again."
        )
        return ConversationHandler.END
    if response != "YES":
        await update.message.reply_text(
            "Type YES to confirm or NO to cancel:"
        )
        return SEND_CONFIRM
    naira_amount = context.user_data["naira_amount"]
    recipient = context.user_data["recipient_name"]
    bank = context.user_data["recipient_bank"]
    account = context.user_data["recipient_account"]
    usdc_amount = round(naira_amount / NAIRA_TO_USD, 2)
    transaction_id = generate_transaction_id()
    sender_id = update.effective_user.id
    await update.message.reply_text(
        "⏳ Processing your transfer via Paystack...\n\n"
        "Please wait a moment."
    )
    result = simulate_paystack_transfer(
        recipient, bank, account, naira_amount
    )
    if result["status"] == "success":
        save_transaction(
            sender_id, recipient, bank, account,
            naira_amount, usdc_amount,
            result["reference"], transaction_id
        )
        await update.message.reply_text(
            f"✅ Transfer Successful!\n\n"
            f"₦{naira_amount:,} sent directly to:\n\n"
            f"Recipient: {recipient}\n"
            f"Bank: {bank}\n"
            f"Account: {account}\n\n"
            f"Paystack Reference:\n"
            f"`{result['reference']}`\n\n"
            f"Transaction ID:\n"
            f"`{transaction_id}`\n\n"
            f"💡 {recipient} will receive a bank "
            f"alert shortly.\n\n"
            f"Powered by Paystack + Solana",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "❌ Transfer failed. Please try again.\n\n"
            "Type /send to start again."
        )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Cancelled. Type /start to begin again."
    )
    return ConversationHandler.END

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text(
            "⚠️ Type /start to create an account."
        )
        return
    wallet_address = get_wallet_address(telegram_id)
    await update.message.reply_text(
        "⏳ Checking your balance on Solana..."
    )
    usdc_balance = get_usdc_balance(wallet_address)
    await update.message.reply_text(
        f"💰 USDC Balance: ${usdc_balance:.2f}\n\n"
        f"Wallet:\n`{wallet_address}`\n\n"
        f"Type /topup to add funds.",
        parse_mode="Markdown"
    )

async def help_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 How NairaLink Works\n\n"
        "1️⃣ Create account with /start\n"
        "2️⃣ Type /topup to fund with GBP/USD/EUR\n"
        "3️⃣ Pay with your card via Transak\n"
        "4️⃣ USDC lands in your Solana wallet\n"
        "5️⃣ Type /send — enter recipient details\n"
        "6️⃣ Money goes directly to their bank\n\n"
        "💡 Powered by Transak + Solana + Paystack\n"
        "Fees under 1 percent. Arrives in seconds."
    )

async def fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    wallet_address = get_wallet_address(telegram_id)
    if not wallet_address:
        await update.message.reply_text(
            "⚠️ Type /start to create an account."
        )
        return
    await update.message.reply_text(
        f"💳 Fund Your Wallet\n\n"
        f"Type /topup to fund with GBP, USD or EUR\n\n"
        f"Or send USDC directly to:\n`{wallet_address}`\n\n"
        f"Type /balance to check your balance.",
        parse_mode="Markdown"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    import sqlite3
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    conn.commit()
    conn.close()
    await update.message.reply_text(
        "🗑️ Account reset. Type /start to create a new one."
    )

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
                filters.TEXT & ~filters.COMMAND, get_amount
            )],
            SEND_RECIPIENT: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, get_recipient
            )],
            SEND_BANK: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, get_bank
            )],
            SEND_ACCOUNT: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, get_account
            )],
            SEND_CONFIRM: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, confirm_send
            )],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    topup_handler = ConversationHandler(
        entry_points=[CommandHandler("topup", topup)],
        states={
            TOPUP_CURRENCY: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, topup_currency
            )],
            TOPUP_AMOUNT: [MessageHandler(
                filters.TEXT & ~filters.COMMAND, topup_amount
            )],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(registration_handler)
    app.add_handler(send_handler)
    app.add_handler(topup_handler)
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
