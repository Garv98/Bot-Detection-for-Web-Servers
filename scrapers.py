
import httpx
import asyncio
import time

async def simulate_bot(name, delay, identify=False):
    url = "http://localhost:8000/api/data"
    headers = {"User-Agent": "Crawl-Bot/1.0"} if identify else {}
    
    print(f"[{name}] Starting attack...")
    async with httpx.AsyncClient() as client:
        for i in range(15):
            try:
                resp = await client.get(url, headers=headers)
                print(f"[{name}] Hit {i+1}: Status {resp.status_code}")
                if resp.status_code == 429:
                    print(f"[{name}] BLOCKED BY BIG DATA ENGINE.")
                    break
                await asyncio.sleep(delay)
            except: break

if __name__ == "__main__":
    print("DEMONSTRATION: Human activity is normal. Bot activity triggers 429.")
    asyncio.run(simulate_bot("STEALTH_SCRAPER", 0.1))
