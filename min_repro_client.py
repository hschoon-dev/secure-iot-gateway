"""
Minimal asyncua client for memory leak reproduction.
This client continually creates subscriptions on the server and prints the amount every
    thousandth subscription it has created.
"""

import asyncio
import logging
import sys

from asyncua import Client

class Handler:
    def datachange_notification(self, node, val, data):
        pass

    def event_notification(self, event):
        pass


async def run_client():
    await asyncio.sleep(1)
    client = Client("opc.tcp://127.0.0.1:4840/freeopcua/server/")
    async with client:
        handler = Handler()
        i = 0
        while True:
            sub = await client.create_subscription(sys.maxsize, handler)
            i += 1
            if i % 1000 == 0:
                print(f"created {i} subscriptions, last id={sub.subscription_id}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    asyncio.run(run_client())
