"""
Synonym and Alias Mapping Mechanism for Canonical Tags.

Normalizes raw tag/genre strings from diverse sources (AniList, MangaDex, MyAnimeList)
into stable canonical tags without deleting or discarding unknown tags.

Taxonomic Notes & Mapping Decisions:
1. Yaoi & Shounen Ai:
   - "Yaoi" historically designates sexually explicit or focused male-male romance.
   - "Shounen Ai" historically designates non-explicit emotional male-male romance.
   - For unified search and filtering, both are mapped to the canonical `boys_love` theme,
     preserving the broader umbrella while raw tags retain the granular source distinction.
2. Yuri & Shoujo Ai:
   - "Yuri" and "Shoujo Ai" similarly map to canonical `girls_love`.
3. Webtoon vs Manhwa:
   - "Webtoon" describes a digital vertical scroll format (originating in South Korea).
   - "Manhwa" describes Korean comic origins. Both are mapped to their respective canonical tags
     (`webtoon` under format, `manhwa` under format).
4. Portal Fantasy / Transmigration / Reborn:
   - "Portal Fantasy" and "Another World" map to `isekai`.
   - "Reborn" and "Transmigration" map to `reincarnation`.
   - "Time Reversal" / "Returner" map to `regression`.
"""

import re
from typing import Dict, Optional
from .vocabulary import CANONICAL_VOCABULARY, CanonicalTag, get_tag_by_slug

# Normalization regex for cleaning punctuation, quotes, and whitespace
PUNCT_RE = re.compile(r"['`’]")
DELIMITER_RE = re.compile(r"[-_/]+")
EXTRA_SPACE_RE = re.compile(r"\s+")

def normalize_tag_input(raw: Optional[str]) -> str:
    """
    Normalizes a tag string by lowercasing, stripping punctuation,
    converting hyphens/delimiters to spaces, and collapsing whitespace.
    """
    if not raw or not isinstance(raw, str):
        return ""
    # Lowercase
    s = raw.lower().strip()
    # Normalize curly apostrophes / quotes
    s = PUNCT_RE.sub("", s)
    # Replace delimiters (- and _) with space
    s = DELIMITER_RE.sub(" ", s)
    # Collapse multiple spaces
    s = EXTRA_SPACE_RE.sub(" ", s).strip()
    return s

# ─────────────────────────────────────────────────────────────────────────────
# Controlled Alias Mapping Table: Normalized Alias String -> Canonical Slug
# ─────────────────────────────────────────────────────────────────────────────

