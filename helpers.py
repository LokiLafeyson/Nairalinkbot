import sqlite3
import hashlib
import random
import string
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.api import Client

SOLANA_CLIENT = Client(
    "https://api.devnet.solana.com",
    timeout=10
)

USDC_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
NAIRA_TO_USD = 1650

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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
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
    conn.commit()
    conn.close()

def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()

def get_user(telegram_id):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    user = cursor.fetchone()
    conn.close()
    return user

def create_user(telegram_id, first_name, pin):
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

def get_wallet_address(telegram_id):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT wallet_address FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def verify_pin(telegram_id, pin):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT pin_hash FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    result = cursor.fetchone()
    conn.close()
    if result:
        return result[0] == hash_pin(pin)
    return False

def increment_failed_attempts(telegram_id):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET failed_attempts = failed_attempts + 1 WHERE telegram_id = ?",
        (telegram_id,)
    )
    conn.commit()
    conn.close()

def reset_failed_attempts(telegram_id):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET failed_attempts = 0 WHERE telegram_id = ?",
        (telegram_id,)
    )
    conn.commit()
    conn.close()

def get_failed_attempts(telegram_id):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT failed_attempts FROM users WHERE telegram_id = ?",
        (telegram_id,)
    )
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def generate_redemption_code():
    letters = ''.join(random.choices(string.ascii_uppercase, k=4))
    numbers = ''.join(random.choices(string.digits, k=4))
    return f"NL-{letters}-{numbers}"

def generate_transaction_id():
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

def get_transaction_by_code(code):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM transactions WHERE redemption_code = ?",
        (code.upper(),)
    )
    result = cursor.fetchone()
    conn.close()
    return result

def mark_redeemed(code):
    conn = sqlite3.connect("nairalink.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE transactions SET status = 'redeemed' WHERE redemption_code = ?",
        (code.upper(),)
    )
    conn.commit()
    conn.close()

def get_usdc_balance(wallet_address):
    try:
        pubkey = Pubkey.from_string(wallet_address)
        from solana.rpc.types import TokenAccountOpts
        opts = TokenAccountOpts(mint=Pubkey.from_string(USDC_MINT))
        response = SOLANA_CLIENT.get_token_accounts_by_owner(pubkey, opts)
        if response.value:
            amount = response.value[0].account.data.parsed[
                "info"]["tokenAmount"]["uiAmount"]
            return amount if amount else 0.0
        return 0.0
    except Exception:
        return 0.0
def get_bank_code(bank_name):
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

def simulate_paystack_transfer(
        recipient_name, bank_name, account_number, amount_naira):
    import time
    import random

    bank_code = get_bank_code(bank_name)
    reference = f"NL-PAY-{''.join(random.choices('0123456789ABCDEF', k=12))}"
    transfer_code = f"TRF_{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=16))}"

    time.sleep(1.5)

    return {
        "status": "success",
        "reference": reference,
        "transfer_code": transfer_code,
        "bank_code": bank_code,
        "account_number": account_number,
        "recipient_name": recipient_name,
        "amount": amount_naira,
        "bank_name": bank_name.title(),
        "message": "Transfer initiated successfully"
        }
def get_exchange_rate(currency="GBP"):
    import requests
    import os
    try:
        api_key = os.getenv("EXCHANGE_RATE_API_KEY")
        response = requests.get(
            f"https://v6.exchangerate-api.com/v6/{api_key}/latest/{currency}"
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
    return {
        "ngn_per_foreign": 1950,
        "foreign_per_usdc": 1.0,
        "ngn_per_usdc": 1650,
        "currency": currency
    }

def generate_transak_link(
        api_key, amount, currency, wallet_address):
    import urllib.parse
    base_url = "https://global-stg.transak.com"
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
    return f"{base_url}?{query}"

def calculate_send_cost(naira_amount, currency="GBP"):
    rates = get_exchange_rate(currency)
    ngn_per_foreign = rates["ngn_per_foreign"]
    foreign_amount = round(naira_amount / ngn_per_foreign, 2)
    usdc_amount = round(naira_amount / rates["ngn_per_usdc"], 2)
    fee_foreign = round(foreign_amount * 0.008, 2)
    total_foreign = round(foreign_amount + fee_foreign, 2)
    return {
        "naira_amount": naira_amount,
        "foreign_amount": foreign_amount,
        "fee_foreign": fee_foreign,
        "total_foreign": total_foreign,
        "usdc_amount": usdc_amount,
        "currency": currency,
        "rate": ngn_per_foreign
    }
    
