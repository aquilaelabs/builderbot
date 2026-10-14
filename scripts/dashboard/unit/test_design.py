"""design.py's rules as functions: the record's migration, what a save is
refused for, and the page text a session reads. The browser suite
(test/design.mjs) proves the view draws these; this proves the rules
themselves in milliseconds. Asserts outcomes, not wording: a refusal is
found by what it is about, never by its whole sentence."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import design  # noqa: E402


def clean(lang):
    """The language as a read stores it, problems collected, not raised."""
    design._collecting.found = []
    try:
        return design._clean_language(lang), list(design._collecting.found)
    finally:
        design._collecting.found = None


def block(kind="content", x=0, y=0, w=4, h=2, inside=0):
    b = {"kind": kind, "label": kind, "x": x, "y": y, "w": w, "h": h}
    if inside:
        b["in"] = inside
    return b


def page(blocks, **kw):
    return {"name": "a page", "platform": "web", "frame": "desktop", "template": "blank",
            "blocks": blocks, **kw}


class OtherHalf(unittest.TestCase):
    """A theme's other half (R216): the same tokens for the opposite mode,
    kept with the theme, a bad hex dropped like any color's, and written
    out wherever the theme's colors are."""
    THEME = {"name": "Night", "mode": "dark",
             "colors": [{"name": "bg", "hex": "#101010", "means": "the page"},
                        {"name": "accent", "hex": "#3fb950", "means": "the one"}],
             "light": [{"name": "bg", "hex": "#f4f4f4", "means": "the page"},
                       {"name": "accent", "hex": "#1f7a3a", "means": "the one"},
                       {"name": "accent", "hex": "#000000", "means": "twice"},
                       {"name": "odd", "hex": "nope", "means": ""}]}

    def test_the_other_half_is_kept_and_cleaned(self):
        got, found = clean({"themes": [self.THEME]})
        light = got["themes"][0]["light"]
        self.assertEqual([c["name"] for c in light], ["bg", "accent", "odd"], "a name twice is dropped")
        self.assertEqual(light[0]["hex"], "#f4f4f4")
        self.assertEqual(light[2]["hex"], "#000000", "a hex that is not one reads as black, as a color's does")
        self.assertTrue(any("nope" in f for f in found))
        none, _ = clean({"themes": [{"name": "Plain", "mode": "dark", "colors": self.THEME["colors"]}]})
        self.assertEqual(none["themes"][0]["light"], [])

    def test_the_other_half_is_written_out_with_the_theme(self):
        got, _ = clean({"themes": [self.THEME, {"name": "Day", "mode": "light", "colors": self.THEME["light"][:2]}]})
        text = design.file_text({"language": got, "pages": []})
        self.assertIn("Its light half, the same tokens under the mode switch:", text)
        self.assertIn("| `--accent` | `#1f7a3a` |", text)
        self.assertNotIn("Its dark half", text, "Day has one palette")


class Migration(unittest.TestCase):
    def test_pre_theme_record_becomes_one_theme(self):
        got, found = clean({"scheme": "abyss", "colors": {"bg": "#000000"}})
        self.assertEqual(found, [])
        self.assertEqual(len(got["themes"]), 1)
        bg = [c for c in got["themes"][0]["colors"] if c["name"] == "bg"]
        self.assertEqual(bg[0]["hex"], "#000000")

    def test_language_choices_carry_to_every_theme_lacking_them(self):
        got, found = clean({"font": "serif", "themes": [
            {"name": "A", "mode": "dark", "colors": []},
            {"name": "B", "mode": "light", "colors": [], "font": "mono"}]})
        self.assertEqual(found, [])
        self.assertEqual([t["font"] for t in got["themes"]], ["serif", "mono"])

    def test_language_rules_go_to_the_first_theme_only(self):
        rule = {"name": "radii", "text": "all corners 6px"}
        got, found = clean({"rules": [rule], "themes": [
            {"name": "A", "mode": "dark", "colors": []},
            {"name": "B", "mode": "dark", "colors": []}]})
        self.assertEqual(found, [])
        self.assertEqual([r["name"] for r in got["themes"][0]["rules"]], ["radii"])
        self.assertEqual(got["themes"][1]["rules"], [])

    def test_custom_map_follows_the_rules_to_the_first_theme_only(self):
        # B386: carried into a theme without the rule, it refused the record.
        got, found = clean({"corners": "custom", "custom": {"corners": "radii"},
                            "rules": [{"name": "radii", "text": "6px"}],
                            "themes": [{"name": "A", "mode": "dark", "colors": []},
                                       {"name": "B", "mode": "dark", "colors": []}]})
        self.assertEqual(found, [])
        self.assertEqual(got["themes"][0]["custom"], {"corners": "radii"})
        self.assertEqual(got["themes"][1]["custom"], {})

    def test_choices_with_no_theme_get_a_theme_to_hold_them(self):
        got, _ = clean({"font": "mono"})
        self.assertEqual(len(got["themes"]), 1)
        self.assertEqual(got["themes"][0]["font"], "mono")

    def test_an_empty_language_is_a_language(self):
        got, found = clean({})
        self.assertEqual((got["themes"], found), ([], []))

    def test_lead_is_the_first_theme_or_an_empty_one(self):
        self.assertEqual(design.lead({"themes": [{"name": "A"}, {"name": "B"}]})["name"], "A")
        self.assertEqual(design.lead({"themes": []})["rules"], [])


class Refusals(unittest.TestCase):
    def test_every_problem_is_listed_in_one_pass(self):
        found = design.problems({"themes": [{"name": "A", "mode": "dark", "colors": []},
                                            {"name": "a", "mode": "dark", "colors": []}]},
                                [page([block()], key="k"), page([block()], key="k")])
        self.assertTrue(any("two themes" in f for f in found), found)
        self.assertTrue(any("two pages carry the key" in f for f in found), found)

    def test_too_many_themes(self):
        many = [{"name": f"T{i}", "mode": "dark", "colors": []} for i in range(design.THEMES_MAX + 1)]
        self.assertTrue(design.problems({"themes": many}, []))

    def test_a_clean_record_has_no_problems(self):
        self.assertEqual(design.problems({"themes": [{"name": "A", "mode": "dark", "colors": []}]},
                                         [page([block()])]), [])

    def test_a_block_off_the_frame_is_refused(self):
        self.assertTrue(design.problems({}, [page([block(x=-1)])]))
        self.assertTrue(design.problems({}, [page([block(x=10, w=4)])]))

    def test_a_child_must_stay_inside_its_parent(self):
        ok = [block(x=0, y=0, w=6, h=4), block(x=1, y=1, w=2, h=2, inside=1)]
        out = [block(x=0, y=0, w=6, h=4), block(x=5, y=1, w=3, h=2, inside=1)]
        self.assertEqual(design.problems({}, [page(ok)]), [])
        self.assertTrue(design.problems({}, [page(out)]))

    def test_a_child_comes_after_its_parent(self):
        self.assertTrue(design.problems({}, [page([block(x=1, y=1, w=2, h=2, inside=2),
                                                   block(x=0, y=0, w=6, h=4)])]))


class PageText(unittest.TestCase):
    def test_blocks_are_numbered_in_drawing_order_and_children_name_parents(self):
        design._collecting.found = []
        try:
            p = design._clean_page(page([block("list", w=6, h=4), block("card", x=1, y=1, w=2, h=1, inside=1)]), 1)
        finally:
            design._collecting.found = None
        text = design.page_text(p)
        self.assertIn("  1. ", text)
        self.assertIn("  2. ", text)
        self.assertIn("inside block 1", text)


if __name__ == "__main__":
    unittest.main()
