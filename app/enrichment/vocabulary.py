"""
Controlled Canonical Tag Vocabulary for Manga/Manhwa/Manhua Recommendation.

Enforces:
1. Stable lowercase snake_case slugs.
2. Unique canonical display names.
3. Categorization across: genre, theme, setting, demographic, relationship, trope, format.
4. Extensibility without tag duplication.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
import re

SLUG_PATTERN = re.compile(r'^[a-z0-9]+(?:_[a-z0-9]+)*$')

class TagCategory(str, Enum):
    GENRE = "genre"
    THEME = "theme"
    SETTING = "setting"
    DEMOGRAPHIC = "demographic"
    RELATIONSHIP = "relationship"
    TROPE = "trope"
    FORMAT = "format"

@dataclass(frozen=True)
class CanonicalTag:
    slug: str
    name: str
    category: TagCategory
    description: str = ""

# ─────────────────────────────────────────────────────────────────────────────
# Controlled Taxonomy Definitions
# ─────────────────────────────────────────────────────────────────────────────

_TAG_DEFINITIONS: List[CanonicalTag] = [
    # --- 1. GENRES ---
    CanonicalTag("action", "Action", TagCategory.GENRE, "Stories featuring high-energy conflict, battles, or martial sequences."),
    CanonicalTag("adventure", "Adventure", TagCategory.GENRE, "Journeys, quests, exploration, and unfamiliar lands."),
    CanonicalTag("comedy", "Comedy", TagCategory.GENRE, "Humorous situations, satire, and comedic timing."),
    CanonicalTag("drama", "Drama", TagCategory.GENRE, "Emotionally driven narrative exploring character depth and conflict."),
    CanonicalTag("fantasy", "Fantasy", TagCategory.GENRE, "Magic, mythical creatures, supernatural worldbuilding."),
    CanonicalTag("horror", "Horror", TagCategory.GENRE, "Fear, dread, grotesque imagery, or psychological terror."),
    CanonicalTag("mystery", "Mystery", TagCategory.GENRE, "Detective cases, unexplained occurrences, and investigative puzzle solving."),
    CanonicalTag("psychological", "Psychological", TagCategory.GENRE, "Mind games, mental instability, and internal psychological struggles."),
    CanonicalTag("romance", "Romance", TagCategory.GENRE, "Romantic attraction, romantic tension, and developing relationships."),
    CanonicalTag("sci_fi", "Sci-Fi", TagCategory.GENRE, "Science fiction, advanced technology, cybernetics, or space travel."),
    CanonicalTag("slice_of_life", "Slice of Life", TagCategory.GENRE, "Everyday domestic or mundane life experiences."),
    CanonicalTag("sports", "Sports", TagCategory.GENRE, "Competitive athletic sports, training, tournaments, or team dynamics."),
    CanonicalTag("supernatural", "Supernatural", TagCategory.GENRE, "Ghosts, spirits, deities, or unexplained occult forces."),
    CanonicalTag("thriller", "Thriller", TagCategory.GENRE, "High-stakes suspense, conspiracies, pacing, and tension."),
    CanonicalTag("tragedy", "Tragedy", TagCategory.GENRE, "Somber narratives involving devastating loss or sorrow."),
    CanonicalTag("mecha", "Mecha", TagCategory.GENRE, "Giant pilotable robotic exoskeletons or machinery."),
    CanonicalTag("music", "Music", TagCategory.GENRE, "Musical performances, bands, instruments, or sound artistry."),
    CanonicalTag("crime", "Crime", TagCategory.GENRE, "Criminal organizations, heists, mafias, or police investigations."),
    CanonicalTag("ecchi", "Ecchi", TagCategory.GENRE, "Provocative, suggestive, or comedic mild sexual themes."),

    # --- 2. THEMES ---
    CanonicalTag("boys_love", "Boys' Love", TagCategory.THEME, "Male-male romantic or emotional relationships (BL / Yaoi / Shounen Ai)."),
    CanonicalTag("girls_love", "Girls' Love", TagCategory.THEME, "Female-female romantic or emotional relationships (GL / Yuri / Shoujo Ai)."),
    CanonicalTag("isekai", "Isekai", TagCategory.THEME, "Transported, summoned, or reincarnated into an alternate/parallel universe."),
    CanonicalTag("reincarnation", "Reincarnation", TagCategory.THEME, "Rebirth into a new body or different world after death."),
    CanonicalTag("regression", "Regression", TagCategory.THEME, "Time reversal / returner returning to one's past self with future memories."),
    CanonicalTag("time_travel", "Time Travel", TagCategory.THEME, "Chronological movement forward, backward, or temporal loops."),
    CanonicalTag("martial_arts", "Martial Arts", TagCategory.THEME, "Hand-to-hand combat styles, Murim, cultivation, or martial disciplines."),
    CanonicalTag("historical", "Historical", TagCategory.THEME, "Set in recognizable historical eras or period pieces."),
    CanonicalTag("military", "Military", TagCategory.THEME, "Armed forces, wartime operations, and soldier regiments."),
    CanonicalTag("parody", "Parody", TagCategory.THEME, "Subversion, mockery, or comedic caricature of existing tropes."),
    CanonicalTag("magic", "Magic", TagCategory.THEME, "Spells, mana, arcane arts, or elemental sorcery."),
    CanonicalTag("monsters", "Monsters", TagCategory.THEME, "Beasts, mythical creatures, and monstrous entities."),
    CanonicalTag("demons", "Demons", TagCategory.THEME, "Fiends, devils, demon lords, and demonic realms."),
    CanonicalTag("superpowers", "Superpowers", TagCategory.THEME, "Extraordinary innate mutant, superhero, or metaphysical abilities."),
    CanonicalTag("virtual_reality", "Virtual Reality", TagCategory.THEME, "Full-dive simulated sensory technology and VRMMO worlds."),
    CanonicalTag("video_games", "Video Games", TagCategory.THEME, "Gamer culture, game mechanics, or living inside a video game."),
    CanonicalTag("survival", "Survival", TagCategory.THEME, "Struggling for life against death games, nature, or hostile environments."),
    CanonicalTag("revenge", "Revenge", TagCategory.THEME, "Vengeance, retribution, and paying back betrayal."),
    CanonicalTag("underdog", "Underdog", TagCategory.THEME, "Protagonist underestimated or mocked rising against the odds."),
    CanonicalTag("cyberpunk", "Cyberpunk", TagCategory.THEME, "High tech, low life, neon-lit dystopian corporate cities."),
    CanonicalTag("steampunk", "Steampunk", TagCategory.THEME, "Retro-futuristic steam-powered industrial technology."),
    CanonicalTag("mahou_shoujo", "Mahou Shoujo", TagCategory.THEME, "Magical girls transforming to combat evil."),

    # --- 3. SETTINGS ---
    CanonicalTag("school_life", "School Life", TagCategory.SETTING, "Set predominantly in high school, middle school, or academic academies."),
    CanonicalTag("college_university", "College / University", TagCategory.SETTING, "Higher education campus life and young adulthood."),
    CanonicalTag("workplace", "Workplace", TagCategory.SETTING, "Corporate offices, shops, culinary kitchens, or professional careers."),
    CanonicalTag("dystopian", "Dystopian", TagCategory.SETTING, "Oppressive, dehumanizing totalitarian or authoritarian regimes."),
    CanonicalTag("post_apocalyptic", "Post-Apocalyptic", TagCategory.SETTING, "Ruins of society following cataclysmic global collapse."),
    CanonicalTag("ancient_china", "Ancient China", TagCategory.SETTING, "Imperial dynasties, Murim, or historical Chinese cultural backdrops."),
    CanonicalTag("feudal_japan", "Feudal Japan", TagCategory.SETTING, "Samurai, ninja, shogunate, or historical Japanese eras."),
    CanonicalTag("space", "Space", TagCategory.SETTING, "Outer space, planetary colonies, and interstellar vessels."),
    CanonicalTag("fantasy_world", "Fantasy World", TagCategory.SETTING, "Fictional kingdoms, castles, and non-Earth medieval settings."),

    # --- 4. DEMOGRAPHICS ---
    CanonicalTag("shounen", "Shounen", TagCategory.DEMOGRAPHIC, "Targeted primarily toward adolescent male readers."),
    CanonicalTag("shoujo", "Shoujo", TagCategory.DEMOGRAPHIC, "Targeted primarily toward adolescent female readers."),
    CanonicalTag("seinen", "Seinen", TagCategory.DEMOGRAPHIC, "Targeted primarily toward adult men (18+)."),
    CanonicalTag("josei", "Josei", TagCategory.DEMOGRAPHIC, "Targeted primarily toward adult women (18+)."),
    CanonicalTag("kids", "Kids", TagCategory.DEMOGRAPHIC, "Targeted primarily toward children and young audiences."),

    # --- 5. RELATIONSHIPS ---
    CanonicalTag("enemies_to_lovers", "Enemies to Lovers", TagCategory.RELATIONSHIP, "Antagonists or hostile rivals developing genuine romantic affection."),
    CanonicalTag("friends_to_lovers", "Friends to Lovers", TagCategory.RELATIONSHIP, "Platonic companions or childhood friends transitioning into romance."),
    CanonicalTag("slow_burn", "Slow Burn", TagCategory.RELATIONSHIP, "Gradual, patient romantic pacing with prolonged emotional tension."),
    CanonicalTag("fake_relationship", "Fake Relationship", TagCategory.RELATIONSHIP, "Pretending to date, marry, or cohabitate for practical or social reasons."),
    CanonicalTag("age_gap", "Age Gap", TagCategory.RELATIONSHIP, "Significant age disparity between romantic partners."),
    CanonicalTag("love_triangle", "Love Triangle", TagCategory.RELATIONSHIP, "Competing romantic interests among three individuals."),
    CanonicalTag("harem", "Harem", TagCategory.RELATIONSHIP, "Protagonist romantically pursued by three or more female suitors."),
    CanonicalTag("reverse_harem", "Reverse Harem", TagCategory.RELATIONSHIP, "Protagonist romantically pursued by three or more male suitors."),
    CanonicalTag("childhood_friends", "Childhood Friends", TagCategory.RELATIONSHIP, "Characters with deep shared childhood upbringing."),
    CanonicalTag("contract_marriage", "Contract Marriage", TagCategory.RELATIONSHIP, "Marriage formed on legal, political, or business contracts."),

    # --- 6. TROPES ---
    CanonicalTag("overpowered_protagonist", "Overpowered Protagonist", TagCategory.TROPE, "Lead character whose strength vastly exceeds peers and challenges."),
    CanonicalTag("second_chance", "Second Chance", TagCategory.TROPE, "An opportunity to rewrite a failed life, relationship, or past regret."),
    CanonicalTag("dungeon_gate", "Dungeon / Gate", TagCategory.TROPE, "Dimensional portals or dungeons spawning monsters into modern society."),
    CanonicalTag("system_level_up", "System / Level Up", TagCategory.TROPE, "Game-like status windows, stat leveling, and numerical skill gains."),
    CanonicalTag("reborn_as_a_villainess", "Reborn as a Villainess", TagCategory.TROPE, "Reincarnated into the antagonist noblewoman of an otome game/novel."),
    CanonicalTag("secret_identity", "Secret Identity", TagCategory.TROPE, "Concealing true identity, rank, nobility, or powers from others."),
    CanonicalTag("time_skip", "Time Skip", TagCategory.TROPE, "Narrative jumps forward significantly in time."),

    # --- 7. FORMATS ---
    CanonicalTag("manga", "Manga", TagCategory.FORMAT, "Traditional Japanese comic publication, primarily right-to-left black-and-white."),
    CanonicalTag("manhwa", "Manhwa", TagCategory.FORMAT, "Korean comic publication, typically vertical scroll full-color webtoon."),
    CanonicalTag("manhua", "Manhua", TagCategory.FORMAT, "Chinese comic publication, often full-color digital or print."),
    CanonicalTag("webtoon", "Webtoon", TagCategory.FORMAT, "Digital scroll-optimized full-color comic strip format."),
    CanonicalTag("one_shot", "One-shot", TagCategory.FORMAT, "Standalone single-chapter complete story."),
    CanonicalTag("anthology", "Anthology", TagCategory.FORMAT, "Collection of independent short stories or multiple author contributions."),
    CanonicalTag("long_strip", "Long Strip", TagCategory.FORMAT, "Vertical seamless infinite-scroll panel format."),
    CanonicalTag("full_color", "Full Color", TagCategory.FORMAT, "Illustrated entirely in color rather than monochrome tones.")
]

# ─────────────────────────────────────────────────────────────────────────────
# Verification & Registry Construction
# ─────────────────────────────────────────────────────────────────────────────

CANONICAL_VOCABULARY: Dict[str, CanonicalTag] = {}
_NAME_TO_SLUG: Dict[str, str] = {}

for _t in _TAG_DEFINITIONS:
    if not SLUG_PATTERN.match(_t.slug):
        raise ValueError(f"Invalid canonical tag slug format '{_t.slug}'. Must be lowercase snake_case.")
    if _t.slug in CANONICAL_VOCABULARY:
        raise ValueError(f"Duplicate canonical tag slug detected: '{_t.slug}'")
    _lower_name = _t.name.lower().strip()
    if _lower_name in _NAME_TO_SLUG:
        raise ValueError(f"Duplicate canonical tag name detected: '{_t.name}' (slugs: {_NAME_TO_SLUG[_lower_name]}, {_t.slug})")

    CANONICAL_VOCABULARY[_t.slug] = _t
    _NAME_TO_SLUG[_lower_name] = _t.slug

def get_tag_by_slug(slug: str) -> Optional[CanonicalTag]:
    """Retrieve canonical tag by its stable slug."""
    if not slug:
        return None
    return CANONICAL_VOCABULARY.get(slug.lower().strip())

def get_tags_by_category(category: TagCategory) -> List[CanonicalTag]:
    """Retrieve all canonical tags under a specific category."""
    return [t for t in CANONICAL_VOCABULARY.values() if t.category == category]

def list_all_tags() -> List[CanonicalTag]:
    """Return all registered canonical tags."""
    return list(CANONICAL_VOCABULARY.values())
