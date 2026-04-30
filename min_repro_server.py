"""
Minimal asyncua server for memory leak reproduction.
All this does is start a server print the memory usage every two seconds.
"""

import asyncio
import logging
import psutil
import os

from asyncua import Server

async def run_server():
    process = psutil.Process(os.getpid())
    server = Server()
    await server.init()
    server.set_endpoint("opc.tcp://127.0.0.1:4840/freeopcua/server/")
    async with server:
        while True:
            print(f"Server memory usage: {process.memory_info().rss / 1024 / 1024:.2f} MB")
            await asyncio.sleep(2)

if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    asyncio.run(run_server())