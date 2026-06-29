import asyncio
import uuid
import re
from playwright.async_api import async_playwright
import anthropic
import os

from .models import AuctionUnit, TenantProfile

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


async def fetch_page_text(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        text = await page.inner_text("body")
        await browser.close()
        return text


def extract_units_with_haiku(page_text: str, source_url: str) -> list[AuctionUnit]:
    prompt = f"""You are extracting storage auction lien notice data from a webpage.

Extract ALL individual storage unit listings. For each unit find:
- tenant_name: the person's full name
- unit_number: the storage unit number/ID
- facility_address: the facility's street address
- facility_name: the storage facility name if present
- auction_date: date of auction if present
- default_amount: dollar amount owed if present

Return a JSON array of objects. If no units found, return [].

Page text:
{page_text[:8000]}
"""

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    import json
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        return []

    units = []
    for item in items:
        if not item.get("tenant_name") or not item.get("unit_number"):
            continue
        tenant = TenantProfile(
            name=item["tenant_name"],
            unit_number=item.get("unit_number", ""),
            facility_address=item.get("facility_address", ""),
            auction_date=item.get("auction_date"),
            default_amount=item.get("default_amount"),
        )
        unit = AuctionUnit(
            id=str(uuid.uuid4()),
            source_url=source_url,
            facility_name=item.get("facility_name"),
            facility_address=item.get("facility_address"),
            tenant=tenant,
        )
        units.append(unit)

    return units


async def scrape_auction_page(url: str) -> list[AuctionUnit]:
    page_text = await fetch_page_text(url)
    return extract_units_with_haiku(page_text, url)
