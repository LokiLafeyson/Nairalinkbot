import sqlite3
import hashlib
import hmac
import random
import string
import urllib.parse
import base64
import os
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.api import Client

SOLANA_CLIENT = Client(
    "https://api.devnet.solana.com",
    timeout=10
)

USDC_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"

# ─── Fee Configuration ────────────────────────────────────────────────────────
# All fees as percentages (e.g. 1.5 = 1.5%)
# Change values here — they propagate everywhere automatically

TRANSAK_FEE_PERCENT   = 1.5   # Transak onramp charge
PAYSTACK_FEE_PERCENT  = 1.5   # Paystack disbursement charge
PLATFORM_FEE_PERCENT  = 0.5   # NairaLink margin
TOTAL_FEE_PERCENT     = TRANSAK_FEE_PERCENT + PAYSTACK_FEE_PERCENT + PLATFORM_FEE_PERCENT  # = 3.5%

# Fallback exchange rate used only when API is unavailable
NAIRA_TO_USD = 1650


# ─── Database ────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            first_name TEXT,
            pin_hash TEXT,
            wallet_address TEXT,
            wallet_private_key TEXT,
            failed_attempts INTEGER DEFAULT 0,
            locked_until INTEGER DEFAULT 0,
            naira_balance INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Safe migration for older DBs missing naira_balance
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN naira_balance INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            recipient_name TEXT,
            recipient_bank TEXT,
            recipient_account TEXT,
            naira_amount INTEGER,
            usdc_amount REAL,
            redemption_code TEXT,
            transaction_id TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_topups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            naira_amount INTEGER,
            currency TEXT,
            foreign_amount REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


# ─── PIN / Auth ───────────────────────────────────────────────────────────────

def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()


def verify_pin(telegram_id: int, pin: str) -> bool:
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute("SELECT pin_hash FROM users WHERE telegram_id = ?", (telegram_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] == hash_pin(pin) if result else False


def increment_failed_attempts(telegram_id: int):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET failed_attempts = failed_attempts + 1 WHERE telegram_id = ?",
        (telegram_id,)
    )
    conn.commit()
    conn.close()


def reset_failed_attempts(telegram_id: int):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET failed_attempts = 0 WHERE telegram_id = ?",
        (telegram_id,)
    )
    conn.commit()
    conn.close()


def get_failed_attempts(telegram_id: int) -> int:
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute("SELECT failed_attempts FROM users WHERE telegram_id = ?", (telegram_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0


# ─── User CRUD ────────────────────────────────────────────────────────────────

def get_user(telegram_id: int):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cursor.fetchone()
    conn.close()
    return user


def get_user_by_wallet(wallet_address: str):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE wallet_address = ?", (wallet_address,))
    result = cursor.fetchone()
    conn.close()
    return result


def create_user(telegram_id: int, first_name: str, pin: str) -> str:
    keypair = Keypair()
    wallet_address = str(keypair.pubkey())
    wallet_private_key = str(keypair)
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO users
        (telegram_id, first_name, pin_hash, wallet_address, wallet_private_key)
        VALUES (?, ?, ?, ?, ?)""",
        (telegram_id, first_name, hash_pin(pin), wallet_address, wallet_private_key)
    )
    conn.commit()
    conn.close()
    return wallet_address


def get_wallet_address(telegram_id: int):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute("SELECT wallet_address FROM users WHERE telegram_id = ?", (telegram_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


def get_user_balance(telegram_id: int) -> int:
    conn = sqlite3.connect("nairalink.db")
    c = conn.cursor()
    c.execute("SELECT naira_balance FROM users WHERE telegram_id = ?", (telegram_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0


def update_user_balance(telegram_id: int, amount: int, mode: str = "add") -> bool:
    current = get_user_balance(telegram_id)
    if mode == "add":
        new_balance = current + amount
    elif mode == "deduct":
        if current < amount:
            return False
        new_balance = current - amount
    else:
        return False
    conn = sqlite3.connect("nairalink.db")
    c = conn.cursor()
    c.execute(
        "UPDATE users SET naira_balance = ? WHERE telegram_id = ?",
        (new_balance, telegram_id)
    )
    conn.commit()
    conn.close()
    return True


# ─── Pending Topups ───────────────────────────────────────────────────────────

def save_pending_topup(telegram_id: int, naira_amount: int, currency: str, foreign_amount: float) -> int:
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO pending_topups (telegram_id, naira_amount, currency, foreign_amount)
           VALUES (?, ?, ?, ?)""",
        (telegram_id, naira_amount, currency, foreign_amount)
    )
    row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_pending_topup(topup_id: int):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pending_topups WHERE id = ?", (topup_id,))
    result = cursor.fetchone()
    conn.close()
    return result


def delete_pending_topup(topup_id: int):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pending_topups WHERE id = ?", (topup_id,))
    conn.commit()
    conn.close()


# ─── Transactions ─────────────────────────────────────────────────────────────

def generate_redemption_code() -> str:
    letters = ''.join(random.choices(string.ascii_uppercase, k=4))
    numbers = ''.join(random.choices(string.digits, k=4))
    return f"NL-{letters}-{numbers}"


def generate_transaction_id() -> str:
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=44))


