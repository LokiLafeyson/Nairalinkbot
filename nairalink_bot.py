import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes
)
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ---- KEEP ALIVE SERVER ----
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"NairaLink is alive")

    def log_message(self, format, *args):
        pass  # silences server logs

def run_server():
    server = HTTPServer(("0.0.0.0", 8000), PingHandler)
    server.serve_forever()

def keep_alive():
    thread = threading.Thread(target=run_server)
    thread.daemon = True
    thread.start()

# ---- BOT COMMANDS ----

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Welcome to NairaLink, {user_name}!\n\n"
        f"Send money home instantly and cheaply — "
        f"your family receives naira cash, no bank account needed.\n\n"
        f"What you can do:\n"
        f"💸 /send — Send money home\n"
        f"💰 /balance — Check your balance\n"
        f"📖 /help — How NairaLink works\n\n"
        f"Type /help to get started."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 How NairaLink Works\n\n"
        "1️⃣ Fund your NairaLink wallet with USDC\n"
        "2️⃣ Type a command like:\n"
        "   send 50000 to Mum\n"
        "3️⃣ We convert and send instantly on Solana\n"
        "4️⃣ Recipient gets a cash pickup code\n"
        "5️⃣ They redeem at any OPay or PalmPay agent\n\n"
        "💡 Fees under 1 percent. Arrives in seconds.\n\n"
        "Ready? Type /send to begin."
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 Your NairaLink Balance\n\n"
        "USDC Balance: $0.00\n\n"
        "To fund your wallet, type /fund"
    )

async def send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💸 Send Money Home\n\n"
        "Type your instruction like this:\n\n"
        "send 50000 to Mum\n\n"
        "Replace 50000 with the naira amount you want to send."
    )

async def fund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 Fund Your Wallet\n\n"
        "To fund your NairaLink wallet:\n\n"
        "1️⃣ Buy USDC on Quidax or Yellow Card\n"
        "2️⃣ Send it to your NairaLink wallet address\n"
        "3️⃣ Your balance updates automatically\n\n"
        "Type /balance to check your balance."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower().strip()

    if text.startswith("send"):
        parts = text.split()
        if len(parts) >= 4 and parts[2] == "to":
            try:
                amount = int(parts[1])
                recipient = " ".join(parts[3:]).title()
                await update.message.reply_text(
                    f"✅ Transfer Initiated\n\n"
                    f"Amount: ₦{amount:,}\n"
                    f"Recipient: {recipient}\n"
                    f"Status: Processing on Solana...\n\n"
                    f"⏳ Your recipient will receive a cash pickup code shortly.\n\n"
                    f"Transaction ID: TXN{amount}SOL001"
                )
            except ValueError:
                await update.message.reply_text(
                    "⚠️ I could not read that amount.\n\n"
                    "Please try:\nsend 50000 to Mum"
                )
        else:
            await update.message.reply_text(
                "⚠️ Please use this format:\n\n"
                "send 50000 to Mum"
            )
    else:
        await update.message.reply_text(
            "I did not understand that.\n\n"
            "Type /help to see what I can do."
        )

# ---- MAIN ----
def main():
    keep_alive()  # starts the web server in background

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("send", send))
    app.add_handler(CommandHandler("fund", fund))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("NairaLink bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
