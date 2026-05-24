from difflib import get_close_matches

TARGET_WORDS = [
    "tiktok", "facebook", "instagram", "messenger",
    "telegram", "whatsapp", "viber", "shopee", "lazada"
]

PHONETIC_MAP = {
    "ticktock": "tiktok",
    "ticktok": "tiktok",
    "tik tok": "tiktok",
    "face book": "facebook",
    "insta gram": "instagram",
    "whats up": "whatsapp",
    "what's up": "whatsapp"
}

def normalize_word(word):
    clean = word.lower().strip(".,!?'")

    # direct phonetic mapping first
    if clean in PHONETIC_MAP:
        return PHONETIC_MAP[clean]

    # fuzzy match fallback
    match = get_close_matches(clean, TARGET_WORDS, n=1, cutoff=0.7)
    return match[0] if match else clean






