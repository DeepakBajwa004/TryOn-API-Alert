"""One-time helper: generate a Telethon session string for the account that will place the calls.

Run locally (never on Render):  python gen_session.py
"""

import asyncio
import getpass

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main() -> None:
    api_id = int(input("API ID: ").strip())
    api_hash = getpass.getpass("API HASH: ").strip()
    async with TelegramClient(StringSession(), api_id, api_hash) as client:
        print("\nSESSION STRING (keep secret, put in TG_SESSION_STRING):\n")
        print(client.session.save())


asyncio.run(main())