RAW_ALIAS_DEFINITIONS: Dict[str, str] = {
    # Boys' Love
    "bl": "boys_love",
    "boys love": "boys_love",
    "boy love": "boys_love",
    "yaoi": "boys_love",
    "shounen ai": "boys_love",
    "shonen ai": "boys_love",
    "danmei": "boys_love",

    # Girls' Love
    "gl": "girls_love",
    "girls love": "girls_love",
    "girl love": "girls_love",
    "yuri": "girls_love",
    "shoujo ai": "girls_love",
    "shojo ai": "girls_love",
    "baihe": "girls_love",

    # Isekai & Reincarnation & Regression
    "isekai": "isekai",
    "another world": "isekai",
    "portal fantasy": "isekai",
    "transported to another world": "isekai",
    "reincarnation": "reincarnation",
    "reincarnated": "reincarnation",
    "reborn": "reincarnation",
    "transmigration": "reincarnation",
    "regression": "regression",
    "time regression": "regression",
    "returner": "regression",
    "time loop": "time_travel",
    "time travel": "time_travel",
    "time leap": "time_travel",

    # Settings & Schools
    "school": "school_life",
    "school life": "school_life",
    "high school": "school_life",
    "academy": "school_life",
    "college": "college_university",
    "university": "college_university",
    "campus": "college_university",
    "workplace": "workplace",
    "office": "workplace",
    "office worker": "workplace",
    "salaryman": "workplace",
    "ancient china": "ancient_china",
    "imperial china": "ancient_china",
    "feudal japan": "feudal_japan",
    "samurai": "feudal_japan",
    "space": "space",
    "outer space": "space",
    "fantasy world": "fantasy_world",
    "dystopian": "dystopian",
    "dystopia": "dystopian",
    "post apocalyptic": "post_apocalyptic",
    "post apocalypse": "post_apocalyptic",

    # Demographics
    "shounen": "shounen",
    "shonen": "shounen",
    "shoujo": "shoujo",
    "shojo": "shoujo",
    "seinen": "seinen",
    "josei": "josei",
    "kids": "kids",
    "children": "kids",

    # Relationships & Tropes
    "enemies to lovers": "enemies_to_lovers",
    "friends to lovers": "friends_to_lovers",
    "childhood friends": "childhood_friends",
    "childhood friend": "childhood_friends",
    "slow burn": "slow_burn",
    "fake relationship": "fake_relationship",
    "pretend relationship": "fake_relationship",
    "contract marriage": "contract_marriage",
    "fake marriage": "contract_marriage",
    "age gap": "age_gap",
    "love triangle": "love_triangle",
    "harem": "harem",
    "female harem": "harem",
    "reverse harem": "reverse_harem",
    "male harem": "reverse_harem",

    # Power & Progression Tropes
    "op protagonist": "overpowered_protagonist",
    "overpowered protagonist": "overpowered_protagonist",
    "op mc": "overpowered_protagonist",
    "overpowered": "overpowered_protagonist",
    "dungeon": "dungeon_gate",
    "dungeons": "dungeon_gate",
    "gate": "dungeon_gate",
    "gates": "dungeon_gate",
    "dungeon gate": "dungeon_gate",
    "system": "system_level_up",
    "level up": "system_level_up",
    "leveling": "system_level_up",
    "game system": "system_level_up",
    "status window": "system_level_up",
    "second chance": "second_chance",
    "villainess": "reborn_as_a_villainess",
    "villainess noble": "reborn_as_a_villainess",
    "reborn as a villainess": "reborn_as_a_villainess",
    "otome game": "reborn_as_a_villainess",
    "secret identity": "secret_identity",
    "hidden identity": "secret_identity",
    "time skip": "time_skip",

    # Martial Arts & Murim
    "martial arts": "martial_arts",
    "murim": "martial_arts",
    "wuxia": "martial_arts",
    "xianxia": "martial_arts",
    "cultivation": "martial_arts",

    # Formats
    "manga": "manga",
    "manhwa": "manhwa",
    "korean": "manhwa",
    "manhua": "manhua",
    "chinese": "manhua",
    "webtoon": "webtoon",
    "web comic": "webtoon",
    "one shot": "one_shot",
    "oneshot": "one_shot",
    "anthology": "anthology",
    "long strip": "long_strip",
    "full color": "full_color",
    "colored": "full_color",

    # Standard Genres
    "action": "action",
    "adventure": "adventure",
    "comedy": "comedy",
    "drama": "drama",
    "fantasy": "fantasy",
    "horror": "horror",
    "mystery": "mystery",
    "psychological": "psychological",
    "romance": "romance",
    "sci fi": "sci_fi",
    "scifi": "sci_fi",
    "science fiction": "sci_fi",
    "slice of life": "slice_of_life",
    "sol": "slice_of_life",
    "sports": "sports",
    "sport": "sports",
    "supernatural": "supernatural",
    "thriller": "thriller",
    "suspense": "thriller",
    "tragedy": "tragedy",
    "mecha": "mecha",
    "robots": "mecha",
    "music": "music",
    "crime": "crime",
    "mafia": "crime",
    "yakuza": "crime",
    "ecchi": "ecchi",
    "mahou shoujo": "mahou_shoujo",
    "magical girl": "mahou_shoujo",
    "magic": "magic",
    "monsters": "monsters",
    "monster": "monsters",
    "demons": "demons",
    "demon": "demons",
    "superpowers": "superpowers",
    "super power": "superpowers",
    "virtual reality": "virtual_reality",
    "vr": "virtual_reality",
    "vrmmo": "virtual_reality",
    "video games": "video_games",
    "gaming": "video_games",
    "survival": "survival",
    "revenge": "revenge",
    "vengeance": "revenge",
    "underdog": "underdog",
    "cyberpunk": "cyberpunk",
    "steampunk": "steampunk",
    "historical": "historical",
    "military": "military",
    "parody": "parody"
}

# Pre-compile normalized alias lookup table
ALIAS_MAP: Dict[str, str] = {}

for _raw_alias, _slug in RAW_ALIAS_DEFINITIONS.items():
    _norm_alias = normalize_tag_input(_raw_alias)
    if _slug not in CANONICAL_VOCABULARY:
        raise ValueError(f"Alias '{_raw_alias}' references non-existent canonical slug '{_slug}'")
    ALIAS_MAP[_norm_alias] = _slug

# Also ensure every canonical name and slug is registered as self-referencing alias
for _slug, _tag in CANONICAL_VOCABULARY.items():
    ALIAS_MAP[normalize_tag_input(_tag.name)] = _slug
    ALIAS_MAP[normalize_tag_input(_slug)] = _slug

def resolve_canonical_tag(raw_name: Optional[str]) -> Optional[CanonicalTag]:
    """
    Resolves any raw source tag, genre, or alias into its controlled CanonicalTag.
    
    Returns:
        CanonicalTag instance if resolved.
        None if the tag is unmapped or unknown.
    
    Important: Unmapped source tags must NOT be discarded or deleted.
    They should remain preserved in the raw metadata array/object.
    """
    if not raw_name:
        return None
    normalized = normalize_tag_input(raw_name)
    slug = ALIAS_MAP.get(normalized)
    if not slug:
        return None
    return get_tag_by_slug(slug)
