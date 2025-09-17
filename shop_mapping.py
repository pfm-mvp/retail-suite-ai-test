# shop_mapping.py
# ✅ Enkelvoudige bron: id → {name, region, postcode}
SHOP_NAME_MAP = {
    32224: {"name": "Amersfoort", "region": "Noord NL", "postcode": "3811"},
    31977: {"name": "Amsterdam",  "region": "Noord NL", "postcode": "1012"},
    31831: {"name": "Den Bosch",  "region": "Zuid NL",  "postcode": "5211"},
    32872: {"name": "Haarlem",    "region": "Noord NL", "postcode": "2011"},
    32319: {"name": "Leiden",     "region": "Noord NL", "postcode": "2311"},
    32871: {"name": "Maastricht", "region": "Zuid NL",  "postcode": "6211"},
    30058: {"name": "Nijmegen",   "region": "Zuid NL",  "postcode": "6511"},
    32320: {"name": "Rotterdam",  "region": "Zuid NL",  "postcode": "3011"},
    32204: {"name": "Venlo",      "region": "Zuid NL",  "postcode": "5911"},
}

# Helper: haal 4-cijferige postcode op (letters worden gestript)
def get_postcode_by_id(shop_id: int) -> str:
    raw = str(SHOP_NAME_MAP.get(shop_id, {}).get("postcode", "")).strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[:4] if digits else ""
