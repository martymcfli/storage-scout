"""
Vision Scout — Claude Sonnet 4.6 computer vision agent.

Architecture:
  1. Playwright scrapes all large images from a StorageTreasures listing page
  2. Each image is downloaded and base64-encoded (Anthropic vision API requires this)
  3. Claude Sonnet analyzes each photo: identifies items, estimates resale value + flip time
  4. Results are aggregated into a VisualInventory used by the Bid Strategist and all other agents

Model choice: claude-sonnet-4-6 — vision-capable, faster/cheaper than Opus for per-image
calls, and critically better than raw object-detection APIs (Google Vision, AWS Rekognition)
because it understands context and resale value, not just labels.

Cost: ~$0.01–0.04 per image at typical 1024x768 resolution. 5 photos per unit ≈ $0.05–0.20.
"""
import asyncio
import base64
import json
import os
import re
from typing import Optional

import anthropic
import httpx
from playwright.async_api import async_playwright

from .models import VisualInventory, VisualItem

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MAX_PHOTOS_PER_UNIT = 6          # cost control; first N photos analyzed
MIN_IMAGE_DIMENSION = 150        # px — filters out icons, thumbnails, UI elements
SKIP_URL_FRAGMENTS = [
    "logo", "icon", "avatar", "button", "banner", "badge",
    "sprite", "placeholder", "blank", "loading", "spinner",
]

VISION_SYSTEM = """You are Vision Scout, a specialist reseller with 15 years of experience
flipping items from storage units. You analyze storage unit photos to identify every item
worth selling, estimate its realistic resale value, and flag anything that changes the math.

Your eye is trained to spot:
- Solid wood furniture vs. pressed MDF (solid = 3-5× more valuable)
- Brand markings on tools even in dim/partial photos
- Signs of water damage, mold, or structural issues that kill value
- Items partially obscured that experienced bidders would notice and others miss
- Vintage or antique pieces that sell well on specialized platforms

Be specific. "Cabinet" is not useful. "Oak Hoosier-style cabinet, solid construction,
glass upper doors intact, approx 5ft tall, good condition" is useful.
"""

VISION_PROMPT = """Analyze this storage unit photo. Identify every item worth noting.

For each item return:
- description: specific (material, brand if visible, size estimate, style)
- condition: "excellent" | "good" | "fair" | "poor"
- resale_low: realistic low-end $ on Facebook Marketplace or Craigslist
- resale_high: realistic high-end $ (eBay sold listings or specialty buyer)
- flip_hours: total hours to photograph, list, communicate, hand off / ship
- best_platform: "Facebook Marketplace" | "eBay" | "Craigslist" | "specialty auction" | "scrap"
- notes: anything that changes the value estimate (brand visible, damage, unusual item)

Also return:
- notable_finds: list of high-value items or surprises a general bidder would miss
- red_flags: list of issues that reduce value or add cost (water damage, hazmat, junk density)
- photo_quality_note: "clear" | "partial" | "dark" | "obscured" — how well can you see the unit

Return ONLY valid JSON. No other text:
{
  "items": [
    {
      "description": "...",
      "condition": "good",
      "resale_low": 150,
      "resale_high": 350,
      "flip_hours": 2.0,
      "best_platform": "Facebook Marketplace",
      "notes": "..."
    }
  ],
  "notable_finds": [],
  "red_flags": [],
  "photo_quality_note": "clear"
}"""


async def _scrape_photo_urls(listing_url: str) -> list[str]:
    """Extract large unit photo URLs from a StorageTreasures (or Bid13) listing page."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(listing_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)

            images = await page.eval_on_selector_all(
                "img",
                """els => els.map(el => ({
                    src: el.src || el.getAttribute('data-src') || el.getAttribute('data-lazy-src') || '',
                    width: el.naturalWidth || el.width || 0,
                    height: el.naturalHeight || el.height || 0
                }))"""
            )
        finally:
            await browser.close()

    photo_urls = []
    seen: set[str] = set()

    for img in images:
        src = img.get("src", "").strip()
        if not src or src in seen:
            continue
        if img.get("width", 0) < MIN_IMAGE_DIMENSION and img.get("height", 0) < MIN_IMAGE_DIMENSION:
            continue
        if any(frag in src.lower() for frag in SKIP_URL_FRAGMENTS):
            continue
        if src.startswith("data:"):
            continue

        seen.add(src)
        photo_urls.append(src)

    return photo_urls[:MAX_PHOTOS_PER_UNIT]


def _fetch_image_as_base64(url: str) -> Optional[tuple[str, str]]:
    """Download an image and return (base64_data, media_type). Returns None on failure."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://www.storagetreasures.com/",
        }
        resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        if resp.status_code != 200:
            return None

        content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        if not content_type.startswith("image/"):
            return None

        data = base64.standard_b64encode(resp.content).decode("utf-8")
        return data, content_type
    except Exception as e:
        print(f"[Vision] Could not fetch {url}: {e}")
        return None


