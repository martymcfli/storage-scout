"""
ZIP radius expansion using uszipcode (offline SQLite database — no API key needed).
Falls back gracefully if the library or ZIP is not found.
"""
from typing import Optional


def get_zips_in_radius(home_zip: str, max_miles: int) -> list[str]:
    """Return all ZIP codes within max_miles of home_zip (straight-line distance)."""
    try:
        from uszipcode import SearchEngine
        search = SearchEngine()
        home = search.by_zipcode(home_zip)

        if not home or not home.lat or not home.lng:
            print(f"[ZipRadius] Could not locate ZIP {home_zip}, using it alone.")
            return [home_zip]

        results = search.by_coordinates(
            home.lat, home.lng,
            radius=max_miles,
            returns=500,
        )

        zips = [r.zipcode for r in results if r.zipcode]
        print(f"[ZipRadius] {len(zips)} ZIPs within {max_miles} miles of {home_zip}")
        return zips if zips else [home_zip]

    except ImportError:
        print("[ZipRadius] uszipcode not installed — falling back to home ZIP only.")
        return [home_zip]
    except Exception as e:
        print(f"[ZipRadius] Error: {e} — falling back to home ZIP only.")
        return [home_zip]


def get_zip_location(zip_code: str) -> Optional[dict]:
    """Return city/state/lat/lng for a ZIP, or None if not found."""
    try:
        from uszipcode import SearchEngine
        search = SearchEngine()
        z = search.by_zipcode(zip_code)
        if not z or not z.lat:
            return None
        return {
            "zip": z.zipcode,
            "city": z.major_city or z.post_office_city,
            "state": z.state,
            "lat": z.lat,
            "lng": z.lng,
        }
    except Exception:
        return None
