"""
External Gap Taxonomy Mapper.

Provides safe, deterministic mappings from external provider tags/categories
(MangaUpdates, AniList, MangaDex, Wikidata) to the canonical tag vocabulary,
specifically for the gap-only evaluation pilot.

Classifications:
- EXACT: Direct semantic identity
- STRONG: Unambiguous domain equivalent
- PARTIAL: Related concept, but insufficient on its own (rejected for production without rules/ML)
- None: Unmapped or explicitly rejected keyword leap

PRODUCTION SAFETY POLICY FOR FORMATS (manga, manhwa, manhua):
- SAFE_TO_WRITE is strictly restricted to verified external API metadata from:
    1. MangaUpdates structured `type`
    2. AniList structured `countryOfOrigin`
    3. MangaDex structured `originalLanguage`
  tied to a verified entity (DIRECT_ID or CROSS_REFERENCE_ID).
- Script detection (Hangul, Hanzi, Kana) is local heuristic only and MUST NEVER produce SAFE_TO_WRITE.
- Default assumptions (e.g. assuming 'JP' when metadata is missing) are strictly forbidden.
- Unknown/missing format must remain unresolved/None.
"""

import re
from typing import Optional, Tuple, Dict, Any, List


def parse_mu_id(raw_id: Any) -> Optional[int]:
    """Parse MangaUpdates ID from numeric string or MangaDex base36 string."""
    if not raw_id:
        return None
    s = str(raw_id).strip()
    if s.isdigit():
        return int(s)
    # Check if base36
    if re.fullmatch(r"[0-9a-zA-Z]+", s):
        try:
            return int(s, 36)
        except ValueError:
            return None
    return None


def map_external_gap_tag(source: str, raw_tag: str) -> Optional[Tuple[str, str]]:
    """
    Map an external category or tag to (canonical_tag_slug, match_quality).
    Match quality can be EXACT, STRONG, or PARTIAL.
    Returns None if tag does not map safely to target gap tags.
    """
    if not raw_tag or not isinstance(raw_tag, str):
        return None

    val_norm = raw_tag.strip().lower()

    if source == "MangaUpdates":
        # 1. contract_marriage
        if val_norm in ["contract marriage", "marriage of convenience"]:
            return ("contract_marriage", "EXACT")
        if val_norm in ["arranged marriage"]:
            return ("contract_marriage", "STRONG")
        if val_norm in ["marriage", "married life"]:
            return ("contract_marriage", "PARTIAL")

        # 2. regression
        if val_norm in ["regression", "regressor"]:
            return ("regression", "EXACT")
        if val_norm in ["age regression"]:
            return ("regression", "PARTIAL")

        # 3. overpowered_protagonist
        if val_norm in ["overpowered protagonist", "overpowered main character"]:
            return ("overpowered_protagonist", "EXACT")
        if val_norm in ["strong to stronger"]:
            return ("overpowered_protagonist", "STRONG")

        # 4. enemies_to_lovers
        if val_norm in ["enemies become lovers", "enemies-to-lovers"]:
            return ("enemies_to_lovers", "EXACT")
        if val_norm in ["rivals become lovers", "childhood friends become enemies"]:
            return ("enemies_to_lovers", "STRONG")

        # 5. friends_to_lovers
        if val_norm in ["friends become lovers", "childhood friends become lovers"]:
            return ("friends_to_lovers", "EXACT")
        if val_norm in ["friends to lovers"]:
            return ("friends_to_lovers", "EXACT")

        # 6. slow_burn
        if val_norm in ["slow burn", "slow burn romance"]:
            return ("slow_burn", "EXACT")
        if val_norm in ["slow romance"]:
            return ("slow_burn", "STRONG")

        # 7. childhood_friends
        if val_norm in ["childhood friend/s", "childhood friend", "childhood friends"]:
            return ("childhood_friends", "EXACT")

        # 8. second_chance
        if val_norm in ["second chance", "second chance romance"]:
            return ("second_chance", "EXACT")

        # 9. system_level_up
        if val_norm in ["level system", "game system", "status window"]:
            return ("system_level_up", "EXACT")
        if val_norm in ["system", "level up", "numerical stats"]:
            return ("system_level_up", "STRONG")

        # 10. secret_identity
        if val_norm in ["secret identity", "hidden identity"]:
            return ("secret_identity", "EXACT")
        if val_norm in ["hidden abilities", "secret past"]:
            return ("secret_identity", "PARTIAL")

        # 11. underdog
        if val_norm in ["underdog"]:
            return ("underdog", "EXACT")
        if val_norm in ["weak to strong"]:
            return ("underdog", "STRONG")

        # 12. fantasy_world
        if val_norm in ["alternate world", "fantasy world"]:
            return ("fantasy_world", "EXACT")
        if val_norm == "urban fantasy":
            return ("fantasy_world", "PARTIAL")

        # 13, 14, 15. Formats (from MangaUpdates structured type)
        if val_norm == "manga":
            return ("manga", "EXACT")
        if val_norm == "manhwa":
            return ("manhwa", "EXACT")
        if val_norm == "manhua":
            return ("manhua", "EXACT")

    elif source == "AniList":
        # Country of Origin -> format
        if val_norm == "jp":
            return ("manga", "EXACT")
        if val_norm == "kr":
            return ("manhwa", "EXACT")
        if val_norm == "cn":
            return ("manhua", "EXACT")

    elif source == "MangaDex":
        # Original language -> format
        if val_norm == "ja":
            return ("manga", "EXACT")
        if val_norm == "ko":
            return ("manhwa", "EXACT")
        if val_norm == "zh":
            return ("manhua", "EXACT")

    return None


