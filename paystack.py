import os
import time
import random
import requests
from helpers import get_bank_code

def initiate_paystack_transfer(recipient_name, bank_name, account_number, amount_naira):
    """
    Initiate a real transfer via Paystack API using test or live secret key.
    Returns dict with status, reference, and other details.
    """
    secret_key = os.getenv("PAYSTACK_SECRET_KEY")
    if not secret_key:
        return {
            "status": "error",
            "message": "Paystack secret key not configured. Set PAYSTACK_SECRET_KEY environment variable."
        }

    # Validate bank
    bank_code = get_bank_code(bank_name)
    if bank_code == "000":
        return {
            "status": "error",
            "message": f"Bank '{bank_name}' not recognized. Please use a supported bank."
        }

    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json"
    }

    # Step 1: Create transfer recipient
    recipient_url = "https://api.paystack.co/transferrecipient"
    recipient_data = {
        "type": "nuban",
        "name": recipient_name,
        "account_number": account_number,
        "bank_code": bank_code,
        "currency": "NGN"
    }

    try:
        resp = requests.post(recipient_url, json=recipient_data, headers=headers, timeout=10)
        resp_json = resp.json()
        if not resp_json.get("status"):
            return {
                "status": "error",
                "message": f"Failed to create recipient: {resp_json.get('message', 'Unknown error')}"
            }
        recipient_code = resp_json["data"]["recipient_code"]
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error creating transfer recipient: {str(e)}"
        }

    # Step 2: Initiate transfer
    transfer_url = "https://api.paystack.co/transfer"
    reference = f"NL-{int(time.time())}-{random.randint(1000,9999)}"
    transfer_data = {
        "source": "balance",
        "amount": int(amount_naira * 100),  # Paystack uses kobo
        "recipient": recipient_code,
        "reason": f"Money transfer to {recipient_name}",
        "reference": reference
    }

    try:
        resp = requests.post(transfer_url, json=transfer_data, headers=headers, timeout=10)
        transfer_json = resp.json()
        if transfer_json.get("status"):
            return {
                "status": "success",
                "reference": transfer_json["data"]["reference"],
                "transfer_code": transfer_json["data"]["transfer_code"],
                "bank_code": bank_code,
                "account_number": account_number,
                "recipient_name": recipient_name,
                "amount": amount_naira,
                "bank_name": bank_name.title(),
                "message": "Transfer initiated successfully"
            }
        else:
            return {
                "status": "error",
                "message": transfer_json.get("message", "Transfer initiation failed"),
                "details": transfer_json
            }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error initiating transfer: {str(e)}"
        }
