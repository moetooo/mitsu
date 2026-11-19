import json
import unittest
from app.services.format import build_format_sql_condition, infer_format_type
from app.services.query_filters import build_genre_sql_condition, generate_filter_hash
from app.models import RecommendFilters

class TestFilterBuilder(unittest.TestCase):
    """Unit tests for SQL filter condition builders and format inference."""

    # -------------------------------------------------------------
    # 1. Format SQL Condition Tests
    # -------------------------------------------------------------
    def test_build_format_sql_manga(self):
        """The manga filter is a comparison against the stored column (ARCH-05).

        It used to be a NOT(...) expression over Hangul ranges, JSON tag
        containment and site_url substrings, re-evaluated per query.
        """
        cond = build_format_sql_condition(["manga"])
        self.assertEqual(cond, "(format_type = 'MANGA')")
        self.assertNotIn("title_native", cond)
        self.assertNotIn("tags @>", cond)

    def test_build_format_sql_manhwa(self):
        self.assertEqual(build_format_sql_condition(["manhwa"]), "(format_type = 'MANHWA')")

    def test_build_format_sql_manhua(self):
        self.assertEqual(build_format_sql_condition(["manhua"]), "(format_type = 'MANHUA')")

    def test_build_format_sql_multiple(self):
        """Selecting several formats is one IN list, not an OR of predicates."""
        cond = build_format_sql_condition(["manga", "manhwa"])
        self.assertEqual(cond, "(format_type IN ('MANGA', 'MANHWA'))")

    def test_build_format_sql_empty(self):
        """Empty format list must return None."""
        self.assertIsNone(build_format_sql_condition([]))
        self.assertIsNone(build_format_sql_condition(None))

    # -------------------------------------------------------------
    # Genre alias resolution (excluded Boys' Love used to filter nothing)
    # -------------------------------------------------------------
    def test_genre_alias_accepts_apostrophe_free_boys_love(self):
        """`Boys Love` has to reach the Boys' Love / Yaoi tag aliases.

        The alias list only held `boys' love`, and the request sanitizer deleted
        apostrophes before this ran, so `Boys Love` fell through to the generic
        branch and matched a tag that does not exist. Excluding it therefore
        excluded nothing, and the NOT(condition) was NOT(false) per row.
        """
        for spelling in ("Boys' Love", "Boys Love", "boys love", "boys-love", "BL", "Yaoi"):
            params = {}
            cond = build_genre_sql_condition([spelling], params, exclude=True)
            self.assertTrue(cond.startswith("NOT ("), spelling)
            bound = json.dumps(params)
            self.assertIn("Boys' Love", bound)
            self.assertIn("Yaoi", bound)

    def test_genre_alias_accepts_apostrophe_free_girls_love(self):
        for spelling in ("Girls' Love", "Girls Love", "GL", "Yuri"):
            params = {}
            build_genre_sql_condition([spelling], params)
            bound = json.dumps(params)
            self.assertIn("Girls' Love", bound)
            self.assertIn("Yuri", bound)

    def test_unaliased_genre_keeps_the_value_it_was_given(self):
        """No alias match means the caller's own text, apostrophes included."""
        params = {}
        build_genre_sql_condition(["Family's Bond"], params)
        self.assertIn("Family's Bond", json.dumps(params))

    def test_genre_alias_binds_apostrophe_verbatim(self):
        """The apostrophe must survive into the bind parameter, not the SQL text."""
        params = {}
        build_genre_sql_condition(["Boys' Love"], params, exclude=True)
        bound = json.dumps(params)
        self.assertIn("Boys' Love", bound)
        self.assertNotIn("Boys Love", bound)

    def test_build_format_sql_case_insensitive(self):
        """Format matching must be case-insensitive (e.g. 'MANGA' or 'Manhwa')."""
        cond_upper = build_format_sql_condition(["MANGA"])
        cond_lower = build_format_sql_condition(["manga"])
        self.assertEqual(cond_upper, cond_lower)

    def test_build_format_sql_ignores_unknown_values(self):
        """An unknown filter value must not be interpolated into SQL."""
        self.assertIsNone(build_format_sql_condition(["'; DROP TABLE manga; --"]))
        self.assertEqual(
            build_format_sql_condition(["manga", "nonsense"]), "(format_type = 'MANGA')"
        )

    # -------------------------------------------------------------
    # 2. Format Inference Tests
    # -------------------------------------------------------------
    def test_infer_format_korean_hangul(self):
        """Titles with Korean native Hangul must be classified as MANHWA."""
        fmt = infer_format_type(title_native="나 혼자만 레벨업", tags=None, genres=["Action"], site_url=None)
        self.assertEqual(fmt, "MANHWA")

    def test_infer_format_korean_tag_or_genre(self):
        """Titles tagged with Manhwa, Webtoon, or Korean must be classified as MANHWA."""
        fmt1 = infer_format_type(title_native=None, tags=[{"name": "Manhwa"}], genres=None)
        fmt2 = infer_format_type(title_native=None, tags=None, genres=["Manhwa"])
        fmt3 = infer_format_type(title_native=None, tags=[{"name": "Webtoon"}], genres=None)
        self.assertEqual(fmt1, "MANHWA")
        self.assertEqual(fmt2, "MANHWA")
        self.assertEqual(fmt3, "MANHWA")

    def test_infer_format_relife_preservation(self):
        """Japanese vertical web comic (Long Strip + Japanese Kana) must remain MANGA."""
        # ReLIFE: title_native has Katakana リライフ (\u30ea\u30e9\u30a4\u30d5), tag Long Strip
        fmt = infer_format_type(
            title_native="\u30ea\u30e9\u30a4\u30d5", 
            tags=[{"name": "Long Strip"}, {"name": "School Life"}],
            genres=["Romance", "Comedy"],
            site_url="https://mangadex.org/title/6e3553b9"
        )
        self.assertEqual(fmt, "MANGA", "ReLIFE with Japanese Kana must remain classified as MANGA")

    def test_infer_format_long_strip_without_korean_markers(self):
        """Long Strip title without Korean markers must not be classified as MANHWA."""
        fmt = infer_format_type(
            title_native=None,
            tags=[{"name": "Long Strip"}],
            genres=["Action"]
        )
        self.assertNotEqual(fmt, "MANHWA", "Generic strip without Korean markers must not leak into Manhwa")

    def test_infer_format_chinese_manhua(self):
        """Chinese titles with Manhua, Chinese tag or Full Color without Kana must be MANHUA."""
        fmt1 = infer_format_type(title_native=None, tags=[{"name": "Manhua"}], genres=None)
        fmt2 = infer_format_type(title_native="一条狗", tags=[{"name": "Full Color"}], genres=["Comedy"])
        self.assertEqual(fmt1, "MANHUA")
        self.assertEqual(fmt2, "MANHUA")

    def test_infer_format_japanese_manga(self):
        """Pure Japanese manga (e.g. Berserk, Chainsaw Man) must be classified as MANGA."""
        fmt = infer_format_type(
            title_native="チェンソーマン",
            tags=[{"name": "Demons"}, {"name": "Gore"}],
            genres=["Action", "Supernatural"]
        )
        self.assertEqual(fmt, "MANGA")

    # -------------------------------------------------------------
    # 3. Genre SQL Condition Tests
    # -------------------------------------------------------------
    def test_build_genre_sql_standard(self):
        """Standard genres must check both text array genres and JSONB tags."""
        params: dict = {}
        cond = build_genre_sql_condition(["Action"], params)
        self.assertIn("genres @> CAST(:genre_0_arr AS text[])", cond)
        self.assertIn("tags @> CAST(:genre_0_tag AS jsonb)", cond)
        self.assertEqual(params["genre_0_arr"], ["Action"])
        self.assertEqual(json.loads(params["genre_0_tag"]), [{"name": "Action"}])

    def test_build_genre_sql_yaoi_bl_aliases(self):
        """Yaoi / BL / Boys' Love aliases must expand to all related terminology."""
        for alias in ["yaoi", "bl", "boys' love"]:
            params: dict = {}
            cond = build_genre_sql_condition([alias], params)
            self.assertEqual(params["genre_0_arr"], ["Boys' Love"])
            self.assertEqual(json.loads(params["genre_0_t2"]), [{"name": "Yaoi"}])
            self.assertNotIn("'Boys'' Love'", cond)

    def test_build_genre_sql_yuri_gl_aliases(self):
        """Yuri / GL / Girls' Love aliases must expand to all related terminology."""
        for alias in ["yuri", "gl", "girls' love"]:
            params: dict = {}
            cond = build_genre_sql_condition([alias], params)
            self.assertEqual(params["genre_0_arr"], ["Girls' Love"])
            self.assertEqual(json.loads(params["genre_0_t2"]), [{"name": "Yuri"}])
            self.assertNotIn("'Girls'' Love'", cond)

    def test_build_genre_sql_demographics(self):
        """Demographics (Seinen, Shounen, Shoujo, Josei) must match tag name pattern."""
        for demo in ["Seinen", "Shounen", "Shoujo", "Josei"]:
            params: dict = {}
            build_genre_sql_condition([demo], params)
            self.assertEqual(json.loads(params["genre_0_tag"]), [{"name": demo}])

    def test_build_genre_sql_exclude(self):
        """Exclude mode must wrap conditions in NOT (...)."""
        params: dict = {}
        cond = build_genre_sql_condition(["Horror"], params, exclude=True)
        self.assertTrue(cond.startswith("NOT ("))
        self.assertEqual(params["exclude_genre_0_arr"], ["Horror"])

    def test_build_genre_sql_empty(self):
        """Empty genre list must return None."""
        self.assertIsNone(build_genre_sql_condition([], {}))
        self.assertIsNone(build_genre_sql_condition(None, {}))

    def test_build_genre_sql_requires_params(self):
        """SVC-10: there is no inline-literal form to fall back to any more."""
        with self.assertRaises(TypeError):
            build_genre_sql_condition(["Action"])  # type: ignore[call-arg]

    # -------------------------------------------------------------
    # 4. Filter Hash Determinism Tests
    # -------------------------------------------------------------
    def test_filter_hash_stability(self):
        """generate_filter_hash must be deterministic and insensitive to dict insertion order."""
        f1 = RecommendFilters(genres=["Action", "Fantasy"], format_type=["manga"], min_score=80)
        f2 = RecommendFilters(min_score=80, format_type=["manga"], genres=["Action", "Fantasy"])
        self.assertEqual(generate_filter_hash(f1), generate_filter_hash(f2))

    def test_filter_hash_none(self):
        """None filters must return 'default' hash."""
        self.assertEqual(generate_filter_hash(None), "default")