def save_transaction(sender_id, recipient_name, recipient_bank,
                     recipient_account, naira_amount, usdc_amount,
                     redemption_code, transaction_id):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO transactions
        (sender_id, recipient_name, recipient_bank, recipient_account,
        naira_amount, usdc_amount, redemption_code, transaction_id, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed')""",
        (sender_id, recipient_name, recipient_bank, recipient_account,
         naira_amount, usdc_amount, redemption_code, transaction_id)
    )
    conn.commit()
    conn.close()


def get_transaction_by_code(code: str):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM transactions WHERE redemption_code = ?",
        (code.upper(),)
    )
    result = cursor.fetchone()
    conn.close()
    return result


def mark_redeemed(code: str):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE transactions SET status = 'redeemed' WHERE redemption_code = ?",
        (code.upper(),)
    )
    conn.commit()
    conn.close()


def get_user_transactions(telegram_id: int, limit: int = 5):
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


# ─── Solana / USDC ────────────────────────────────────────────────────────────

def get_usdc_balance(wallet_address: str) -> float:
    try:
        pubkey = Pubkey.from_string(wallet_address)
        from solana.rpc.types import TokenAccountOpts
        opts = TokenAccountOpts(mint=Pubkey.from_string(USDC_MINT))
        response = SOLANA_CLIENT.get_token_accounts_by_owner(pubkey, opts)
        if response.value:
            amount = response.value[0].account.data.parsed["info"]["tokenAmount"]["uiAmount"]
            return amount if amount else 0.0
        return 0.0
    except Exception:
        return 0.0


# ─── Exchange Rates ───────────────────────────────────────────────────────────

def get_exchange_rate(currency: str = "GBP") -> dict:
    import requests
    try:
        api_key = os.getenv("EXCHANGE_RATE_API_KEY")
        response = requests.get(
            f"https://v6.exchangerate-api.com/v6/{api_key}/latest/{currency}",
            timeout=8
        )
        data = response.json()
        if data["result"] == "success":
            ngn_rate = data["conversion_rates"]["NGN"]
            usd_rate = data["conversion_rates"]["USD"]
            return {
                "ngn_per_foreign": ngn_rate,
                "foreign_per_usdc": usd_rate,
                "ngn_per_usdc": ngn_rate / usd_rate,
                "currency": currency
            }
    except Exception:
        pass
    fallback = {"GBP": 2450, "USD": 1600, "EUR": 1750, "CAD": 1180}
    rate = fallback.get(currency, 1600)
    return {
        "ngn_per_foreign": rate,
        "foreign_per_usdc": 1.0,
        "ngn_per_usdc": NAIRA_TO_USD,
        "currency": currency
    }


