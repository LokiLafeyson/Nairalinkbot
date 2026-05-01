import os
import json
import hmac
import hashlib
import threading
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
)
from dotenv import load_dotenv
from helpers import (
    init_db, get_user_by_wallet, update_user_balance, NAIRA_TO_USD
)
from commands import (
    balance, history, wallet_command, fund,
    help_command, topup, topup_currency, topup_amount,
)
from handlers import (
    start, set_pin, confirm_pin,
    send, verify_pin_for_send, get_amount,
    get_bank, get_account,
    send_confirm_yes, send_confirm_no, cancel,
    topup_confirm_callback, topup_cancel_callback,
    button_callback,
    SET_PIN, CONFIRM_PIN, VERIFY_PIN,
    SEND_AMOUNT, SEND_BANK, SEND_ACCOUNT, SEND_CONFIRM,
    TOPUP_CURRENCY, TOPUP_AMOUNT
)
from admin import add_funds, get_balance_admin, list_users, cmd_check_balance

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
MOONPAY_WEBHOOK_SECRET = os.getenv("MOONPAY_WEBHOOK_SECRET", "")


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
                MOONPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256
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
                        wallet       = txn.get("walletAddress")
                        amount       = float(txn.get("quoteCurrencyAmount", 0))
                        naira_amount = int(amount * NAIRA_TO_USD)
                        user = get_user_by_wallet(wallet)
                        if user:
                            update_user_balance(user[0], naira_amount, "add")
                            print(f"[Webhook] ₦{naira_amount:,} credited to {user[0]}", flush=True)
            except Exception as e:
                print(f"[Webhook Error] {e}", flush=True)
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
    HTTPServer(("0.0.0.0", port), PingHandler).serve_forever()


def keep_alive():
    threading.Thread(target=run_server, daemon=True).start()


# ─── App Entry Point ──────────────────────────────────────────────────────────

def main():
    init_db()
    keep_alive()
    print("Starting NairaLink bot...", flush=True)

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    registration_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SET_PIN:     [MessageHandler(filters.TEXT & ~filters.COMMAND, set_pin)],
            CONFIRM_PIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_pin)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("start",   start),
            CommandHandler("history", history),
            CommandHandler("balance", balance),
            CommandHandler("send",    send),
            CommandHandler("topup",   topup),
        ],
        allow_reentry=True,
    )

    send_handler = ConversationHandler(
        entry_points=[CommandHandler("send", send)],
        states={
            VERIFY_PIN:  [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_pin_for_send)],
            SEND_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_amount)],
            SEND_BANK:   [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bank)],
            SEND_ACCOUNT:[MessageHandler(filters.TEXT & ~filters.COMMAND, get_account)],
            SEND_CONFIRM:[
                CallbackQueryHandler(send_confirm_yes, pattern="^send_confirm_yes$"),
                CallbackQueryHandler(send_confirm_no,  pattern="^send_confirm_no$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel",  cancel),
            CommandHandler("history", history),
            CommandHandler("balance", balance),
            CommandHandler("topup",   topup),
            CommandHandler("start",   start),
            CallbackQueryHandler(send_confirm_no, pattern="^send_confirm_no$"),
        ],
        allow_reentry=True,
    )

    topup_handler = ConversationHandler(
        entry_points=[CommandHandler("topup", topup)],
        states={
            TOPUP_CURRENCY: [
                CallbackQueryHandler(topup_currency, pattern="^topup_cur_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, topup_currency),
            ],
            TOPUP_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, topup_amount),
                CallbackQueryHandler(topup_confirm_callback, pattern="^topup_confirm_"),
                CallbackQueryHandler(topup_cancel_callback,  pattern="^topup_cancel_"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel",  cancel),
            CommandHandler("history", history),
            CommandHandler("balance", balance),
            CommandHandler("send",    send),
            CommandHandler("start",   start),
            CallbackQueryHandler(topup_cancel_callback, pattern="^topup_cancel_"),
        ],
        allow_reentry=True,
    )

    # Register standalone commands FIRST so they are never swallowed
    # by ConversationHandlers regardless of active state
    app.add_handler(CommandHandler("balance",       balance))
    app.add_handler(CommandHandler("history",       history))
    app.add_handler(CommandHandler("help",          help_command))
    app.add_handler(CommandHandler("fund",          fund))
    app.add_handler(CommandHandler("wallet",        wallet_command))
    app.add_handler(CommandHandler("add_funds",     add_funds))
    app.add_handler(CommandHandler("get_balance",   get_balance_admin))
    app.add_handler(CommandHandler("list_users",    list_users))
    app.add_handler(CommandHandler("check_balance", cmd_check_balance))

    # Conversation handlers after standalone commands
    app.add_handler(registration_handler)
    app.add_handler(send_handler)
    app.add_handler(topup_handler)
    app.add_handler(CallbackQueryHandler(button_callback))

    print("Bot polling started...", flush=True)
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Fatal error: {e}", flush=True)
        sys.exit(1)
