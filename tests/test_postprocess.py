from stt import postprocess


class TestBuildPrompt:
    def test_none_when_empty(self):
        assert postprocess.build_prompt([]) is None
        assert postprocess.build_prompt(["", "  "]) is None

    def test_joins_terms(self):
        assert postprocess.build_prompt(["Anthropic", "Kubernetes"]) == (
            "Vocabulario: Anthropic, Kubernetes."
        )

    def test_strips_whitespace(self):
        assert postprocess.build_prompt(["  Grafana  "]) == "Vocabulario: Grafana."


class TestApply:
    def test_no_replacements_returns_text(self):
        assert postprocess.apply("hola mundo", {}) == "hola mundo"

    def test_empty_text(self):
        assert postprocess.apply("", {"a": "b"}) == ""

    def test_case_insensitive_match_preserves_canonical(self):
        out = postprocess.apply("uso anthropik a diario", {"anthropik": "Anthropic"})
        assert out == "uso Anthropic a diario"

    def test_respects_word_boundaries(self):
        out = postprocess.apply("anthropikismo", {"anthropik": "Anthropic"})
        assert out == "anthropikismo"

    def test_uppercase_source_uppercases_replacement(self):
        out = postprocess.apply("ANTHROPIK", {"anthropik": "Anthropic"})
        assert out == "ANTHROPIC"

    def test_capitalized_source_capitalizes_replacement(self):
        out = postprocess.apply("Cubernetes mola", {"cubernetes": "kubernetes"})
        assert out == "Kubernetes mola"

    def test_longest_key_wins(self):
        out = postprocess.apply("new york city", {"new york": "NYC", "new york city": "NYC!"})
        assert out == "NYC!"

    def test_multiple_replacements(self):
        out = postprocess.apply(
            "anthropik y cubernetes",
            {"anthropik": "Anthropic", "cubernetes": "Kubernetes"},
        )
        assert out == "Anthropic y Kubernetes"


class TestApplyFuzzy:
    def test_no_terms_returns_text(self):
        assert postprocess.apply_fuzzy("hola", []) == "hola"

    def test_exact_term_untouched(self):
        # Si rapidfuzz no está, devuelve el texto igual; si está, no debe romper la palabra exacta.
        assert postprocess.apply_fuzzy("Anthropic", ["Anthropic"]) == "Anthropic"
