from telegram import Update
from telegram.ext import ContextTypes
from helpers import get_user, get_wallet_address, get_user_balance, get_user_transactions

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    naira_bal = get_user_balance(telegram_id)
    wallet = get_wallet_address(telegram_id)
    await update.message.reply_text(
        f"💰 Your NairaLink Balance\n\n"
        f"🇳🇬 Naira balance: ₦{naira_bal:,}\n"
        f"💎 Solana wallet: `{wallet}`\n\n"
        f"To add funds (demo), ask admin to use /add_funds.",
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
    await update.message.reply_text(f"👛 Your Solana wallet:\n`{wallet}`\n\nSend USDC here to fund your account.", parse_mode="Markdown")

async def fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    wallet = get_wallet_address(telegram_id)
    if not wallet:
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    await update.message.reply_text(
        f"💳 Fund Your Wallet\n\n"
        f"To add funds, contact admin for demo top‑up using `/add_funds`.\n\n"
        f"Or send USDC directly to:\n`{wallet}`\n\n"
        f"Type /balance to check balance.",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 How NairaLink Works\n\n"
        "1️⃣ Create account with /start\n"
        "2️⃣ Admin adds demo funds with /add_funds\n"
        "3️⃣ Type /send — enter recipient details\n"
        "4️⃣ Money goes directly to Nigerian bank via Paystack\n\n"
        "💡 Fees under 1 percent. Arrives in seconds.\n\n"
        "Commands: /start, /send, /balance, /history, /wallet, /help"
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

# Topup conversation handlers (simplified – just show Transak link)
async def topup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.effective_user.id
    if not get_user(telegram_id):
        await update.message.reply_text("⚠️ Type /start to create an account.")
        return
    await update.message.reply_text(
        "💱 Top Up Your Wallet\n\n"
        "For demo purposes, please ask admin to use `/add_funds`.\n\n"
        "In production, you would pay via Transak or Coinbase Onramp."
    )
    return -1  # end conversation

# Dummy functions to satisfy imports in main.py (they won't be used if topup is simplified)
async def topup_currency(update, context):
    pass
async def topup_amount(update, context):
    pass
