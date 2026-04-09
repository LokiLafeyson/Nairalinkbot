import os
import requests

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

def initiate_paystack_transfer(
        recipient_name, bank_name, account_number, amount_naira):
    secret_key = os.getenv("PAYSTACK_SECRET_KEY")
    headers = {
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": "application/json"
    }
    bank_code = get_bank_code(bank_name)

    try:
        # Step 1: Create transfer recipient
        recipient_response = requests.post(
            "https://api.paystack.co/transferrecipient",
            json={
                "type": "nuban",
                "name": recipient_name,
                "account_number": account_number,
                "bank_code": bank_code,
                "currency": "NGN"
            },
            headers=headers,
            timeout=15
        )
        recipient_data = recipient_response.json()

        if not recipient_data.get("status"):
            return {
                "status": "error",
                "message": recipient_data.get("message", "Failed to create recipient")
            }

        recipient_code = recipient_data["data"]["recipient_code"]

        # Step 2: Initiate transfer
        transfer_response = requests.post(
            "https://api.paystack.co/transfer",
            json={
                "source": "balance",
                "amount": amount_naira * 100,
                "recipient": recipient_code,
                "reason": f"NairaLink remittance to {recipient_name}"
            },
            headers=headers,
            timeout=15
        )
        transfer_data = transfer_response.json()

        if transfer_data.get("status"):
            return {
                "status": "success",
                "reference": transfer_data["data"]["reference"],
                "transfer_code": transfer_data["data"]["transfer_code"],
                "message": "Transfer initiated successfully"
            }
        else:
            return {
                "status": "error",
                "message": transfer_data.get("message", "Transfer failed")
            }

    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
    }
