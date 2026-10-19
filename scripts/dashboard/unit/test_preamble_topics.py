"""R202: the briefing is a core plus an index, and the rest is topics a
session reads with `bb help TOPIC`. preamble.split reads the template's
markers; this holds it to them without a server or a project."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import preamble  # noqa: E402

TEMPLATE = """Intro line.

## What holds every time

- Always this.

<!-- BUILDERBOT:CORE-END -->

## This project

Per-project line.

<!-- BUILDERBOT:TOPICS -->

## Start here
<!-- BUILDERBOT:TOPIC start: the machine -->

How the machine works, at length.

## Git
<!-- BUILDERBOT:TOPIC git: pushing -->

Push with bb git push.
More about git.

## Kept in the block

A section with no marker stays where it is.
"""


class Split(unittest.TestCase):
    def test_topics_leave_the_block_and_the_index_takes_their_place(self):
        text, topics = preamble.split(TEMPLATE)
        self.assertEqual([t[0] for t in topics], ["start", "git"])
        self.assertEqual(topics[1][1:3], ("Git", "pushing"))
        self.assertEqual(topics[1][3], "Push with bb git push.\nMore about git.")
        self.assertIn("- start: the machine\n- git: pushing", text)
        self.assertIn("`bb help TOPIC`", text)
        self.assertNotIn("How the machine works", text)
        self.assertIn("## Kept in the block", text)
        self.assertIn("A section with no marker stays", text)
        self.assertIn("## This project\n\nPer-project line.", text)
        self.assertNotIn("\n\n\n", text)

    def test_a_template_without_topics_is_itself(self):
        text, topics = preamble.split("## Only\n\nthis\n")
        self.assertEqual(topics, [])
        self.assertEqual(text, "## Only\n\nthis\n")

    def test_the_shipped_template_splits_into_the_named_topics(self):
        text = None
        for cand in preamble.BRIEFING_PATHS:
            try:
                text = cand.read_text()
                break
            except OSError:
                continue
        self.assertIsNotNone(text)
        block, topics = preamble.split(text)
        slugs = [t[0] for t in topics]
        for s in ("start", "where", "map", "build", "capture", "asks", "notebook", "git", "android", "gpu", "containers"):
            self.assertIn(s, slugs)
        self.assertLess(len(block), 8000, "the block without its topics is a few screens")
        self.assertIn("## What holds every time", block)


class Mentioned(unittest.TestCase):
    """What a prompt names on the record arrives on that prompt (R202)."""

    def setUp(self):
        class Roadmap:
            items = staticmethod(lambda p: [
                {"id": 4, "text": "The emulator boots headless on the dev node", "steps": [{"text": "a"}, {"text": "b", "done": True}]},
                {"id": 9, "text": "A parked one about the emulator", "shelved": 1},
                {"id": 12, "text": "Unrelated: the nginx page's certificate block"}])

        class Bugs:
            open_bugs = staticmethod(lambda p: [
                {"id": 7, "title": "The emulator boot hangs under software rendering", "severity": "medium"},
                {"id": 8, "title": "A title with nothing in common", "severity": "low"}])
        preamble.configure(rules_mod=None, roadmap_mod=Roadmap, bugs_mod=Bugs)

    def test_words_shared_with_a_title_name_it_and_a_parked_one_never(self):
        said, names = preamble.mentioned("p", "the emulator does not boot on the dev node")
        self.assertIn("R4 The emulator boots headless on the dev node (1 step open): `bb roadmap show R4`", said)
        self.assertIn("B7 [medium] The emulator boot hangs under software rendering: `bb bug show B7`", said)
        self.assertNotIn("parked", said)
        self.assertNotIn("nginx", said)
        self.assertEqual(names, ["roadmap-4", "bug-7"])

    def test_a_number_names_one_and_what_was_told_is_left_out(self):
        said, names = preamble.mentioned("p", "what about R12 and B8?")
        self.assertEqual(names, ["roadmap-12", "bug-8"])
        self.assertEqual(preamble.mentioned("p", "what about R12 and B8?", told=names), ("", []))
        self.assertEqual(preamble.mentioned("p", "nothing here at all"), ("", []))

    def test_common_words_alone_name_nothing(self):
        self.assertEqual(preamble.mentioned("p", "the one with the thing on the tab"), ("", []))


if __name__ == "__main__":
    unittest.main()
