import pytest

from s2f import postprocess


class TestBuildPrompt:
    def test_none_when_empty(self):
        assert postprocess.build_prompt([]) is None
        assert postprocess.build_prompt(["", "  "]) is None

    def test_joins_terms(self):
        assert postprocess.build_prompt(["Anthropic", "Kubernetes"]) == (
            "Vocabulary: Anthropic, Kubernetes."
        )

    def test_strips_whitespace(self):
        assert postprocess.build_prompt(["  Grafana  "]) == "Vocabulary: Grafana."


class TestWithContext:
    PROMPT = "Vocabulary: Grafana."

    def test_no_context_leaves_the_prompt_alone(self):
        assert postprocess.with_context(self.PROMPT, "") == self.PROMPT
        assert postprocess.with_context(self.PROMPT, "   \n ") == self.PROMPT

    def test_context_is_appended(self):
        assert postprocess.with_context(self.PROMPT, "Estaba diciendo que sí.") == (
            "Vocabulary: Grafana. Estaba diciendo que sí."
        )

    def test_without_vocabulary_the_context_is_the_whole_prompt(self):
        assert postprocess.with_context(None, "Estaba diciendo que sí.") == (
            "Estaba diciendo que sí."
        )

    def test_long_context_is_trimmed_to_what_whisper_reads(self):
        context = "Una frase cualquiera del dictado. " * 60
        out = postprocess.with_context(self.PROMPT, context)
        assert len(out) <= postprocess._PROMPT_MAX_CHARS
        # The vocabulary survives, and it is the *end* of the dictation that is kept.
        assert out.startswith(self.PROMPT)
        assert out.endswith("Una frase cualquiera del dictado.")

    def test_trimming_starts_on_a_sentence_boundary(self):
        context = "Frase número uno del dictado. " * 40 + "Y la última."
        out = postprocess.with_context(None, context)
        assert out.startswith("Frase número uno")

    def test_unpunctuated_context_is_cut_between_words(self):
        out = postprocess.with_context(None, "palabra " * 300)
        assert out.startswith("palabra ")
        assert len(out) <= postprocess._PROMPT_MAX_CHARS


class TestIsContextEcho:
    CONTEXT = "Vocabulary: Grafana. Lo que quería comentarte es que mañana no puedo."

    def test_a_sentence_recited_back(self):
        assert postprocess.is_context_echo(
            "Lo que quería comentarte es que mañana no puedo.", self.CONTEXT
        ) is True

    def test_case_and_punctuation_do_not_matter(self):
        assert postprocess.is_context_echo(
            "lo que quería comentarte, es que mañana no puedo", self.CONTEXT
        ) is True

    def test_new_speech_is_kept(self):
        assert postprocess.is_context_echo(
            "Te llamo el jueves y lo vemos con calma.", self.CONTEXT
        ) is False

    def test_text_that_continues_the_context_is_kept(self):
        """Only a *complete* repetition counts; carrying on is the normal case."""
        assert postprocess.is_context_echo(
            "es que mañana no puedo, así que lo dejamos para el jueves", self.CONTEXT
        ) is False

    def test_a_short_repetition_is_kept(self):
        """People do say the same four words twice."""
        assert postprocess.is_context_echo("mañana no puedo", self.CONTEXT) is False

    def test_no_match_mid_word(self):
        assert postprocess.is_context_echo(
            "ana no puedo comentarte nada", "Mañana no puedo comentarte nada"
        ) is False

    def test_empty(self):
        assert postprocess.is_context_echo("", self.CONTEXT) is False
        assert postprocess.is_context_echo("Cualquier cosa que diga aquí", "") is False