def _analyze_single_photo(image_data: str, media_type: str, photo_index: int) -> dict:
    """Run Claude Sonnet vision on one image. Returns parsed dict or error dict."""
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=VISION_SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {"type": "text", "text": VISION_PROMPT},
                ],
            }],
        )

        raw = response.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        return json.loads(raw)

    except json.JSONDecodeError as e:
        print(f"[Vision] JSON parse error on photo {photo_index}: {e}")
        return {"items": [], "notable_finds": [], "red_flags": [], "photo_quality_note": "parse_error"}
    except Exception as e:
        print(f"[Vision] Claude error on photo {photo_index}: {e}")
        return {"items": [], "notable_finds": [], "red_flags": [], "photo_quality_note": "api_error"}


def _aggregate_results(photo_results: list[dict]) -> tuple[list[VisualItem], list[str], list[str], str]:
    """Merge results across multiple photos, deduplicating items by description similarity."""
    all_items: list[VisualItem] = []
    all_notable: list[str] = []
    all_red_flags: list[str] = []
    quality_notes: list[str] = []

    seen_descriptions: set[str] = set()

    for result in photo_results:
        quality_notes.append(result.get("photo_quality_note", "unknown"))
        all_notable.extend(result.get("notable_finds", []))
        all_red_flags.extend(result.get("red_flags", []))

        for raw_item in result.get("items", []):
            try:
                desc = raw_item.get("description", "").lower()
                # simple dedup: skip if a very similar description already exists
                is_dup = any(
                    _jaccard_similarity(desc, seen) > 0.6
                    for seen in seen_descriptions
                )
                if is_dup:
                    continue

                seen_descriptions.add(desc)
                all_items.append(VisualItem(
                    description=raw_item.get("description", "unknown item"),
                    condition=raw_item.get("condition", "unknown"),
                    resale_low=int(raw_item.get("resale_low", 0)),
                    resale_high=int(raw_item.get("resale_high", 0)),
                    flip_hours=float(raw_item.get("flip_hours", 1.0)),
                    best_platform=raw_item.get("best_platform", "Facebook Marketplace"),
                    notes=raw_item.get("notes", ""),
                ))
            except Exception as e:
                print(f"[Vision] Item parse error: {e} — raw: {raw_item}")

    deduped_notable = list(dict.fromkeys(all_notable))
    deduped_flags = list(dict.fromkeys(all_red_flags))
    vision_notes = f"Photos: {', '.join(quality_notes)}"

    return all_items, deduped_notable, deduped_flags, vision_notes


def _jaccard_similarity(a: str, b: str) -> float:
    set_a = set(a.split())
    set_b = set(b.split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


async def analyze_unit_visually(listing_url: str) -> VisualInventory:
    """
    Full vision pipeline:
      1. Scrape photo URLs from the listing page
      2. Download + base64-encode each photo
      3. Pass each to Claude Sonnet vision
      4. Aggregate into a VisualInventory

    Runs photo scraping async, then processes photos sequentially
    (Anthropic API has per-request concurrency limits).
    """
    print(f"[Vision] Scraping photos from {listing_url}")
    photo_urls = await _scrape_photo_urls(listing_url)
    print(f"[Vision] Found {len(photo_urls)} photos")

    if not photo_urls:
        return VisualInventory(
            photo_urls=[],
            photos_analyzed=0,
            vision_notes="No photos found on listing page",
        )

    photo_results: list[dict] = []
    analyzed_count = 0

    for i, url in enumerate(photo_urls):
        fetched = _fetch_image_as_base64(url)
        if not fetched:
            print(f"[Vision] Skipping unfetchable image: {url}")
            continue

        image_data, media_type = fetched
        print(f"[Vision] Analyzing photo {i+1}/{len(photo_urls)}")
        result = _analyze_single_photo(image_data, media_type, i + 1)
        photo_results.append(result)
        analyzed_count += 1

    items, notable, red_flags, vision_notes = _aggregate_results(photo_results)

    total_low = sum(item.resale_low for item in items)
    total_high = sum(item.resale_high for item in items)
    total_hours = sum(item.flip_hours for item in items)

    return VisualInventory(
        photo_urls=photo_urls,
        photos_analyzed=analyzed_count,
        items=items,
        total_value_low=total_low,
        total_value_high=total_high,
        total_flip_hours=round(total_hours, 1),
        notable_finds=notable,
        red_flags=red_flags,
        vision_notes=vision_notes,
    )
