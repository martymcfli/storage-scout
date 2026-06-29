import json
import os
from typing import Optional
from .models import AuctionUnit, Alert

AUCTIONS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "auctions.json")
ALERTS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "alerts.json")


def _load_json(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _save_json(path: str, data: list) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# --- Auction CRUD ---

def get_all_auctions() -> list[AuctionUnit]:
    raw = _load_json(AUCTIONS_FILE)
    return [AuctionUnit.model_validate(r) for r in raw]


def get_auction_by_id(auction_id: str) -> Optional[AuctionUnit]:
    for unit in get_all_auctions():
        if unit.id == auction_id:
            return unit
    return None


def get_existing_urls() -> set[str]:
    return {u.source_url for u in get_all_auctions()}


def save_auction(unit: AuctionUnit) -> None:
    units = get_all_auctions()
    for i, u in enumerate(units):
        if u.id == unit.id:
            units[i] = unit
            _save_json(AUCTIONS_FILE, [u.model_dump() for u in units])
            return
    units.append(unit)
    _save_json(AUCTIONS_FILE, [u.model_dump() for u in units])


def delete_auction(auction_id: str) -> bool:
    units = get_all_auctions()
    filtered = [u for u in units if u.id != auction_id]
    if len(filtered) == units.__len__():
        return False
    _save_json(AUCTIONS_FILE, [u.model_dump() for u in filtered])
    return True


# --- Alerts ---

def get_all_alerts() -> list[Alert]:
    raw = _load_json(ALERTS_FILE)
    return [Alert.model_validate(r) for r in raw]


def save_alert(alert: Alert) -> None:
    alerts = get_all_alerts()
    alerts.append(alert)
    _save_json(ALERTS_FILE, [a.model_dump() for a in alerts])


def alert_exists(unit_id: str) -> bool:
    return any(a.unit_id == unit_id for a in get_all_alerts())