class TestIsPromptEcho:
    TERMS = ["Anthropic", "Kubernetes", "Grafana"]

    def test_the_reported_hallucination(self):
        assert postprocess.is_prompt_echo("Anthropic, Kubernetes, Grafana", self.TERMS) is True

    def test_prompt_repeated_verbatim(self):
        assert postprocess.is_prompt_echo(
            postprocess.build_prompt(self.TERMS), self.TERMS
        ) is True

    def test_prompt_preamble_translated(self):
        assert postprocess.is_prompt_echo("Vocabulario: Grafana.", self.TERMS) is True

    def test_reordered_and_repeated_terms(self):
        assert postprocess.is_prompt_echo("Grafana. Grafana. Kubernetes.", self.TERMS) is True

    def test_single_term_is_kept(self):
        """A one-word dictation is legitimate and must survive."""
        assert postprocess.is_prompt_echo("Grafana", self.TERMS) is False

    def test_real_sentence_using_terms_is_kept(self):
        assert postprocess.is_prompt_echo(
            "Despliega Grafana en Kubernetes esta tarde.", self.TERMS
        ) is False

    def test_empty_text(self):
        assert postprocess.is_prompt_echo("", self.TERMS) is False
        assert postprocess.is_prompt_echo("...", self.TERMS) is False

    def test_without_dictionary_nothing_is_an_echo(self):
        assert postprocess.is_prompt_echo("Anthropic, Kubernetes", []) is False


class TestCollapseRepeats:
    def test_the_reported_loop(self):
        """Whisper latching onto a phrase and repeating it to the end."""
        text = ("Y esto es lo que quería decir. "
                + "Gracias por escuchar el mensaje. " * 5).strip()
        out = postprocess.collapse_repeats(text)
        assert out.count("Gracias por escuchar el mensaje.") == 1
        assert out.startswith("Y esto es lo que quería decir.")

    def test_a_loop_of_two_alternating_sentences(self):
        text = ("Cierro el tema por hoy. " + "Una frase. Y la otra frase. " * 4).strip()
        out = postprocess.collapse_repeats(text)
        assert out.count("Una frase.") == 1
        assert out.count("Y la otra frase.") == 1
        assert out.startswith("Cierro el tema por hoy.")

    def test_ordinary_text_is_untouched(self):
        text = "Primera frase. Segunda frase. Tercera frase."
        assert postprocess.collapse_repeats(text) == text

    def test_a_phrase_repeated_twice_is_kept(self):
        """Saying something twice for emphasis is normal; three times is a loop."""
        text = "Es importante revisarlo. Es importante revisarlo."
        assert postprocess.collapse_repeats(text) == text

    def test_short_repeats_are_kept(self):
        text = "No. No. No. No."
        assert postprocess.collapse_repeats(text) == text

    def test_only_the_looping_run_is_collapsed(self):
        text = ("Empezamos con esto. " + "Repite la misma cosa. " * 4 + "Y terminamos aquí.")
        out = postprocess.collapse_repeats(text)
        assert out.count("Repite la misma cosa.") == 1
        assert "Empezamos con esto." in out and "Y terminamos aquí." in out

    def test_case_and_spacing_differences_still_count_as_repeats(self):
        text = "Hola qué tal todo. hola qué tal todo. HOLA QUÉ TAL TODO."
        assert postprocess.collapse_repeats(text) == "Hola qué tal todo."

    def test_empty_and_single_sentence(self):
        assert postprocess.collapse_repeats("") == ""
        assert postprocess.collapse_repeats("Una sola frase.") == "Una sola frase."


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
        # If rapidfuzz is missing, the text is returned as-is; if present, it must
        # not break a word that already matches a term exactly.
        assert postprocess.apply_fuzzy("Anthropic", ["Anthropic"]) == "Anthropic"

    def test_corrects_a_mangled_client_name(self):
        pytest.importorskip("rapidfuzz")
        terms = ["Iberdrola", "Anthropic", "Mapfre"]
        assert postprocess.apply_fuzzy("factura de iberdrolla", terms) == "factura de Iberdrola"
        assert postprocess.apply_fuzzy("antropic", terms) == "Anthropic"
        assert postprocess.apply_fuzzy("seguro mapfrey", terms) == "seguro Mapfre"

    def test_leaves_ordinary_words_alone(self):
        pytest.importorskip("rapidfuzz")
        terms = ["Iberdrola", "Anthropic", "Mapfre"]
        text = "el mapa de la mano derecha estaba mojado"
        assert postprocess.apply_fuzzy(text, terms) == text

    def test_ignores_short_terms_and_words(self):
        """"mano" scores 86 against "Ana": short words are not judged at all."""
        pytest.importorskip("rapidfuzz")
        assert postprocess.apply_fuzzy("la mano", ["Ana"]) == "la mano"
