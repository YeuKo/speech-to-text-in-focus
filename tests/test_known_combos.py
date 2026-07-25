from stt.ui import known_combos as kc


class TestNormalise:
    def test_orders_modifiers_canonically(self):
        assert kc.normalise("shift+ctrl+f") == "ctrl+shift+f"
        assert kc.normalise("alt+ctrl+shift+q") == "ctrl+alt+shift+q"

    def test_case_and_spacing(self):
        assert kc.normalise(" Ctrl + Shift + N ") == "ctrl+shift+n"

    def test_keeps_multi_word_keys(self):
        assert kc.normalise("ctrl+page up") == "ctrl+page up"


class TestDescribe:
    def test_the_classics(self):
        assert kc.describe("ctrl+f") == ("common", "Find")
        assert kc.describe("ctrl+s") == ("common", "Save")

    def test_windows_reserved(self):
        tier, _ = kc.describe("ctrl+alt+delete")
        assert tier == "reserved"

    def test_recognised_whatever_the_order(self):
        assert kc.describe("shift+ctrl+t") == kc.describe("ctrl+shift+t")

    def test_free_combination(self):
        assert kc.describe("ctrl+alt+a") is None
        assert kc.describe("ctrl+alt+q") is None

    def test_no_combination_is_in_both_tiers(self):
        assert not set(kc.RESERVED) & set(kc.COMMON)

    def test_every_entry_is_stored_canonically(self):
        """A typo in the table's key order would silently never match."""
        for combo in (*kc.RESERVED, *kc.COMMON):
            assert kc.normalise(combo) == combo