def calculate_send_cost(naira_amount: int, currency: str = "GBP") -> dict:
    """
    Calculate full transfer cost broken down by fee component.
    Fee is applied to the naira amount, then converted to foreign currency.
    """
    rates = get_exchange_rate(currency)
    ngn_per_foreign = rates["ngn_per_foreign"]

    # Fee breakdown (applied to naira amount)
    transak_fee_naira  = round(naira_amount * TRANSAK_FEE_PERCENT / 100)
    paystack_fee_naira = round(naira_amount * PAYSTACK_FEE_PERCENT / 100)
    platform_fee_naira = round(naira_amount * PLATFORM_FEE_PERCENT / 100)
    total_fee_naira    = transak_fee_naira + paystack_fee_naira + platform_fee_naira
    total_naira        = naira_amount + total_fee_naira

    # Foreign currency equivalents
    foreign_amount     = round(naira_amount / ngn_per_foreign, 2)
    total_fee_foreign  = round(total_fee_naira / ngn_per_foreign, 2)
    total_foreign      = round(total_naira / ngn_per_foreign, 2)

    usdc_amount        = round(naira_amount / rates["ngn_per_usdc"], 2)

    return {
        "naira_amount":        naira_amount,
        "transak_fee_naira":   transak_fee_naira,
        "paystack_fee_naira":  paystack_fee_naira,
        "platform_fee_naira":  platform_fee_naira,
        "total_fee_naira":     total_fee_naira,
        "total_naira":         total_naira,
        "foreign_amount":      foreign_amount,
        "total_fee_foreign":   total_fee_foreign,
        "total_foreign":       total_foreign,
        "usdc_amount":         usdc_amount,
        "currency":            currency,
        "rate":                ngn_per_foreign,
        "total_fee_percent":   TOTAL_FEE_PERCENT,
    }


# ─── Bank Codes ───────────────────────────────────────────────────────────────

def get_bank_code(bank_name: str) -> str:
    bank_codes = {
        "access bank": "044",
        "gtbank": "058",
        "gtb": "058",
        "guaranty trust bank": "058",
        "zenith bank": "057",
        "first bank": "011",
        "uba": "033",
        "united bank for africa": "033",
        "fidelity bank": "070",
        "union bank": "032",
        "sterling bank": "232",
        "keystone bank": "082",
        "polaris bank": "076",
        "stanbic ibtc": "039",
        "standard chartered": "068",
        "ecobank": "050",
        "heritage bank": "030",
        "providus bank": "101",
        "wema bank": "035",
        "opay": "999992",
        "palmpay": "999991",
        "kuda": "090267",
        "moniepoint": "090405",
        "carbon": "090175",
        "vfd": "090110",
    }
    return bank_codes.get(bank_name.lower().strip(), "000")


# ─── Payment Links ────────────────────────────────────────────────────────────

def generate_transak_link(api_key: str, amount: float, currency: str, wallet_address: str) -> str:
    params = {
        "apiKey": api_key,
        "cryptoCurrencyCode": "USDC",
        "network": "solana",
        "walletAddress": wallet_address,
        "fiatCurrency": currency,
        "fiatAmount": str(amount),
        "disableWalletAddressForm": "true",
        "hideMenu": "true",
        "themeColor": "00A651",
    }
    query = urllib.parse.urlencode(params)
    return f"https://global-stg.transak.com?{query}"


def generate_moonpay_url(wallet_address: str, currency_code: str = "ngn",
                          base_currency: str = "usdc_sol") -> str:
    """
    MoonPay onramp link. Currently used as fallback — Transak is primary.
    Kept for webhook compatibility.
    """
    public_key = os.getenv("MOONPAY_PUBLIC_KEY", "")
    secret_key = os.getenv("MOONPAY_SECRET_KEY", "")

    params = {
        "apiKey": public_key,
        "currencyCode": base_currency,
        "baseCurrencyCode": currency_code,
        "walletAddress": wallet_address,
    }

    query_string = urllib.parse.urlencode(params)

    signature = hmac.new(
        secret_key.encode("utf-8"),
        f"?{query_string}".encode("utf-8"),
        hashlib.sha256
    ).digest()

    sig_b64 = base64.urlsafe_b64encode(signature).decode("utf-8").rstrip("=")
    return f"https://buy-sandbox.moonpay.com?{query_string}&signature={sig_b64}"
