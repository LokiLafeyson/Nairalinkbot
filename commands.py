import os
import sqlite3
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from helpers import (
    get_user, get_wallet_address, get_usdc_balance,
    generate_transak_link, NAIRA_TO_USD
)


def get_user_transactions(telegram_id, limit=5):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        """SELECT recipient_name, recipient_bank,
        recipient_account, naira_amount, transaction_id,
        status, created_at
        FROM transactions
        WHERE sender_id = ?
        ORDER BY created_at DESC
        LIMIT ?""",
        (telegram_id, limit)
    )
    results = cursor.fetchall()
    conn.close()
    return results


async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    tables = cursor.fetchall()
    try:
        cursor.execute("SELECT COUNT(*) FROM transactions")
        count = cursor.fetchone()[0]
        cursor.execute(
            "SELECT sender_id FROM transactions LIMIT 3"
        )
        rows = cursor.fetchall()
    except Exception as e:
        count = f"Error: {e}"
        rows = []
    conn.close()
    await update.message.reply_text(
        f"🔍 Debug Info\n\n"
        f"Your ID: {telegram_id}\n"
        f"Tables: {tables}\n"
        f"Transaction count: {count}\n"
        f"Sender IDs found: {rows}"
    )


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


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text(
            "⚠️ Type /start to create an account."
        )
        return
    await update.message.reply_text(
        "⏳ Fetching your transaction history..."
    )
    transactions = get_user_transactions(telegram_id)
    if not transactions:
        await update.message.reply_text(
            "📋 No transactions yet.\n\n"
            "Type /send to make your first transfer."
        )
        return
    message = "📋 Your Last 5 Transactions\n\n"
    for i, txn in enumerate(transactions, 1):
        recipient_name = txn[0]
        recipient_bank = txn[1]
        recipient_account = txn[2]
        naira_amount = txn[3]
        transaction_id = txn[4]
        status = txn[5]
        created_at = txn[6]
        date = created_at[:10] if created_at else "Unknown"
        status_icon = "✅" if status == "completed" else "⏳"
        message += (
            f"{i}. {status_icon} ₦{naira_amount:,} → "
            f"{recipient_name}\n"
            f"   Bank: {recipient_bank}\n"
            f"   Account: {recipient_account}\n"
            f"   Date: {date}\n"
            f"   ID: {transaction_id[:12]}...\n\n"
        )
    await update.message.reply_text(message)


async def wallet_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def help_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 How NairaLink Works\n\n"
        "1️⃣ Create account with /start\n"
        "2️⃣ Type /topup to fund with GBP/USD/EUR\n"
        "3️⃣ Pay with your card via Transak\n"
        "4️⃣ USDC lands in your Solana wallet\n"
        "5️⃣ Type /send — enter recipient details\n"
        "6️⃣ Money goes directly to their bank\n"
        "7️⃣ Type /history to view past transfers\n\n"
        "💡 Powered by Transak + Solana + Paystack\n"
        "Fees under 1 percent. Arrives in seconds."
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
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


async def topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text(
            "⚠️ Type /start to create an account first."
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "💱 Top Up Your NairaLink Wallet\n\n"
        "What currency are you sending from?\n\n"
        "Type one of these:\n"
        "🇬🇧 GBP — British Pounds\n"
        "🇺🇸 USD — US Dollars\n"
        "🇪🇺 EUR — Euros\n"
        "🇨🇦 CAD — Canadian Dollars"
    )
    return 10


async def topup_currency(
        update: Update, context: ContextTypes.DEFAULT_TYPE):
    currency = update.message.text.strip().upper()
    supported = ["GBP", "USD", "EUR", "CAD"]
    if currency not in supported:
        await update.message.reply_text(
            "⚠️ Please type one of these:\n"
            "GBP, USD, EUR, or CAD"
        )
        return 10
    context.user_data["topup_currency"] = currency
    await update.message.reply_text(
        f"💱 Currency: {currency}\n\n"
        f"How much {currency} do you want to convert?\n\n"
        f"Type the amount:\nExample: 50"
    )
    return 11


async def topup_amount(
        update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    if not amount_text.replace(".", "").isdigit():
        await update.message.reply_text(
            "⚠️ Please enter a valid amount:\nExample: 50"
        )
        return 11
    amount = float(amount_text)
    if amount < 5:
        await update.message.reply_text(
            "⚠️ Minimum amount is 5.\n\n"
            "Please enter a higher amount:"
        )
        return 11
    currency = context.user_data["topup_currency"]
    telegram_id = update.effective_user.id
    wallet_address = get_wallet_address(telegram_id)
    loading_msg = await update.message.reply_text(
        "⏳ Getting live exchange rate..."
    )
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
        fallback_rates = {
            "GBP": 2050, "USD": 1620,
            "EUR": 1750, "CAD": 1190
        }
        rate = fallback_rates[currency]
    naira_equivalent = int(amount * rate)
    fee_foreign = round(amount * 0.008, 2)
    total_foreign = round(amount + fee_foreign, 2)
    usdc_amount = round(naira_equivalent / NAIRA_TO_USD, 2)
    currency_symbols = {
        "GBP": "£", "USD": "$", "EUR": "€", "CAD": "CA$"
    }
    symbol = currency_symbols[currency]
    transak_key = os.getenv("TRANSAK_API_KEY", "demo")
    payment_link = generate_transak_link(
        transak_key, amount, currency, wallet_address
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "💳 Pay Now via Transak", url=payment_link
        )]
    ])
    await loading_msg.edit_text(
        f"💱 Live Exchange Rate\n\n"
        f"You send: {symbol}{amount} {currency}\n"
        f"Fee: {symbol}{fee_foreign} (0.8%)\n"
        f"Total: {symbol}{total_foreign} {currency}\n\n"
        f"Recipient gets: ₦{naira_equivalent:,}\n"
        f"USDC Value: ${usdc_amount}\n"
        f"Rate: {symbol}1 = ₦{rate:,.0f}\n\n"
        f"After payment your wallet will be funded "
        f"with USDC automatically.\n\n"
        f"Then type /send to transfer to Nigeria.",
        reply_markup=keyboard
    )
    return ConversationHandler.END
