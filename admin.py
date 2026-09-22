import os


def _admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "")
    result: set[int] = set()
    for item in raw.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError:
            continue
    # Keep the historical admin ID used by the supplied bot only as an opt-in
    # fallback. Set ADMIN_IDS in production instead.
    legacy = os.getenv("LEGACY_ADMIN_ID", "8244079903")
    if os.getenv("ALLOW_LEGACY_ADMIN", "false").lower() == "true":
        try:
            result.add(int(legacy))
        except ValueError:
            pass
    return result


def is_admin(user_id: int) -> bool:
    return int(user_id) in _admin_ids()