if __name__ == "__main__":
    unittest.main()


class TestScoreFloor(unittest.TestCase):
    """`min_score: 0` must mean "no floor", not "score at least zero".

    `average_score` is nullable and `NULL >= 0` is NULL, so binding 0 dropped every
    unscored title. Measured on the live catalogue before the fix: 8 of 20 rows
    vanished from an ordinary search, because the client sends 0 for an untouched
    slider -- the default state, not an edge case.
    """

    def _where(self, **kwargs):
        from app.services.query_filters import apply_filter_criteria
        from app.models import RecommendFilters

        where = []
        params = {}
        apply_filter_criteria(RecommendFilters(**kwargs), where, params)
        return where, params

    def test_zero_floor_adds_no_predicate(self):
        where, params = self._where(min_score=0)
        self.assertEqual(where, [])
        self.assertNotIn("min_score", params)

    def test_zero_match_floor_adds_no_predicate(self):
        where, params = self._where(min_match_pct=0)
        self.assertEqual(where, [])
        self.assertNotIn("min_pct", params)

    def test_a_real_floor_still_adds_one(self):
        where, params = self._where(min_score=70, min_match_pct=0.5)
        self.assertIn("average_score >= :min_score", where)
        self.assertEqual(params["min_score"], 70)

    def test_absent_floor_is_absent(self):
        where, _params = self._where()
        self.assertEqual(where, [])
