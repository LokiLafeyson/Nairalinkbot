import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from helpers import (
    get_user, get_user_balance, update_user_balance,
    get_wallet_address, get_usdc_balance, get_user_transactions,
    generate_moonpay_url, save_pending_topup
)

TOPUP_CURRENCY, TOPUP_AMOUNT = 10, 11

CURRENCY_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€", "CAD": "CA$"}
SUPPORTED_CURRENCIES = list(CURRENCY_SYMBOLS.keys())
FALLBACK_RATES = {"GBP": 2450, "USD": 1600, "EUR": 1750, "CAD": 1180}


def get_main_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("💸 Send", callback_data="menu_send"),
            InlineKeyboardButton("📥 Receive", callback_data="menu_receive"),
        ],
        [
            InlineKeyboardButton("💰 Balance", callback_data="menu_balance"),
            InlineKeyboardButton("👛 Wallet", callback_data="menu_wallet"),
        ],
        [
            InlineKeyboardButton("📋 History", callback_data="menu_history"),
            InlineKeyboardButton("➕ Top Up", callback_data="menu_topup"),
        ],
        [
            InlineKeyboardButton("📖 Help", callback_data="menu_help"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ─── Commands ─────────────────────────────────────────────────────────────────

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    naira_bal = get_user_balance(telegram_id)
    wallet = get_wallet_address(telegram_id)
    usdc_bal = get_usdc_balance(wallet) if wallet else 0.0
    await update.message.reply_text(
        f"💰 *Your NairaLink Balance*\n\n"
        f"🇳🇬 Naira (spendable): ₦{naira_bal:,}\n"
        f"💎 USDC on Solana: ${usdc_bal:.2f}\n\n"
        f"Wallet: `{wallet}`",
        parse_mode="Markdown",
        reply_markup=get_main_menu()
    )


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    txs = get_user_transactions(telegram_id, limit=5)
    if not txs:
        await update.message.reply_text(
            "No transactions yet.\n\nTop up with /topup then send with /send.",
            reply_markup=get_main_menu()
        )
        return
    msg = "📜 *Last 5 Transactions*\n\n"
    for tx in txs:
        recipient, bank, account, amount, txid, status, date = tx
        msg += (
            f"• ₦{amount:,} → {recipient}\n"
            f"  {bank} · {account}\n"
            f"  {date[:10]} · {status}\n\n"
        )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_main_menu())


async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    wallet = get_wallet_address(telegram_id)
    await update.message.reply_text(
        f"👛 *Your Solana Wallet*\n\n`{wallet}`\n\n"
        f"Send USDC (Solana network) here to fund your account.",
        parse_mode="Markdown",
        reply_markup=get_main_menu()
    )


async def fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    wallet = get_wallet_address(telegram_id)
    if not wallet:
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    await update.message.reply_text(
        f"💳 *Fund Your Wallet*\n\n"
        f"Use /topup to add funds via MoonPay.\n\n"
        f"Or send USDC directly to:\n`{wallet}`\n\n"
        f"Check balance with /balance.",
        parse_mode="Markdown",
        reply_markup=get_main_menu()
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *How NairaLink Works*\n\n"
        "1️⃣ Create account — /start\n"
        "2️⃣ Add funds — /topup\n"
        "3️⃣ Send money — /send\n"
        "4️⃣ Recipient gets naira in their bank account\n\n"
        "💡 Fees under 1%. Powered by Paystack + Solana.\n\n"
        "Commands: /start /topup /send /balance /history /wallet",
        parse_mode="Markdown",
        reply_markup=get_main_menu()
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import sqlite3
    telegram_id = update.effective_user.id
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()
    await update.message.reply_text("🗑️ Account deleted. Type /start to create a new one.")


# ─── Topup Flow ───────────────────────────────────────────────────────────────

async def topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text("⚠️ Type /start to create an account first.")
        return ConversationHandler.END
    await update.message.reply_text(
        "💱 *Top Up Your Wallet*\n\n"
        "Enter the currency you're paying from:\n\n"
        "GBP · USD · EUR · CAD",
        parse_mode="Markdown"
    )
    return TOPUP_CURRENCY


async def topup_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    currency = update.message.text.strip().upper()
    if currency not in SUPPORTED_CURRENCIES:
        await update.message.reply_text(
            "⚠️ Unsupported currency.\n\nType one of: GBP, USD, EUR, CAD"
        )
        return TOPUP_CURRENCY
    context.user_data["topup_currency"] = currency
    symbol = CURRENCY_SYMBOLS[currency]
    await update.message.reply_text(
        f"💱 Currency: *{currency}*\n\n"
        f"How much {currency} do you want to top up?\n"
        f"Minimum: {symbol}5\n\n"
        f"Type the amount:",
        parse_mode="Markdown"
    )
    return TOPUP_AMOUNT


async def topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text.strip()
    try:
        amount = float(amount_text)
        if amount < 5:
            await update.message.reply_text("⚠️ Minimum is 5. Enter a higher amount:")
            return TOPUP_AMOUNT
    except ValueError:
        await update.message.reply_text("⚠️ Invalid amount. Enter a number e.g. 50:")
        return TOPUP_AMOUNT

    currency = context.user_data["topup_currency"]
    symbol = CURRENCY_SYMBOLS[currency]
    loading_msg = await update.message.reply_text("⏳ Fetching live exchange rate...")

    # Fetch live rate
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.exchangerate-api.com/v4/latest/{currency}"
            )
            data = resp.json()
            rate = data["rates"]["NGN"]
    except Exception:
        rate = FALLBACK_RATES.get(currency, 1600)

    naira_equivalent = int(amount * rate)
    fee = round(amount * 0.008, 2)
    total_charged = round(amount + fee, 2)

    telegram_id = update.effective_user.id
    wallet = get_wallet_address(telegram_id)
    moonpay_url = generate_moonpay_url(wallet)

    # Save pending topup — id encoded into callback so no session state needed
    topup_id = save_pending_topup(telegram_id, naira_equivalent, currency, amount)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Open MoonPay", url=moonpay_url)],
        [InlineKeyboardButton(
            "✅ I've Paid — Credit My Wallet",
            callback_data=f"topup_confirm_{topup_id}_{telegram_id}_{naira_equivalent}"
        )],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"topup_cancel_{topup_id}")]
    ])

    await loading_msg.edit_text(
        f"💱 *Top Up Summary*\n\n"
        f"You pay: {symbol}{total_charged} {currency}\n"
        f"  — Amount: {symbol}{amount}\n"
        f"  — Fee (0.8%): {symbol}{fee}\n\n"
        f"You receive: *₦{naira_equivalent:,}*\n"
        f"Rate: 1 {currency} = ₦{rate:,.0f}\n\n"
        f"1️⃣ Tap *Open MoonPay* and complete the payment\n"
        f"2️⃣ Tap *I've Paid* — your balance is credited instantly\n\n"
        f"_For testing: tap I've Paid without completing MoonPay._",
        parse_mode="Markdown",
        reply_markup=keyboard
    )
    return ConversationHandler.END
