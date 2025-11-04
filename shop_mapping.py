# shop_mapping.py
# ✅ Enkelvoudige bron: id → {name, region, postcode}
SHOP_NAME_MAP = {
    29658: {"name": "Amsterdam", "region": "Noord NL", "postcode": "3811"},
    29679: {"name": "Apeldoorn",  "region": "Noord NL", "postcode": "7331"},
    29683: {"name": "Den Haag",  "region": "Zuid NL",  "postcode": "2511"},
    29669: {"name": "Gouda",    "region": "Noord NL", "postcode": "2801"},
    29771: {"name": "Haarlem",     "region": "Noord NL", "postcode": "2011"},
    29770: {"name": "Leiden", "region": "Zuid NL",  "postcode": "2311"},
    28704: {"name": "Rotterdam",  "region": "Zuid NL",  "postcode": "3087"},
    29691: {"name": "Tilburg",      "region": "Zuid NL",  "postcode": "5038"},
}

# Helper: haal 4-cijferige postcode op (letters worden gestript)
def get_postcode_by_id(shop_id: int) -> str:
    raw = str(SHOP_NAME_MAP.get(shop_id, {}).get("postcode", "")).strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[:4] if digits else ""
