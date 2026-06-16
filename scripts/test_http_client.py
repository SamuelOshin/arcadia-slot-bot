import urllib.request
import json
import httpx
import aiohttp
import asyncio
import time
import socket
from dotenv import load_dotenv
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

load_dotenv()

from app.core.session_manager import SessionManager

def test_urllib(url, headers):
    start = time.time()
    print("\n--- Testing urllib ---")
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15.0) as response:
            data = response.read()
            elapsed = (time.time() - start) * 1000
            print(f"urllib success: {response.status} in {elapsed:.1f}ms, length: {len(data)}")
    except Exception as e:
        print(f"urllib failed: {e}")

def test_httpx(url, headers):
    start = time.time()
    print("\n--- Testing httpx (HTTP/1.1 only) ---")
    try:
        with httpx.Client(timeout=15.0, http2=False) as client:
            resp = client.get(url, headers=headers)
            elapsed = (time.time() - start) * 1000
            print(f"httpx success: {resp.status_code} in {elapsed:.1f}ms, length: {len(resp.text)}")
    except Exception as e:
        print(f"httpx failed: {e}")

async def test_aiohttp(url, headers):
    start = time.time()
    print("\n--- Testing aiohttp (Forced IPv4) ---")
    try:
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        async with aiohttp.ClientSession(headers=headers, connector=connector) as session:
            async with session.get(url, timeout=15.0) as resp:
                text = await resp.text()
                elapsed = (time.time() - start) * 1000
                print(f"aiohttp success: {resp.status} in {elapsed:.1f}ms, length: {len(text)}")
    except Exception as e:
        print(f"aiohttp failed: {e}")

async def main():
    session = SessionManager()
    url = "https://arcadia-roster.up.railway.app/api/clip/campaigns"
    headers = session.headers
    
    test_urllib(url, headers)
    test_httpx(url, headers)
    await test_aiohttp(url, headers)

if __name__ == "__main__":
    asyncio.run(main())
