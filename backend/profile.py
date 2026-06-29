import json
import os
from typing import Optional
from .models import UserProfile

PROFILE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "profile.json")


def load_profile() -> Optional[UserProfile]:
    if not os.path.exists(PROFILE_FILE):
        return None
    with open(PROFILE_FILE) as f:
        try:
            return UserProfile.model_validate(json.load(f))
        except Exception:
            return None


def save_profile(profile: UserProfile) -> None:
    os.makedirs(os.path.dirname(PROFILE_FILE), exist_ok=True)
    with open(PROFILE_FILE, "w") as f:
        json.dump(profile.model_dump(), f, indent=2)


def profile_exists() -> bool:
    return os.path.exists(PROFILE_FILE)
