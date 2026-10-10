"""
Rule Definitions for Deterministic Metadata Tag Enrichment.

Enforces:
1. Every target tag MUST exist in the controlled CanonicalTag taxonomy.
2. Evidence quality hierarchy: explicit metadata > strong multi-word phrases > corroborating keywords.
3. Guardrails against ambiguous single-word false positives.
4. Strict determinism without external dependencies or LLMs.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Pattern
import re
from .vocabulary import CANONICAL_VOCABULARY, get_tag_by_slug

@dataclass(frozen=True)
class EnrichmentRule:
    """
    Deterministic tag inference rule.
    
    Attributes:
        rule_id: Unique identifier for audit and provenance (e.g. 'RULE-BL-001').
        target_slug: Canonical tag slug. Must exist in CANONICAL_VOCABULARY.
        confidence: Confidence score strictly between 0.0 and 1.0.
        description: Explainable rationale for the rule.
        strong_patterns: Patterns in text (synopsis/titles) sufficient on their own.
        corroborating_patterns: Terms requiring at least min_corroborating matches.
        min_corroborating: Threshold of distinct corroborating patterns required.
        genre_triggers: Exact raw genre matches that trigger this rule.
        tag_triggers: Exact raw tag names that trigger this rule.
        negative_patterns: Patterns that prevent rule activation to avoid false positives.
    """
    rule_id: str
    target_slug: str
    confidence: float
    description: str
    strong_patterns: List[Pattern] = field(default_factory=list)
    corroborating_patterns: List[Pattern] = field(default_factory=list)
    min_corroborating: int = 2
    genre_triggers: List[str] = field(default_factory=list)
    tag_triggers: List[str] = field(default_factory=list)
    negative_patterns: List[Pattern] = field(default_factory=list)

    def __post_init__(self):
        if not get_tag_by_slug(self.target_slug):
            raise ValueError(f"Rule '{self.rule_id}' specifies unknown canonical slug '{self.target_slug}'")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Rule '{self.rule_id}' confidence {self.confidence} must be between 0.0 and 1.0")


def _p(pattern_str: str) -> Pattern:
    """Helper to compile regex pattern with word boundaries and case insensitivity."""
    return re.compile(pattern_str, re.IGNORECASE)


# ─────────────────────────────────────────────────────────────────────────────
# CONTROLLED RULE REGISTRY
# ─────────────────────────────────────────────────────────────────────────────

RULES: List[EnrichmentRule] = [
    # ── 1. BOYS' LOVE (Theme) ────────────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-BL-001",
        target_slug="boys_love",
        confidence=0.98,
        description="Explicit Boys' Love / Yaoi / Shounen Ai tag or title keyword",
        genre_triggers=["Boys Love", "Boys' Love", "Yaoi", "Shounen Ai", "Shonen Ai", "Danmei"],
        tag_triggers=["Boys Love", "Boys' Love", "Yaoi", "Shounen Ai", "Shonen Ai", "Danmei", "BL"],
        strong_patterns=[
            _p(r"\bboys'?\s+love\b"),
            _p(r"\b(?:shounen|shonen)\s*ai\b"),
            _p(r"\byaoi\b"),
            _p(r"\bdanmei\b"),
            _p(r"\b(?:male-male|boy-boy|man-man)\s+(?:romance|love|relationship)\b"),
        ]
    ),
    EnrichmentRule(
        rule_id="RULE-BL-002",
        target_slug="boys_love",
        confidence=0.92,
        description="Synopsis describes explicit male-male romance or attraction",
        strong_patterns=[
            _p(r"\b(?:two|both)\s+(?:boys|men|male students|male classmates)\s+(?:\w+\s+){0,2}fall(?:s|ing)?\s+in\s+love\b"),
            _p(r"\bhis\s+feelings\s+for\s+(?:his|another)\s+(?:male classmate|guy|man|boy)\b"),
            _p(r"\bfall(?:s|ing)?\s+for\s+(?:his|another)\s+(?:male classmate|guy|man|boy)\b"),
            _p(r"\bromance\s+between\s+(?:two|both)\s+(?:young\s+)?(?:men|boys|male students)\b"),
            _p(r"\battraction\s+between\s+(?:two|both)\s+(?:young\s+)?(?:men|boys|male students)\b"),
            _p(r"\blove\s+story\s+between\s+(?:two|both)\s+(?:young\s+)?(?:men|boys)\b"),
        ]
    ),

    # ── 2. GIRLS' LOVE (Theme) ───────────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-GL-001",
        target_slug="girls_love",
        confidence=0.98,
        description="Explicit Girls' Love / Yuri / Shoujo Ai tag or title keyword",
        genre_triggers=["Girls Love", "Girls' Love", "Yuri", "Shoujo Ai", "Shojo Ai", "Baihe"],
        tag_triggers=["Girls Love", "Girls' Love", "Yuri", "Shoujo Ai", "Shojo Ai", "Baihe", "GL"],
        strong_patterns=[
            _p(r"\bgirls'?\s+love\b"),
            _p(r"\b(?:shoujo|shojo)\s*ai\b"),
            _p(r"\byuri\b"),
            _p(r"\bbaihe\b"),
            _p(r"\b(?:female-female|girl-girl|woman-woman)\s+(?:romance|love|relationship)\b"),
        ]
    ),
    EnrichmentRule(
        rule_id="RULE-GL-002",
        target_slug="girls_love",
        confidence=0.92,
        description="Synopsis describes explicit female-female romance or attraction",
        strong_patterns=[
            _p(r"\b(?:two|both)\s+(?:girls|women|female students|female classmates)\s+(?:\w+\s+){0,2}fall(?:s|ing)?\s+in\s+love\b"),
            _p(r"\bher\s+feelings\s+for\s+(?:her|another)\s+(?:female classmate|girl|woman)\b"),
            _p(r"\bfall(?:s|ing)?\s+for\s+(?:her|another)\s+(?:female classmate|girl|woman)\b"),
            _p(r"\bromance\s+between\s+(?:two|both)\s+(?:young\s+)?(?:women|girls|female students)\b"),
            _p(r"\battraction\s+between\s+(?:two|both)\s+(?:young\s+)?(?:women|girls|female students)\b"),
            _p(r"\blove\s+story\s+between\s+(?:two|both)\s+(?:young\s+)?(?:women|girls)\b"),
        ]
    ),

    # ── 3. SCHOOL LIFE (Setting) ─────────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-SETTING-SCHOOL-001",
        target_slug="school_life",
        confidence=0.92,
        description="Strong academic setting phrases in synopsis",
        strong_patterns=[
            _p(r"\bhigh\s+school\s+(?:student|life|freshman|senior|years|days|campus|club)\b"),
            _p(r"\bmiddle\s+school\s+(?:student|life|graduate)\b"),
            _p(r"\bstudent\s+council\s+(?:president|member|room)\b"),
            _p(r"\btransfer\s+student\b"),
            _p(r"\btransfers?\s+to\s+a\s+new\s+school\b"),
            _p(r"\battends?\s+(?:a\s+prestigious|an\s+elite)\s+academy\b"),
            _p(r"\bhomeroom\s+teacher\b"),
            _p(r"\bschool\s+festival\b"),
        ],
        negative_patterns=[
            _p(r"\b(?:school\s+of\s+(?:magic|sorcery|thought|martial\s+arts)|old[- ]school|dropped\s+out\s+of\s+school)\b")
        ]
    ),
    EnrichmentRule(
        rule_id="RULE-SETTING-SCHOOL-002",
        target_slug="school_life",
        confidence=0.85,
        description="Corroborating school environment terms (requires at least 2 distinct academic indicators)",
        corroborating_patterns=[
            _p(r"\bhigh\s+school\b"),
            _p(r"\bclassroom\b"),
            _p(r"\bclassmates?\b"),
            _p(r"\bschoolmate\b"),
            _p(r"\bschool\s+uniform\b"),
            _p(r"\bschool\s+roof(?:top)?\b"),
            _p(r"\bafter[- ]school\b"),
        ],
        min_corroborating=2,
        negative_patterns=[
            _p(r"\b(?:school\s+of\s+(?:magic|sorcery|thought|martial\s+arts)|old[- ]school)\b")
        ]
    ),

    # ── 4. COLLEGE / UNIVERSITY (Setting) ────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-SETTING-COLLEGE-001",
        target_slug="college_university",
        confidence=0.92,
        description="Higher education campus life indicators",
        strong_patterns=[
            _p(r"\b(?:college|university)\s+(?:student|life|freshman|senior|campus|dorm|professor)\b"),
            _p(r"\battending\s+(?:college|university)\b"),
            _p(r"\bentering\s+(?:college|university)\b"),
        ]
    ),

    # ── 5. WORKPLACE (Setting) ───────────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-SETTING-WORKPLACE-001",
        target_slug="workplace",
        confidence=0.90,
        description="Office and corporate workplace setting indicators",
        strong_patterns=[
            _p(r"\boffice\s+worker\b"),
            _p(r"\bcorporate\s+employee\b"),
            _p(r"\bworkplace\s+romance\b"),
            _p(r"\boffice\s+romance\b"),
            _p(r"\bworks?\s+at\s+an?\s+(?:office|agency|firm|company|corporation)\b"),
            _p(r"\bcolleague\s+and\s+boss\b"),
            _p(r"\bboss\s+and\s+(?:his|her)?\s*subordinate\b"),
        ]
    ),

    # ── 6. ISEKAI (Theme) ────────────────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-THEME-ISEKAI-001",
        target_slug="isekai",
        confidence=0.95,
        description="Transported or summoned to a parallel/another world",
        genre_triggers=["Isekai"],
        tag_triggers=["Isekai", "Transported to Another World"],
        strong_patterns=[
            _p(r"\bisekai\b"),
            _p(r"\b(?:transported|summoned|teleported|sent)\s+to\s+(?:another|a\s+parallel|a\s+different|a\s+fantasy)\s+world\b"),
            _p(r"\bwakes?\s+up\s+in\s+(?:another|a\s+parallel|a\s+different|a\s+fantasy)\s+world\b"),
            _p(r"\bsummoned\s+as\s+a\s+hero\s+to\s+another\s+world\b"),
        ]
    ),

    # ── 7. REINCARNATION (Theme) ─────────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-THEME-REINCARNATION-001",
        target_slug="reincarnation",
        confidence=0.94,
        description="Rebirth into a new body or world after death",
        tag_triggers=["Reincarnation", "Transmigration", "Reborn"],
        strong_patterns=[
            _p(r"\breincarnat(?:ed|ion|es)\b"),
            _p(r"\breborn\s+(?:as|into|in)\b"),
            _p(r"\btransmigrat(?:ed|ion|es)\s+into\b"),
            _p(r"\bdies?\s+and\s+(?:is\s+reborn|wakes?\s+up\s+as)\b"),
        ]
    ),

    # ── 8. REGRESSION (Theme) ────────────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-THEME-REGRESSION-001",
        target_slug="regression",
        confidence=0.95,
        description="Time reversal returning to past self with future knowledge",
        tag_triggers=["Regression", "Time Reversal", "Returner"],
        strong_patterns=[
            _p(r"\bregress(?:ed|ion|or|es)\b"),
            _p(r"\breturn(?:ed|ing|s)?\s+to\s+(?:the\s+past|his\s+past\s+self|her\s+past\s+self|their\s+past)\b"),
            _p(r"\btime\s+(?:rewound|reversed|reversal)\b"),
            _p(r"\bsent\s+back\s+(?:in\s+time|\d+\s+years)\b"),
            _p(r"\bwakes?\s+up\s+\d+\s+years\s+(?:in\s+the\s+past|before\s+the\s+(?:apocalypse|cataclysm|disaster|war))\b"),
            _p(r"\bsecond\s+chance\s+at\s+life\s+with\s+(?:past|future)\s+memories\b"),
        ]
    ),

    # ── 9. TIME TRAVEL (Theme) ───────────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-THEME-TIME-TRAVEL-001",
        target_slug="time_travel",
        confidence=0.90,
        description="Temporal loops or time travel mechanisms",
        tag_triggers=["Time Travel", "Time Loop"],
        strong_patterns=[
            _p(r"\btime\s+travel(?:er|ing)?\b"),
            _p(r"\btravel(?:s|ed|ing)?\s+back\s+in\s+time\b"),
            _p(r"\btime\s+loop\b"),
            _p(r"\btime\s+leap\b"),
            _p(r"\brepeating\s+the\s+same\s+day\b"),
        ]
    ),

    # ── 10. ROMANCE (Genre) ──────────────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-GENRE-ROMANCE-001",
        target_slug="romance",
        confidence=0.88,
        description="Strong multi-word romantic narrative patterns (guarded against single 'love')",
        strong_patterns=[
            _p(r"\bfall(?:s|ing|en)?\s+in\s+love\b"),
            _p(r"\bconfess(?:es|ed|ing)?\s+(?:his|her|their)?\s*feelings\b"),
            _p(r"\bromantic\s+(?:feelings|relationship|attraction|tension|comedy)\b"),
            _p(r"\blove\s+confession\b"),
            _p(r"\bmutual\s+feelings\b"),
            _p(r"\bbecome\s+more\s+than\s+friends\b"),
        ],
        negative_patterns=[
            _p(r"\b(?:no\s+romance|platonic\s+only)\b")
        ]
    ),

    # ── 11. ENEMIES TO LOVERS (Relationship) ─────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-REL-ENEMIES-TO-LOVERS-001",
        target_slug="enemies_to_lovers",
        confidence=0.92,
        description="Hostile rivals or enemies developing romantic feelings",
        strong_patterns=[
            _p(r"\benemies\s+to\s+lovers\b"),
            _p(r"\brivals?\s+to\s+lovers\b"),
            _p(r"\bfrom\s+enemies\s+to\s+(?:lovers|partners\s+in\s+love)\b"),
            _p(r"\bbitter\s+rivals?\s+(?:fall|falling)\s+in\s+love\b"),
            _p(r"\bhatred\s+turns?\s+(?:in)?to\s+love\b"),
        ]
    ),

    # ── 12. FRIENDS TO LOVERS (Relationship) ─────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-REL-FRIENDS-TO-LOVERS-001",
        target_slug="friends_to_lovers",
        confidence=0.92,
        description="Platonic companions transitioning into romantic relationship",
        strong_patterns=[
            _p(r"\bfriends\s+to\s+lovers\b"),
            _p(r"\bfrom\s+(?:best\s+)?friends\s+to\s+lovers\b"),
            _p(r"\bplatonic\s+friendship\s+turns?\s+romantic\b"),
            _p(r"\bfell\s+in\s+love\s+with\s+(?:his|her)\s+(?:best|childhood)\s+friend\b"),
            _p(r"\bchildhood\s+friends?\s+fall(?:s|ing)?\s+in\s+love\b"),
        ]
    ),

    # ── 13. SLOW BURN (Relationship) ─────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-REL-SLOW-BURN-001",
        target_slug="slow_burn",
        confidence=0.88,
        description="Gradual romantic progression and developing affection",
        strong_patterns=[
            _p(r"\bslow\s+burn\b"),
            _p(r"\bgradually\s+fall(?:s|ing)?\s+in\s+love\b"),
            _p(r"\bslowly\s+developing\s+(?:feelings|romance|affection)\b"),
            _p(r"\bgradual\s+romantic\s+progression\b"),
        ]
    ),

    # ── 14. FAKE RELATIONSHIP (Relationship) ─────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-REL-FAKE-RELATIONSHIP-001",
        target_slug="fake_relationship",
        confidence=0.92,
        description="Pretending to date or act as lovers for social/practical reasons",
        strong_patterns=[
            _p(r"\bfake\s+relationship\b"),
            _p(r"\bpretend(?:ing)?\s+to\s+date\b"),
            _p(r"\bpretend(?:ing)?\s+to\s+be\s+(?:lovers|a\s+couple|dating)\b"),
            _p(r"\bfake\s+dating\b"),
            _p(r"\bcontract\s+relationship\b"),
        ]
    ),

    # ── 15. CONTRACT MARRIAGE (Relationship) ─────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-REL-CONTRACT-MARRIAGE-001",
        target_slug="contract_marriage",
        confidence=0.92,
        description="Marriage formed on contractual, political, or business grounds",
        strong_patterns=[
            _p(r"\bcontract\s+marriage\b"),
            _p(r"\bmarriage\s+of\s+convenience\b"),
            _p(r"\bcontractual\s+marriage\b"),
            _p(r"\bsham\s+marriage\b"),
        ]
    ),

    # ── 16. CHILDHOOD FRIENDS (Relationship) ─────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-REL-CHILDHOOD-FRIENDS-001",
        target_slug="childhood_friends",
        confidence=0.90,
        description="Shared childhood history between central characters",
        tag_triggers=["Childhood Friends", "Childhood Friend"],
        strong_patterns=[
            _p(r"\bchildhood\s+friends?\b"),
            _p(r"\bknown\s+each\s+other\s+since\s+childhood\b"),
            _p(r"\bfriends\s+since\s+(?:they\s+were\s+)?(?:kids|children)\b"),
        ]
    ),

    # ── 17. LOVE TRIANGLE (Relationship) ─────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-REL-LOVE-TRIANGLE-001",
        target_slug="love_triangle",
        confidence=0.90,
        description="Competing romantic pursuits among three individuals",
        tag_triggers=["Love Triangle"],
        strong_patterns=[
            _p(r"\blove\s+triangle\b"),
            _p(r"\btorn\s+between\s+(?:two|both)\s+(?:men|women|girls|boys|suitors)\b"),
            _p(r"\bboth\s+competing\s+for\s+(?:his|her)\s+(?:heart|affections?)\b"),
        ]
    ),

    # ── 18. DUNGEON / GATE (Trope) ───────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-TROPE-DUNGEON-GATE-001",
        target_slug="dungeon_gate",
        confidence=0.92,
        description="Dimensional portals or dungeons spawning monsters into society",
        tag_triggers=["Dungeon", "Dungeons", "Gate", "Hunter"],
        strong_patterns=[
            _p(r"\bdungeons?\s+and\s+monsters\s+(?:appeared|emerged)\b"),
            _p(r"\bmysterious\s+gates?\s+(?:appeared|opened)\b"),
            _p(r"\bdungeon\s+hunter\b"),
            _p(r"\bawakened\s+as\s+a\s+(?:hunter|player)\b"),
            _p(r"\b(?:s|a|b|c|d|e|f)-rank\s+hunter\b"),
        ]
    ),

    # ── 19. SYSTEM / LEVEL UP (Trope) ────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-TROPE-SYSTEM-LEVEL-UP-001",
        target_slug="system_level_up",
        confidence=0.92,
        description="Status windows, leveling up, and numerical game systems",
        tag_triggers=["System", "Level Up", "Status Window"],
        strong_patterns=[
            _p(r"\bstatus\s+window\b"),
            _p(r"\blevel(?:ing)?\s+up\s+system\b"),
            _p(r"\bmysterious\s+system\s+(?:appeared|notif(?:ied|ication))\b"),
            _p(r"\bquest\s+notifications?\b"),
            _p(r"\bgame-like\s+status\b"),
        ]
    ),

    # ── 20. REBORN AS A VILLAINESS (Trope) ───────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-TROPE-VILLAINESS-001",
        target_slug="reborn_as_a_villainess",
        confidence=0.96,
        description="Transmigration into the villainess of an otome game or fantasy novel",
        tag_triggers=["Villainess", "Reborn as a Villainess"],
        strong_patterns=[
            _p(r"\b(?:reborn|reincarnated|transmigrated)\s+as\s+(?:the|a)\s+villainess\b"),
            _p(r"\bvillainess\s+of\s+(?:the|an)\s+otome\s+game\b"),
            _p(r"\bavoid\s+(?:her|the)\s+(?:death\s+flags|bad\s+ending)\s+as\s+(?:the|a)\s+villainess\b"),
        ]
    ),

    # ── 21. MARTIAL ARTS (Theme) ─────────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-THEME-MARTIAL-ARTS-001",
        target_slug="martial_arts",
        confidence=0.95,
        description="Murim, cultivation, or martial disciplines",
        genre_triggers=["Martial Arts"],
        tag_triggers=["Martial Arts", "Murim", "Cultivation", "Wuxia", "Xianxia"],
        strong_patterns=[
            _p(r"\bmurim\b"),
            _p(r"\bcultivation\s+world\b"),
            _p(r"\bmartial\s+arts\s+sect\b"),
            _p(r"\bwuxia\b"),
            _p(r"\bxianxia\b"),
            _p(r"\bmount\s+hua\s+sect\b"),
            _p(r"\bheavenly\s+demon\b"),
        ]
    ),

    # ── 22. DEMOGRAPHICS ─────────────────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-DEMO-SHOUNEN-001",
        target_slug="shounen",
        confidence=0.96,
        description="Targeted toward adolescent male readers",
        genre_triggers=["Shounen", "Shonen"],
        tag_triggers=["Shounen", "Shonen"],
    ),
    EnrichmentRule(
        rule_id="RULE-DEMO-SHOUJO-001",
        target_slug="shoujo",
        confidence=0.96,
        description="Targeted toward adolescent female readers",
        genre_triggers=["Shoujo", "Shojo"],
        tag_triggers=["Shoujo", "Shojo"],
    ),
    EnrichmentRule(
        rule_id="RULE-DEMO-SEINEN-001",
        target_slug="seinen",
        confidence=0.96,
        description="Targeted toward adult male readers (18+)",
        genre_triggers=["Seinen"],
        tag_triggers=["Seinen"],
    ),
    EnrichmentRule(
        rule_id="RULE-DEMO-JOSEI-001",
        target_slug="josei",
        confidence=0.96,
        description="Targeted toward adult female readers (18+)",
        genre_triggers=["Josei"],
        tag_triggers=["Josei"],
    ),

    # ── 23. FORMATS ──────────────────────────────────────────────────────────
    EnrichmentRule(
        rule_id="RULE-FORMAT-MANHWA-001",
        target_slug="manhwa",
        confidence=0.96,
        description="Korean comic publication format",
        tag_triggers=["Manhwa"],
        strong_patterns=[
            _p(r"\bmanhwa\b"),
        ]
    ),
    EnrichmentRule(
        rule_id="RULE-FORMAT-MANHUA-001",
        target_slug="manhua",
        confidence=0.96,
        description="Chinese comic publication format",
        tag_triggers=["Manhua"],
        strong_patterns=[
            _p(r"\bmanhua\b"),
        ]
    ),
    EnrichmentRule(
        rule_id="RULE-FORMAT-WEBTOON-001",
        target_slug="webtoon",
        confidence=0.94,
        description="Digital scroll webtoon comic format",
        tag_triggers=["Webtoon", "Long Strip"],
        strong_patterns=[
            _p(r"\bwebtoon\b"),
            _p(r"\bvertical\s+scroll\b"),
            _p(r"\btapas\s+original\b"),
            _p(r"\bwebtoon\s+original\b"),
        ]
    ),
]