def classify_format_candidate(
    source: str,
    raw_value: Optional[str],
    match_method: str,
    is_verified_external: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Classifies format evidence (manga, manhwa, manhua) into a production-safe candidate record.

    HARD RULES:
    1. Only verified external metadata from MangaUpdates, AniList, or MangaDex tied
       to a verified entity can produce SAFE_TO_WRITE.
    2. Local script detection (Hangul, Hanzi, Kana) or title heuristics must NEVER
       produce SAFE_TO_WRITE. They are strictly classified as REVIEW_REQUIRED with
       source = "local_heuristic" and match_method = "SCRIPT_HEURISTIC".
    3. Missing or unverified format metadata returns None (unresolved).
       Defaulting to 'JP' or 'manga' is strictly forbidden.
    """
    if not raw_value or not isinstance(raw_value, str):
        return None

    raw_clean = raw_value.strip().lower()

    # Case 1: Verified External Metadata
    if is_verified_external and source in ("MangaUpdates", "AniList", "MangaDex"):
        mapped = map_external_gap_tag(source, raw_clean)
        if not mapped:
            return None

        canonical_tag, quality = mapped
        if canonical_tag not in ("manga", "manhwa", "manhua"):
            return None

        # Precedence: DIRECT_ID and CROSS_REFERENCE_ID can be SAFE_TO_WRITE.
        # TITLE_ALT_TITLE and FUZZY must be REVIEW_REQUIRED.
        if match_method in ("DIRECT_ID", "CROSS_REFERENCE_ID"):
            decision = "SAFE_TO_WRITE"
            confidence = 0.95
        else:
            decision = "REVIEW_REQUIRED"
            confidence = 0.65

        # Format evidence string
        if source == "MangaUpdates":
            evidence = f"Publication format categorized as {raw_value.title()} by MangaUpdates"
            source_tag = f"Type: {raw_value.title()}"
        elif source == "AniList":
            evidence = f"AniList countryOfOrigin: {raw_value.upper()}"
            source_tag = f"countryOfOrigin: {raw_value.upper()}"
        else:  # MangaDex
            evidence = f"MangaDex originalLanguage: {raw_value.lower()}"
            source_tag = f"originalLanguage: {raw_value.lower()}"

        return {
            "canonical_tag": canonical_tag,
            "source": source,
            "source_tag": source_tag,
            "mapping_type": quality.lower(),
            "match_method": match_method,
            "evidence": evidence,
            "quality": quality,
            "confidence": confidence,
            "decision": decision,
            "is_verified_external": True
        }

    # Case 2: Local Heuristic (Script Detection / Romaji Keyword)
    if source == "local_heuristic" or match_method == "SCRIPT_HEURISTIC":
        # Only explicit Hangul, Hanzi, Kana can produce a heuristic candidate
        if raw_clean in ("kr", "korean", "hangul"):
            canonical_tag = "manhwa"
        elif raw_clean in ("cn", "chinese", "hanzi"):
            canonical_tag = "manhua"
        elif raw_clean in ("jp", "japanese", "kana"):
            canonical_tag = "manga"
        else:
            return None

        return {
            "canonical_tag": canonical_tag,
            "source": "local_heuristic",
            "source_tag": f"script_detected: {raw_clean.upper()}",
            "mapping_type": "partial",
            "match_method": "SCRIPT_HEURISTIC",
            "evidence": f"Local title script detection ({raw_clean.upper()}); unverified by external API",
            "quality": "PARTIAL",
            "confidence": 0.50,
            "decision": "REVIEW_REQUIRED",  # NEVER SAFE_TO_WRITE
            "is_verified_external": False
        }

    # Any other case or unknown format remains unresolved
    return None


def resolve_format_from_script(
    title_native: Optional[str],
    title_romaji: Optional[str]
) -> Optional[Dict[str, Any]]:
    """
    Examines title text for non-Latin script signals.
    
    CRITICAL:
    - Never defaults to 'JP' or 'manga'.
    - If native text is Latin/English, absent, or ambiguous, returns None (unresolved).
    - Detected scripts are labeled source='local_heuristic' and decision='REVIEW_REQUIRED'.
    """
    if title_native and isinstance(title_native, str):
        t_nat = title_native.strip()
        # Hangul -> Korean (manhwa)
        if re.search(r"[\uac00-\ud7a3]", t_nat):
            return classify_format_candidate("local_heuristic", "KR", "SCRIPT_HEURISTIC", is_verified_external=False)
        # Hanzi without Kana -> Chinese (manhua)
        if re.search(r"[\u4e00-\u9fff]", t_nat) and not re.search(r"[\u3040-\u30ff]", t_nat):
            return classify_format_candidate("local_heuristic", "CN", "SCRIPT_HEURISTIC", is_verified_external=False)
        # Hiragana or Katakana -> Japanese (manga)
        if re.search(r"[\u3040-\u30ff]", t_nat):
            return classify_format_candidate("local_heuristic", "JP", "SCRIPT_HEURISTIC", is_verified_external=False)

    if title_romaji and isinstance(title_romaji, str):
        t_rom = title_romaji.strip().lower()
        if any(k in t_rom for k in ["manhwa", "geun", "yeong", "hyuk", "jin-woo"]):
            return classify_format_candidate("local_heuristic", "KR", "SCRIPT_HEURISTIC", is_verified_external=False)

    # NO DEFAULT ASSUMPTION! English/Latin-only or missing script remains unresolved.
    return None


def detect_conflicts(tag_instances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Given a list of extracted external tag dictionaries for a title,
    detect mutually exclusive conflicts (e.g. publication formats manga vs manhwa vs manhua).
    Returns list of records updated with CONFLICT status if conflicting.
    All conflicting candidates are downgraded to REVIEW_REQUIRED and NEVER SAFE_TO_WRITE.
    """
    format_tags = set(r["canonical_tag"] for r in tag_instances if r.get("canonical_tag") in ("manga", "manhwa", "manhua"))
    has_conflict = len(format_tags) > 1

    updated = []
    for r in tag_instances:
        rec = dict(r)
        if has_conflict and rec.get("canonical_tag") in ("manga", "manhwa", "manhua"):
            rec["match_status"] = "CONFLICT"
            rec["decision"] = "REVIEW_REQUIRED"
            rec["confidence"] = min(rec.get("confidence", 0.60), 0.60)
            rec["external_evidence"] = f"{rec.get('external_evidence', '')} [CONFLICT: sources disagree on format ({','.join(sorted(format_tags))})]"
        updated.append(rec)
    return updated
