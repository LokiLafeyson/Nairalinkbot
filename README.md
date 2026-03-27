# NairaLink Bot

A Telegram bot for sending money home instantly using Solana blockchain.

## Features
- Send Naira to recipients instantly
- USDC balance tracking
- Cash pickup codes via OPay/PalmPay
- Under 1% fees, settles in seconds

## Commands
- /start — Welcome and menu
- /help — How NairaLink works
- /balance — Check your USDC balance
- /send — Send money home
- /fund — Fund your wallet

## Usage
Type `send 50000 to Mum` to send ₦50,000 to Mum.

## Setup
```
pip install python-telegram-bot python-dotenv
```
Create a `.env` file:
```
BOT_TOKEN=your_telegram_bot_token
```
Run: `python nairalink_bot.py`

