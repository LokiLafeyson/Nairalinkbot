import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from helpers import (
    get_user, get_user_balance, update_user_balance,
    get_wallet_address, get_usdc_balance, get_user_transactions,
    generate_moonpay_url
)

TOPUP_CURRENCY, TOPUP_AMOUNT = 10, 11

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    naira_bal = get_user_balance(telegram_id)
    wallet = get_wallet_address(telegram_id)
    usdc_bal = get_usdc_balance(wallet) if wallet else 0
    await update.message.reply_text(
        f"💰 Your NairaLink Balance\n\n"
        f"🇳🇬 Naira balance (spendable): ₦{naira_bal:,}\n"
        f"💎 USDC on Solana: ${usdc_bal:.2f}\n\n"
        f"Wallet: `{wallet}`\n\n"
        f"Use /topup to add funds.",
        parse_mode="Markdown"
    )

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    txs = get_user_transactions(telegram_id, limit=5)
    if not txs:
        await update.message.reply_text("No transactions yet.")
        return
    msg = "📜 Last 5 transactions:\n\n"
    for tx in txs:
        recipient, bank, account, amount, txid, status, date = tx
        msg += f"• ₦{amount:,} to {recipient} ({bank})\n  {date[:10]}\n  Status: {status}\n\n"
    await update.message.reply_text(msg)

async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    wallet = get_wallet_address(telegram_id)
    await update.message.reply_text(
        f"👛 Your Solana wallet:\n`{wallet}`\n\n"
        f"Send USDC here to fund your account.",
        parse_mode="Markdown"
    )

async def fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    wallet = get_wallet_address(telegram_id)
    if not wallet:
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    await update.message.reply_text(
        f"💳 Fund Your Wallet\n\n"
        f"To add funds, use /topup and click the button.\n\n"
        f"Or send USDC directly to:\n`{wallet}`\n\n"
        f"Type /balance to check balance.",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 How NairaLink Works\n\n"
        "1️⃣ Create account with /start\n"
        "2️⃣ Add funds with /topup (click the button)\n"
        "3️⃣ Type /send — enter recipient details\n"
        "4️⃣ Money goes directly to Nigerian bank via Paystack\n\n"
        "💡 Fees under 1 percent. Arrives in seconds.\n\n"
        "Commands: /start, /topup, /send, /balance, /history, /wallet, /help"
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import sqlite3
    telegram_id = update.effective_user.id
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text("🗑️ Account reset. Type /start to create a new one.")

async def topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text("⚠️ Type /start to create an account first.")
        return ConversationHandler.END
    await update.message.reply_text(
        "💱 Top Up Your Wallet\n\n"
        "Please enter the currency you are sending from (e.g., GBP, USD, EUR, CAD):"
    )
    return TOPUP_CURRENCY

async def topup_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    currency = update.message.text.strip().upper()
    supported = ["GBP", "USD", "EUR", "CAD"]
    if currency not in supported:
        await update.message.reply_text(
            "⚠️ Unsupported currency. Please type one of: GBP, USD, EUR, CAD"
        )
        return TOPUP_CURRENCY
    context.user_data["topup_currency"] = currency
    await update.message.reply_text(
        f"💱 Currency: {currency}\n\n"
        f"How much {currency} do you want to convert?\n"
        f"Type the amount (minimum 5):"
    )
    return TOPUP_AMOUNT

async def topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    try:
        amount = float(amount_text)
        if amount < 5:
            await update.message.reply_text("⚠️ Minimum amount is 5. Please enter a higher amount.")
            return TOPUP_AMOUNT
    except ValueError:
        await update.message.reply_text("⚠️ Invalid amount. Please enter a number (e.g., 50).")
        return TOPUP_AMOUNT

    currency = context.user_data["topup_currency"]
    loading_msg = await update.message.reply_text("⏳ Getting live exchange rate...")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"https://api.exchangerate-api.com/v4/latest/{currency}")
            data = resp.json()
            rate = data["rates"]["NGN"]
    except Exception:
        fallback_rates = {"GBP": 2450, "USD": 1600, "EUR": 1750, "CAD": 1180}
        rate = fallback_rates.get(currency, 1600)

    naira_equivalent = int(amount * rate)
    fee = round(amount * 0.008, 2)
    total_deducted = round(amount + fee, 2)
    symbol = {"GBP": "£", "USD": "$", "EUR": "€", "CAD": "CA$"}.get(currency, "$")

    # Get user's wallet and generate MoonPay link
    telegram_id = update.effective_user.id
    wallet = get_wallet_address(telegram_id)
    moonpay_url = generate_moonpay_url(wallet)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay Now via MoonPay", url=moonpay_url)]
    ])

    await loading_msg.edit_text(
        f"💱 Exchange Rate\n\n"
        f"You send: {symbol}{amount} {currency}\n"
        f"Fee: {symbol}{fee} (0.8%)\n"
        f"Total charged: {symbol}{total_deducted} {currency}\n\n"
        f"You will receive: ₦{naira_equivalent:,}\n"
        f"Rate: 1 {currency} = ₦{rate:,.0f}\n\n"
        f"Click below to complete payment via MoonPay.\n"
        f"Your wallet will be credited automatically once payment clears.",
        reply_markup=keyboard
    )
    return ConversationHandler.END
