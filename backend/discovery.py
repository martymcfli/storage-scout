"""
Phase 5: Auto-Discovery
Scrapes StorageTreasures.com, Bid13, and StorageAuctions.net for auction notices.
Integrates with the user profile for ZIP radius expansion and available-day filtering.
"""
import asyncio
import re
from typing import Optional
from playwright.async_api import async_playwright
from .storage import get_existing_urls
from .models import AuctionUnit
from .sources.storageauctions_net import discover_storage_auctions_net

WEEKDAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _parse_weekday(date_str: Optional[str]) -> Optional[str]:
    """Return lowercase weekday name from a date string, or None if unparseable."""
    if not date_str:
        return None
    try:
        from dateutil import parser as dateparser
        dt = dateparser.parse(date_str, fuzzy=True)
        return WEEKDAY_NAMES[dt.weekday()]
    except Exception:
        return None


def filter_units_by_day(units: list[AuctionUnit], available_days: list[str]) -> list[AuctionUnit]:
    """Drop units whose auction_date falls on a day the user is NOT available.
    Units with unparseable or missing dates are kept (benefit of the doubt)."""
    if not available_days:
        return units

    normalized = {d.lower().strip() for d in available_days}
    kept = []
    for unit in units:
        day = _parse_weekday(unit.tenant.auction_date)
        if day is None or day in normalized:
            kept.append(unit)
        else:
            print(f"[Discovery] Skipping {unit.tenant.name} — auction on {day}, not in available days")
    return kept


async def _discover_storage_treasures(zip_codes: list[str]) -> list[str]:
    urls = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for zip_code in zip_codes:
            try:
                target = f"https://www.storagetreasures.com/auctions/?postalCode={zip_code}&distance=25"
                await page.goto(target, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)

                links = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(el => el.href)"
                )

                for link in links:
                    if (
                        "storagetreasures.com" in link
                        and "/auctions/" in link
                        and link.count("/") > 4
                        and "?" not in link.split("/auctions/")[1]
                    ):
                        clean = link.split("?")[0].rstrip("/")
                        if clean not in urls:
                            urls.append(clean)
            except Exception as e:
                print(f"[Discovery] StorageTreasures ZIP {zip_code} error: {e}")

        await browser.close()
    return urls


async def _discover_bid13(zip_codes: list[str]) -> list[str]:
    """
    Bid13 uses /node/XXXXXX URLs rendered via JavaScript.
    We fill in the ZIP form and collect the resulting node links.
    """
    seen: set[str] = set()
    urls: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for zip_code in zip_codes:
            try:
                await page.goto("https://bid13.com/auctions", wait_until="networkidle", timeout=30000)
                await asyncio.sleep(1)

                # Fill ZIP code into the search form and submit
                zip_input = page.locator("input[placeholder*='Zip'], input[type='text']").first
                await zip_input.fill(zip_code)
                await page.keyboard.press("Enter")
                await asyncio.sleep(3)

                links = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(el => el.href)"
                )

                for link in links:
                    if "bid13.com" in link and re.search(r"/node/\d+", link):
                        clean = link.split("?")[0].rstrip("/")
                        if clean not in seen:
                            seen.add(clean)
                            urls.append(clean)

            except Exception as e:
                print(f"[Discovery] Bid13 ZIP {zip_code} error: {e}")

        await browser.close()

    return urls


async def discover_new_auctions(zip_codes: list[str]) -> list[str]:
    """Return URLs of auction notice pages not already in the database."""
    existing = get_existing_urls()

    st_urls, b13_urls, san_urls = await asyncio.gather(
        _discover_storage_treasures(zip_codes),
        _discover_bid13(zip_codes),
        discover_storage_auctions_net(zip_codes),
    )

    all_discovered = st_urls + b13_urls + san_urls
    new_urls = [url for url in all_discovered if url not in existing]

    print(
        f"[Discovery] ST={len(st_urls)} Bid13={len(b13_urls)} SAN={len(san_urls)} "
        f"total={len(all_discovered)} new={len(new_urls)} across {len(zip_codes)} ZIP(s)"
    )
    return new_urls
