import os
import time
import random
import smtplib
from email.message import EmailMessage
from helpers import get_bank_code

def send_confirmation_email(amount, recipient_name, reference):
    """Send a confirmation email to the business email address."""
    sender = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")
    
    if not sender or not password:
        print("⚠️ Email not configured – skipping notification.")
        return
    
    # Send to the same business email (or you can set a separate admin email)
    to_email = sender  # sends to the business email itself
    
    msg = EmailMessage()
    msg["Subject"] = f"Paystack Transfer Confirmation - ₦{amount:,}"
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content(f"""
    Paystack Transfer Successful

    Amount: ₦{amount:,}
    Recipient: {recipient_name}
    Reference: {reference}
    Status: Completed

    This is an automated confirmation from your NairaLink bot.
    """)
    
    try:
        with smtplib.SMTP("smtp.zoho.com", 587) as smtp:
            smtp.starttls()
            smtp.login(sender, password)
            smtp.send_message(msg)
        print(f"✅ Confirmation email sent to {to_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

def initiate_paystack_transfer(recipient_name, bank_name, account_number, amount_naira):
    """
    Simulate a Paystack transfer and send email confirmation.
    """
    # Simulate processing delay
    time.sleep(1.5)
    
    # Generate realistic reference
    reference = f"PAY-{int(time.time())}-{random.randint(1000,9999)}"
    transfer_code = f"TRF_{random.randint(100000000,999999999)}"
    bank_code = get_bank_code(bank_name)
    
    # Send email confirmation
    send_confirmation_email(amount_naira, recipient_name, reference)
    
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
