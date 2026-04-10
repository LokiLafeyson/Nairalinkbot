import os
import sqlite3
from telegram import Update
from telegram.ext import ContextTypes
from helpers import get_user, update_user_balance, get_user_balance

ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

async def add_funds(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Unauthorized")
        return
    try:
        amount = int(context.args[0])
        if amount <= 0:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /add_funds <amount in naira> [optional user_id]")
        return
    target_id = update.effective_user.id
    if len(context.args) > 1:
        try:
            target_id = int(context.args[1])
        except ValueError:
            await update.message.reply_text("Invalid user ID, using yours.")
    if not get_user(target_id):
        await update.message.reply_text("User not found. They need to /start first.")
        return
    update_user_balance(target_id, amount, "add")
    new_bal = get_user_balance(target_id)
    await update.message.reply_text(f"✅ Added ₦{amount:,} to user {target_id}\nNew balance: ₦{new_bal:,}")

async def get_balance_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Unauthorized")
        return
    target_id = update.effective_user.id
    if context.args:
        try:
            target_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Invalid user ID.")
            return
    if not get_user(target_id):
        await update.message.reply_text("User not found.")
        return
    bal = get_user_balance(target_id)
    await update.message.reply_text(f"💰 User {target_id} Naira balance: ₦{bal:,}")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Unauthorized")
        return
    conn = sqlite3.connect("nairalink.db")
    c = conn.cursor()
    c.execute("SELECT telegram_id, first_name, naira_balance FROM users LIMIT 20")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await update.message.reply_text("No users found.")
        return
    msg = "📋 Users:\n"
    for tid, name, bal in rows:
        msg += f"• {name} (ID: {tid}) – ₦{bal:,}\n"
    await update.message.reply_text(msg)
