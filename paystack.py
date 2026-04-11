import os
import time
import random
from helpers import get_bank_code

def initiate_paystack_transfer(recipient_name, bank_name, account_number, amount_naira):
    """
    Simulate a Paystack transfer for demo purposes.
    Always returns success with a realistic reference.
    """
    # Simulate processing delay
    time.sleep(1.5)

    # Generate realistic reference numbers
    reference = f"PAY-{int(time.time())}-{random.randint(1000,9999)}"
    transfer_code = f"TRF_{random.randint(100000000,999999999)}"

    # Validate bank (still checks for realistic behavior)
    bank_code = get_bank_code(bank_name)
    if bank_code == "000":
        # Still return success for demo, but could note bank not found
        pass

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

def check_paystack_balance():
    """
    Simulate checking Paystack wallet balance for demo.
    Returns a mock balance so admin commands work.
    """
    import random
    # Simulate a balance between ₦500,000 and ₦5,000,000 (in kobo)
    mock_balance_kobo = random.randint(50_000_000, 500_000_000)
    mock_balance_ngn = mock_balance_kobo / 100
    return {
        "status": True,
        "data": [
            {
                "currency": "NGN",
                "balance": mock_balance_kobo
            }
        ],
        "message": f"Demo balance: ₦{mock_balance_ngn:,.2f}"
    }
