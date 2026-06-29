"""
StorageAuctions.net scraper — third discovery source.
Search by ZIP using their /find-storage-auctions path.
"""
import asyncio
import re
from playwright.async_api import async_playwright


async def discover_storage_auctions_net(zip_codes: list[str]) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for zip_code in zip_codes:
            try:
                target = f"https://www.storageauctions.net/find-storage-auctions?zip={zip_code}&distance=25"
                await page.goto(target, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

                links = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(el => el.href)"
                )

                for link in links:
                    if (
                        "storageauctions.net" in link
                        and re.search(r"/auctions?/\d+", link)
                    ):
                        clean = link.split("?")[0].rstrip("/")
                        if clean not in seen:
                            seen.add(clean)
                            urls.append(clean)

            except Exception as e:
                print(f"[Discovery] StorageAuctions.net ZIP {zip_code} error: {e}")

        await browser.close()

    return urls
