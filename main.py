# -*- coding: utf-8 -*-

from commands.base import bot
import os
import asyncio


async def main_task(token):
    print("Logging in...")
    await bot._bot.login(token)
    print("Logged in, Connecting...")
    await bot._bot.connect()


def main():
    loop = asyncio.get_event_loop()
    token = os.environ.get("TOKEN")
    if token in [None, ""]:
        raise RuntimeError("No discord token set in environment")

    try:
        loop.run_until_complete(main_task(token))
    finally:
        loop.run_until_complete(asyncio.sleep(1))
        loop.stop()


if __name__ == "__main__":
    main()


