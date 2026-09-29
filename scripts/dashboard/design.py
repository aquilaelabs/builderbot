"""The notebook's Design view: a project's design language and its pages.

The one thing the dashboard had no say in was what a project looks like:
every colour, font and layout was a sentence typed into a session and
gone with the conversation. This keeps them. A project has ONE design
language (colours as tokens, type, shape, space, and the design notes the
operator adds in their own words, for everything the settings cannot say) and any number of PAGES, each a layout of labelled
blocks arranged on a phone or desktop frame and named for what it is for
("the settings page"). The name is the target: applying a page's design
means applying it there.

Two things come out of it, both generated here and nowhere else, so the
tab, `bb design` and the file cannot drift:

  * a prompt, one for the language and one per page, which the tab shows
    for a person to copy into a session when they want it applied, and
    which `bb design show` prints for a session that reads it by itself.
    The view is passive (the operator, 28 Sep): nothing on it reaches
    into a session;
  * docs/design-language.md in the project's tree, the same shape as
    BuilderBot's own, written on request from the saved state. A session
    reads it as the standing description of the look, which is what the
    brief could never be: a file that says what the product looks like now.

Store: designs.json, {project: {"language": {...}, "next": n, "pages":
[...]}}, keyed by project so a rename carries it (projects._KEYED). Edits
are staged in the notebook and land as one save of the whole record.
"""
import json
import re
import time
from pathlib import Path

import pending
import statefile

WORKSPACE = None
FILE = None
write_json = None
git_env = None

FILE_PATH = "docs/design-language.md"
MAX_PAGES = 40
MAX_BLOCKS = 40
NOTES_MAX = 4000
# The design's rules: the prose, cut into named pieces with triggers, the
# shape the house rules have. A session gets one on the turn it edits a
# file or is asked about a word the rule names (rules.matching, through the
# hooks), never the whole text at once: BuilderBot's own design language is
# thirty thousand characters, and a dump of it on every design question is
# what nobody reads (the operator, 28 Sep). One without triggers stands in
# every briefing, as a house rule does.
RULES_MAX = 60
RULE_TEXT_MAX = 20000
RULE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
NAME_MAX = 120

# ---- the vocabulary: what a design is made of -------------------------------
# What a block can be. A label a person reads, and one line of what the
# kind means, which is what the prompt says about it. Alphabetical by key,
# as every list of choices here is (docs/design-language.md).
KINDS = [
    ("button", "Button", "a primary action"),
    ("card", "Card", "a raised box holding one thing"),
    ("chart", "Chart", "a chart or a meter"),
    ("content", "Content", "the main reading or working area"),
    ("footer", "Footer", "a footer with the quiet links"),
    ("form", "Form", "fields with one Save or Submit at the foot"),
    ("header", "Header", "the top bar with the name and the account"),
    ("hero", "Hero", "a large opening block with one message"),
    ("image", "Image", "a picture or a media block"),
    ("list", "List", "rows of things, each opening to detail"),
    ("nav", "Navigation", "the way around: tabs or a menu"),
    ("overlay", "Overlay", "a dialog, sheet, drawer, popover or toast over the page"),
    ("search", "Search", "a search box"),
    ("sidebar", "Sidebar", "a side column of links or filters"),
    ("table", "Table", "columns of data"),
    ("tabs", "Tabs", "a strip of tabs switching one area"),
    ("text", "Text", "a block of prose"),
]
KIND_KEYS = [k for k, _, _ in KINDS]

# The frames a page is laid out on: the grid a block's cells are counted in.
FRAMES = {"phone": {"cols": 6, "rows": 12, "label": "Phone"},
          "landscape": {"cols": 12, "rows": 6, "label": "Phone, sideways"},
          "desktop": {"cols": 12, "rows": 8, "label": "Desktop"}}

# Preset layouts: a set of blocks on a frame, the starting point a page is
# made from and then rearranged. Blocks are (kind, label, x, y, w, h).
TEMPLATES = [
    {"key": "blank", "label": "Blank", "frame": "desktop", "blocks": []},
    {"key": "app", "label": "App shell", "frame": "desktop", "blocks": [
        ("header", "the app's name and the account menu", 0, 0, 12, 1),
        ("sidebar", "the sections of the app", 0, 1, 3, 7),
        ("content", "the section that is open", 3, 1, 9, 7)]},
    {"key": "dashboard", "label": "Dashboard", "frame": "desktop", "blocks": [
        ("header", "the app's name and the account menu", 0, 0, 12, 1),
        ("card", "the first number that matters", 0, 1, 4, 2),
        ("card", "the second number that matters", 4, 1, 4, 2),
        ("card", "the third number that matters", 8, 1, 4, 2),
        ("chart", "the trend over time", 0, 3, 8, 5),
        ("list", "what happened most recently", 8, 3, 4, 5)]},
    {"key": "landing", "label": "Landing page", "frame": "desktop", "blocks": [
        ("header", "the name and the way in", 0, 0, 12, 1),
        ("hero", "what this is, in one sentence, and the one action", 0, 1, 12, 3),
        ("card", "the first reason to use it", 0, 4, 4, 2),
        ("card", "the second reason", 4, 4, 4, 2),
        ("card", "the third reason", 8, 4, 4, 2),
        ("footer", "the quiet links", 0, 7, 12, 1)]},
    {"key": "listdetail", "label": "List and detail", "frame": "desktop", "blocks": [
        ("header", "the app's name and the account menu", 0, 0, 12, 1),
        ("search", "find one by name", 0, 1, 4, 1),
        ("list", "every one, newest first", 0, 2, 4, 6),
        ("content", "the one that is open", 4, 1, 8, 7)]},
    {"key": "settings", "label": "Settings", "frame": "desktop", "blocks": [
        ("header", "the app's name and the account menu", 0, 0, 12, 1),
        ("nav", "the groups of settings", 0, 1, 3, 7),
        ("form", "the group that is open, with one Save at its foot", 3, 1, 9, 7)]},
    {"key": "mobile", "label": "Mobile app", "frame": "phone", "blocks": [
        ("header", "the screen's title", 0, 0, 6, 1),
        ("content", "the screen", 0, 1, 6, 10),
        ("tabs", "the app's sections, a thumb away", 0, 11, 6, 1)]},
    {"key": "mobilefeed", "label": "Mobile feed", "frame": "phone", "blocks": [
        ("header", "the app's name and a search", 0, 0, 6, 1),
        ("list", "the feed, newest first", 0, 1, 6, 10),
        ("button", "the one thing this screen is for", 4, 9, 2, 1),
        ("tabs", "the app's sections, a thumb away", 0, 11, 6, 1)]},
]
TEMPLATE_KEYS = [t["key"] for t in TEMPLATES]

# The colour tokens a language names, in the order a reader meets them:
# what the page is painted on, what sits on it, the text, the edges, then
# the four states. The names are the dashboard's own, so a session that
# knows one knows the other.
TOKENS = [
    ("bg", "Background", "the page"),
    ("panel", "Surface", "a raised box, a card, a bar"),
    ("ink", "Text", "the text"),
    ("dim", "Muted", "secondary text and labels"),
    ("line", "Edge", "hairlines and borders"),
    ("accent", "Accent", "the one colour that means \"this is the one\": the active tab, the primary button, a link"),
    ("warn", "Warning", "a warning"),
    ("bad", "Danger", "an error, a destructive verb"),
    ("note", "Note", "an informational mark"),
    ("good", "Good", "success: a passing check, a legal move, a safe state"),
]
# A theme is a named list of colours, each a name, a hex and what it is
# for: the ten above are what a preset fills it with, and the operator adds
# a second surface, a chart ramp, a game's card colours, or takes one away.
# A language has one theme or several (light and dark, a few presets), the
# first being the one the app starts on. Where a theme picker sits is the
# app's business: a session asked to make one takes the themes from here.
THEMES_MAX = 16
COLORS_MAX = 40
MODES = ("dark", "light")
TOKEN_KEYS = [k for k, _, _ in TOKENS]

# Preset schemes. The dashboard's own twelve, so a project can wear what its
# operator already looks at, and three light ones the dashboard has no use
# for. Default leads because it is what you get having made no choice; the
# rest are alphabetical.
SCHEMES = [
    ("default", "Default", {"bg": "#1a1f26", "panel": "#212730", "line": "#4d5c6f", "ink": "#e6edf3",
                            "dim": "#9fa9b4", "accent": "#3fb950", "warn": "#d29922", "bad": "#f8524a", "note": "#58a6ff", "good": "#56d364"}),
    ("abyss", "Abyss", {"bg": "#111d20", "panel": "#18262a", "line": "#3e5e66", "ink": "#dcecee",
                        "dim": "#93a9ac", "accent": "#2fb8c6", "warn": "#d7ab4c", "bad": "#ef6a63", "note": "#6fb3e0", "good": "#4fd1a1"}),
    ("ash", "Ash", {"bg": "#1b1b1b", "panel": "#222322", "line": "#555955", "ink": "#e2e4e0",
                    "dim": "#a1a59f", "accent": "#a3b18a", "warn": "#cfa94a", "bad": "#e26d60", "note": "#82a7b8", "good": "#9ccf8a"}),
    ("carbon", "Carbon", {"bg": "#141417", "panel": "#1c1c1f", "line": "#53535b", "ink": "#e8e8ea",
                          "dim": "#9d9da4", "accent": "#e64e53", "warn": "#d9a441", "bad": "#ff6b6b", "note": "#7aa2f7", "good": "#57d17a"}),
    ("ember", "Ember", {"bg": "#1f1814", "panel": "#271f1a", "line": "#67533e", "ink": "#f0e4d8",
                        "dim": "#af9f90", "accent": "#f0873f", "warn": "#e8bb50", "bad": "#ef5f52", "note": "#8fb4d9", "good": "#8fcf7a"}),
    ("ice", "Ice", {"bg": "#151c21", "panel": "#1c252c", "line": "#465b6c", "ink": "#e3edf5",
                    "dim": "#9aa8ae", "accent": "#58c7e8", "warn": "#d3ab52", "bad": "#ee6a68", "note": "#7cc0ff", "good": "#5fd39a"}),
    ("linen", "Linen (light)", {"bg": "#f6f1e8", "panel": "#fffaf2", "line": "#d5c9b6", "ink": "#2b2620",
                                "dim": "#6f665b", "accent": "#b5562a", "warn": "#9a6a00", "bad": "#b8322b", "note": "#2d6a9f", "good": "#2e8b57"}),
    ("mint", "Mint (light)", {"bg": "#eef5f1", "panel": "#ffffff", "line": "#c3d6cb", "ink": "#1d2a24",
                              "dim": "#5f6f67", "accent": "#1f8a5b", "warn": "#9a6a00", "bad": "#c0392b", "note": "#2a6f9e", "good": "#2f9e6b"}),
    ("moss", "Moss", {"bg": "#161f1b", "panel": "#1d2920", "line": "#48604f", "ink": "#dfe9df",
                      "dim": "#9daba0", "accent": "#63c98a", "warn": "#d6ad4e", "bad": "#e8695f", "note": "#74b3d8", "good": "#7fd67a"}),
    ("nocturne", "Nocturne", {"bg": "#181825", "panel": "#202031", "line": "#53537b", "ink": "#e4e2f5",
                              "dim": "#a2a0c1", "accent": "#9d7cff", "warn": "#e0b24d", "bad": "#f2637b", "note": "#7cb0ff", "good": "#6fd39a"}),
    ("nostromo", "Nostromo", {"bg": "#101712", "panel": "#162018", "line": "#405b37", "ink": "#d7e3c8",
                              "dim": "#95a488", "accent": "#ffb000", "warn": "#ffd166", "bad": "#ff5f45", "note": "#9ad07a", "good": "#9ad07a"}),
    ("paper", "Paper (light)", {"bg": "#f4f5f7", "panel": "#ffffff", "line": "#cfd4dc", "ink": "#1f2328",
                                "dim": "#59636e", "accent": "#0969da", "warn": "#9a6700", "bad": "#cf222e", "note": "#0550ae", "good": "#1a7f37"}),
    ("plum", "Plum", {"bg": "#1e1623", "panel": "#261d2d", "line": "#654d73", "ink": "#eddff2",
                      "dim": "#ae9cb7", "accent": "#c874d8", "warn": "#dfae52", "bad": "#ee6183", "note": "#83aee8", "good": "#7fcf9a"}),
    ("rust", "Rust", {"bg": "#1e1614", "panel": "#261d1a", "line": "#6a4e4a", "ink": "#ecdedb",
                      "dim": "#ae9d99", "accent": "#cf6a4c", "warn": "#d9a441", "bad": "#e8544a", "note": "#7fa8c9", "good": "#8fcf7a"}),
    ("sepia", "Sepia", {"bg": "#1f1b14", "panel": "#272219", "line": "#63563e", "ink": "#ece0cb",
                        "dim": "#b0a28c", "accent": "#d3a94f", "warn": "#e3c069", "bad": "#e0705f", "note": "#9db98c", "good": "#9db98c"}),
    ("slate", "Slate", {"bg": "#181c23", "panel": "#1f242d", "line": "#4f5a68", "ink": "#dfe5ec",
                        "dim": "#9fa6ae", "accent": "#6ea8fe", "warn": "#d9a441", "bad": "#ef6f6c", "note": "#7fb8ff", "good": "#5fd39a"}),
]
SCHEME_KEYS = [k for k, _, _ in SCHEMES]

# What a page is for. On the page rather than the language, because one
# project can be several products (a web app and its Android companion) in
# one look. It tailors the rest of the page: which frames it is laid out on
# (a phone app has no desktop frame), what the platform's own font is, and
# the conventions the prompt holds the session to. Alphabetical after Web
# app, which leads because it is what a page is until it says otherwise.
PLATFORMS = [
    ("web", "Web app", ["desktop", "phone", "landscape"], "system-ui, the platform's own sans-serif",
     "a responsive web app: the layout holds at phone and desktop widths, and every tap "
     "target is at least 44px on a coarse pointer"),
    ("android", "Android app", ["phone", "landscape"], "Roboto, the platform's own",
     "an Android app: Material's shapes and elevation, 48dp touch targets, the app's sections "
     "as a bottom bar, and the system's back gesture respected"),
    ("ios", "iOS app", ["phone", "landscape"], "SF Pro, the platform's own",
     "an iOS app: the Human Interface Guidelines' tab bar and navigation bar, 44pt touch "
     "targets, and Dynamic Type respected"),
    ("linux", "Linux app", ["desktop"], "the desktop's own (Cantarell on GNOME, Noto Sans on KDE)",
     "a Linux desktop app: the desktop's toolkit conventions (the GNOME or KDE guidelines), "
     "a header bar of the window's own, and the desktop's controls"),
    ("macos", "macOS app", ["desktop"], "SF Pro, the platform's own",
     "a macOS app: a sidebar and toolbar in the platform's shape, the menu bar carrying every "
     "command, and the system's own controls"),
    ("windows", "Windows app", ["desktop"], "Segoe UI Variable, the platform's own",
     "a Windows app: Fluent's spacing and controls, a navigation view for the app's sections, "
     "and the title bar the platform draws"),
]
PLATFORM_KEYS = [k for k, *_ in PLATFORMS]

# The rest of a language: each a fixed set of choices, so a prompt and a
# file say the same words for the same choice.
FONTS = [
    ("system", "System sans", "the platform's own sans-serif (system-ui), so the app reads as native"),
    ("humanist", "Humanist sans", "a warm sans-serif such as Source Sans or Lato"),
    ("geometric", "Geometric sans", "a geometric sans-serif such as Inter or Manrope"),
    ("serif", "Serif", "a readable serif such as Source Serif or Georgia, for prose"),
    ("mono", "Monospace", "a monospace such as JetBrains Mono, everywhere, for a terminal feel"),
]
CORNERS = [
    ("square", "Square", "no rounding anywhere"),
    ("soft", "Soft", "small radii: 6px on controls, 8px on boxes, 4px on tags"),
    ("round", "Round", "generous radii: 10px on controls, 14px on boxes, and pills for tags"),
]
DENSITY = [
    ("compact", "Compact", "tight rows and small gaps, for a tool used all day"),
    ("comfortable", "Comfortable", "an ordinary rhythm: 11px by 14px bands, 10px between fields"),
    ("spacious", "Spacious", "generous space around everything, for a page read rather than worked"),
]
MOTION = [
    ("quiet", "Quiet", "short eases on state changes, nothing decorative, and none under prefers-reduced-motion"),
    ("none", "None", "no animation at all"),
    ("lively", "Lively", "things arrive and leave with motion, still off under prefers-reduced-motion"),
]
CHOICES = {"font": FONTS, "corners": CORNERS, "density": DENSITY, "motion": MOTION}

def theme_from(scheme_key, name=""):
    """A theme filled from a preset scheme: the ten colours, named and
    explained, in the scheme's hexes, dark or light by its background."""
    key, label, colors = next((row for row in SCHEMES if row[0] == scheme_key), SCHEMES[0])
    # The preset's label says "(light)" to tell the pickers apart; a theme
    # says its mode beside its name, so the name is the bare word.
    return {"name": name or label.replace(" (light)", ""), "mode": "light" if _luma(colors["bg"]) > 0.5 else "dark",
            "colors": [{"name": k, "hex": colors[k], "means": means} for k, _, means in TOKENS]}


def _luma(hexcol):
    r, g, b = (int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


LANGUAGE_DEFAULT = {"themes": [], "font": "system", "corners": "soft", "density": "comfortable",
                    "motion": "quiet", "scope": "", "rules": [], "fonts": ""}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def configure(*, workspace, state, write_json, git_env=None):
    globals().update(WORKSPACE=Path(workspace), FILE=Path(state) / "designs.json",
                     write_json=write_json, git_env=git_env)
    # The approval queue (roadmap #27): a session's save under ask waits
    # for the operator, who approves it on the notebook, and it lands then.
    pending.configure(write_json=write_json, state=state)
    pending.applier("design", replay)


def replay(project, verb, args):
    """A held save, approved: the same save, as the session's."""
    if verb != "save":
        return {"error": f"nothing to replay for design {verb}"}
    r, st = save(project, args if isinstance(args, dict) else {}, "claude")
    return r if st == 200 else {"error": r.get("error") or "the save failed"}


def _load():
    try:
        with open(FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _record(d, project):
    rec = d.get(project)
    if not isinstance(rec, dict):
        rec = {}
    lang = _clean_language(rec.get("language") or {})
    # A page saved before pages had rules of their own reads as one with none.
    pages = [{**p, "rules": p.get("rules") if isinstance(p.get("rules"), list) else []}
             for p in (rec.get("pages") or []) if isinstance(p, dict)]
    return {"language": lang, "pages": pages, "next": int(rec.get("next") or 1),
            "by": str(rec.get("by") or ""), "at": int(rec.get("at") or 0)}


# ---- validation: what is kept is what the vocabulary allows -------------------
class _Refused(Exception):
    pass


def _choice(value, keys, what, dflt):
    v = str(value or dflt)
    if v not in keys:
        raise _Refused(f"{what}: no such choice, {v!r}")
    return v


def _line(value, cap, what):
    v = " ".join(str(value or "").split())
    if len(v) > cap:
        raise _Refused(f"{what} is at most {cap} characters")
    return v


def _clean_colour(m, what):
    if not isinstance(m, dict):
        raise _Refused(f"a colour in {what} is an object: name, hex, means")
    name = _line(m.get("name"), 40, "a colour's name")
    hexv = str(m.get("hex") or "").strip().lower()
    if not _HEX.match(hexv):
        raise _Refused(f"{name or 'a colour'} in {what}: a colour is #rrggbb, not {hexv!r}")
    return {"name": name, "hex": hexv, "means": _line(m.get("means"), NAME_MAX, "what a colour is for")}


def _clean_theme(t, n):
    """A theme as stored: a name, dark or light, and its colours, each
    named once."""
    if not isinstance(t, dict):
        raise _Refused("a theme is an object: name, mode, colors")
    name = _line(t.get("name"), 40, "a theme's name") or f"Theme {n}"
    mode = str(t.get("mode") or "")
    raw = [c for c in (t.get("colors") if isinstance(t.get("colors"), list) else []) if isinstance(c, dict)
           and str(c.get("name") or "").strip()]
    if len(raw) > COLORS_MAX:
        raise _Refused(f"{name} holds at most {COLORS_MAX} colours")
    colors, seen = [], set()
    for c in raw:
        c = _clean_colour(c, name)
        if c["name"].lower() in seen:
            raise _Refused(f"{name} names {c['name']} twice")
        seen.add(c["name"].lower())
        colors.append(c)
    if mode not in MODES:
        bg = _role({"colors": colors}, "bg")
        mode = "light" if bg and _luma(bg) > 0.5 else "dark"
    return {"name": name, "mode": mode, "colors": colors,
            "rules": _clean_rules(t.get("rules"), f"the theme {name}")}


def _clean_language(lang):
    """A language as stored, from whatever arrived: every choice one of the
    vocabulary's, every colour a hex, the notes capped. A record from before
    themes (one scheme and its ten colours) is read as one theme."""
    if not isinstance(lang, dict):
        lang = {}
    out = dict(LANGUAGE_DEFAULT)
    if "themes" not in lang and ("colors" in lang or "scheme" in lang):
        scheme = str(lang.get("scheme") or "default")
        base = theme_from(scheme if scheme in SCHEME_KEYS else "default",
                          "Custom" if scheme not in SCHEME_KEYS else "")
        colors = lang.get("colors") if isinstance(lang.get("colors"), dict) else {}
        for c in base["colors"]:
            c["hex"] = str(colors.get(c["name"]) or c["hex"]).strip().lower()
        base["colors"] += [m for m in (lang.get("more") or []) if isinstance(m, dict)]
        lang = {**lang, "themes": [base]}
    raw = lang.get("themes") if isinstance(lang.get("themes"), list) else []
    if len(raw) > THEMES_MAX:
        raise _Refused(f"a language holds at most {THEMES_MAX} themes")
    themes, names = [], set()
    for i, t in enumerate(raw):
        t = _clean_theme(t, i + 1)
        if t["name"].lower() in names:
            raise _Refused(f"two themes are called {t['name']}")
        names.add(t["name"].lower())
        themes.append(t)
    # None is a language too (the operator, 29 Sep): a project designed by
    # its first session starts empty, and the session fills it in.
    out["themes"] = themes
    for key, rows in CHOICES.items():
        out[key] = _choice(lang.get(key), [k for k, _, _ in rows], key, LANGUAGE_DEFAULT[key])
    out["scope"] = _line(lang.get("scope"), NAME_MAX, "what the language governs")
    out["fonts"] = _line(lang.get("fonts"), 200, "the font families")
    out["rules"] = _clean_rules(lang.get("rules"), "a language")
    return out


def _bits(v):
    """Triggers as a list, from a list or the line somebody typed."""
    parts = [str(x) for x in v] if isinstance(v, (list, tuple)) else re.split(r"[,\s]+", str(v or ""))
    return [p.strip() for p in parts if p.strip() and re.search(r"[A-Za-z0-9]", p)][:24]


def _clean_rule(r, i):
    """A design rule as stored: a slug name, its text, and what fires it."""
    name = re.sub(r"[^a-z0-9]+", "-", str(r.get("name") or "").strip().lower()).strip("-")[:40].strip("-")
    if not RULE_NAME.match(name):
        name = f"design-{i + 1}"
    text = str(r.get("text") or "").strip()
    if len(text) > RULE_TEXT_MAX:
        raise _Refused(f"the rule {name} is at most {RULE_TEXT_MAX} characters")
    if not text:
        raise _Refused(f"the rule {name} says nothing")
    return {"name": name, "text": text, "words": [w.lower() for w in _bits(r.get("words"))],
            "paths": [p.replace("\\", "/").lstrip("/") for p in _bits(r.get("paths")) if ".." not in p.split("/")]}


def _clean_rules(raw, whose):
    """A list of rules as stored, each named once within `whose` (the
    language, a theme or a page): the operator asked for rules of a theme's
    own and a page's own (28 Sep), since the Nostromo scheme has needs no
    other theme shares."""
    if isinstance(raw, str):
        # The notes from before rules: one standing rule, kept whole.
        raw = [{"name": "design-notes", "text": raw}] if raw.strip() else []
    raw = [r for r in (raw if isinstance(raw, list) else []) if isinstance(r, dict)]
    if len(raw) > RULES_MAX:
        raise _Refused(f"{whose} holds at most {RULES_MAX} rules")
    rules, names = [], set()
    for i, r in enumerate(raw):
        r = _clean_rule(r, i)
        if r["name"] in names:
            raise _Refused(f"{whose} has two rules called {r['name']}")
        names.add(r["name"])
        rules.append(r)
    return rules


def scoped_rules(rec):
    """Every rule the design carries, with the theme's or the page's rules
    named under it: `nostromo/hull` is the Nostromo theme's rule hull, and
    `bb design show nostromo/hull` reads it. [(name, rule, holder)]."""
    lang = rec["language"]
    out = [(r["name"], r, "") for r in lang["rules"]]
    for t in lang["themes"]:
        out += [(f"{_slug(t['name'])}/{r['name']}", r, f"the {t['name']} theme") for r in t.get("rules") or []]
    for p in rec["pages"]:
        out += [(f"{_slug(p['name'] or 'page-' + str(p['id']))}/{r['name']}", r, p["name"] or f"page {p['id']}")
                for r in p.get("rules") or []]
    return out


def saved(project):
    """The project's record when somebody saved one (the briefing's line),
    None when the design is still the default nobody touched."""
    rec = _record(_load(), project)
    return rec if rec["at"] else None


def rules_for(project, state=None):
    """The design's rules in the house rules' shape, for rules.effective:
    the operator's, marked as the design's, each pointing at the file the
    view writes. Read from the store by path, so the rules module can ask
    without this one being configured."""
    path = FILE if state is None else Path(state) / "designs.json"
    try:
        with open(path, encoding="utf-8") as f:
            rec = (json.load(f) or {}).get(project) or {}
    except (OSError, ValueError, TypeError, AttributeError):
        return []
    try:
        full = _record({project: rec}, project)
    except _Refused:
        return []
    return [{"name": name, "text": r["text"] if not holder else f"For {holder}. {r['text']}",
             "paths": list(r.get("paths") or []), "words": list(r.get("words") or []),
             "doc": "", "check": "", "by": "you", "at": int(rec.get("at") or 0), "design": True}
            for name, r, holder in scoped_rules(full)]


# What a colour is for, by the names a design gives it: the board and the
# prompt read a theme's background, surface, text, edge and accent by role
# whatever they are called.
ROLES = {"bg": ("bg", "background", "page", "page-bg", "cream", "felt"),
         "panel": ("panel", "surface", "card", "frost", "surface-1"),
         "ink": ("ink", "text", "text-primary", "fg", "foreground"),
         "dim": ("dim", "muted", "text-muted", "secondary"),
         "line": ("line", "border", "edge", "outline"),
         "accent": ("accent", "primary", "gold", "brand"),
         "good": ("good", "ok", "success"),
         "warn": ("warn", "warning"),
         "bad": ("bad", "danger", "error"),
         "note": ("note", "info")}


def _role(theme, role):
    """The hex a theme gives a role, by any of the names designs use for
    it, or "" when it names none."""
    names = ROLES.get(role, (role,))
    for c in theme.get("colors") or []:
        if c["name"].lower() in names:
            return c["hex"]
    return ""


def _clean_block(b, frame):
    if not isinstance(b, dict):
        raise _Refused("a block is an object")
    g = FRAMES[frame]
    kind = _choice(b.get("kind"), KIND_KEYS, "block kind", "content")
    try:
        x, y, w, h = (int(b.get(k, 0)) for k in ("x", "y", "w", "h"))
    except (TypeError, ValueError):
        raise _Refused("a block's cells are whole numbers") from None
    w, h = max(1, w), max(1, h)
    x = min(max(0, x), g["cols"] - 1)
    y = min(max(0, y), g["rows"] - 1)
    w = min(w, g["cols"] - x)
    h = min(h, g["rows"] - y)
    return {"kind": kind, "label": _line(b.get("label"), NAME_MAX, "a block's label"),
            "x": x, "y": y, "w": w, "h": h}


def _clean_page(p, pid):
    if not isinstance(p, dict):
        raise _Refused("a page is an object")
    platform = _choice(p.get("platform"), PLATFORM_KEYS, "platform", "web")
    # A frame the platform has: a page switched to Android keeps its
    # blocks and takes the phone frame, where they are clamped.
    frames = _platform(platform)[2]
    frame = str(p.get("frame") or frames[0])
    if frame not in frames:
        frame = frames[0]
    blocks = p.get("blocks") if isinstance(p.get("blocks"), list) else []
    if len(blocks) > MAX_BLOCKS:
        raise _Refused(f"a page holds at most {MAX_BLOCKS} blocks")
    notes = str(p.get("notes") or "").strip()
    if len(notes) > NOTES_MAX:
        raise _Refused(f"a page's notes are at most {NOTES_MAX} characters")
    name = _line(p.get("name"), NAME_MAX, "a page's name")
    return {"id": pid, "name": name,
            "platform": platform, "template": _choice(p.get("template"), TEMPLATE_KEYS, "template", "blank"),
            "frame": frame, "blocks": [_clean_block(b, frame) for b in blocks],
            "notes": notes, "rules": _clean_rules(p.get("rules"), f"the page {name or pid}"),
            "at": int(time.time())}


# ---- what the tab and bb read ---------------------------------------------------
def presets():
    """The vocabulary, for the tab to draw its pickers from: one copy, here."""
    return {"kinds": [{"key": k, "label": l, "means": m} for k, l, m in KINDS],
            "frames": {k: dict(v) for k, v in FRAMES.items()},
            "templates": [{"key": t["key"], "label": t["label"], "frame": t["frame"],
                           "blocks": [dict(zip(("kind", "label", "x", "y", "w", "h"), b, strict=True)) for b in t["blocks"]]}
                          for t in TEMPLATES],
            "platforms": [{"key": k, "label": l, "frames": list(f), "system": sf, "means": m}
                          for k, l, f, sf, m in PLATFORMS],
            "tokens": [{"key": k, "label": l, "means": m} for k, l, m in TOKENS],
            "schemes": [{"key": k, "label": l, "colors": dict(c)} for k, l, c in SCHEMES],
            "choices": {key: [{"key": k, "label": l, "means": m} for k, l, m in rows]
                        for key, rows in CHOICES.items()},
            "modes": list(MODES), "themes_max": THEMES_MAX, "colors_max": COLORS_MAX, "rules_max": RULES_MAX,
            "roles": {k: list(v) for k, v in ROLES.items()},
            "file": FILE_PATH}


def _file_state(project, rec):
    """Whether docs/design-language.md is there and is what the saved
    state would write, so the tab can say 'written' or 'behind'."""
    p = WORKSPACE / project / FILE_PATH
    try:
        have = p.read_text(encoding="utf-8") if p.is_file() else None
    except OSError:
        have = None
    return {"path": FILE_PATH, "exists": have is not None,
            "current": have is not None and have == file_text(rec)}


def view(project):
    """GET /api/design: the saved record, the vocabulary and the file's
    state. Whether a session is running to send to is the page's poll."""
    rec = _record(_load(), project)
    return {"language": rec["language"], "pages": rec["pages"], "presets": presets(),
            "file": _file_state(project, rec), "by": rec["by"], "at": rec["at"]}


# ---- the words ------------------------------------------------------------------
def _means(rows, key):
    return next((m for k, _, m in rows if k == key), "")


def _label(rows, key):
    return next((label for k, label, _ in rows if k == key), key)


def _where(b, frame):
    """A block's place in words: which part of the frame, and how much."""
    g = FRAMES[frame]
    cols, rows = g["cols"], g["rows"]
    full_w = b["w"] >= cols
    top = b["y"] == 0
    bottom = b["y"] + b["h"] >= rows
    left = b["x"] == 0
    right = b["x"] + b["w"] >= cols
    if full_w and top and bottom:
        return "filling the frame"
    where_rows = f"rows {b['y'] + 1} to {b['y'] + b['h']} of {rows}" if b["h"] > 1 else f"row {b['y'] + 1} of {rows}"
    where_cols = f"columns {b['x'] + 1} to {b['x'] + b['w']} of {cols}" if b["w"] > 1 else f"column {b['x'] + 1} of {cols}"
    if full_w:
        band = "across the top" if top else "across the bottom" if bottom else "across the middle"
        return f"{band}, {where_rows}"
    side = ("the left" if left and not right else "the right" if right and not left
            else "the middle")
    if b["h"] >= rows:
        return f"down {side}, full height, {where_cols}"
    return f"{'in' if side == 'the middle' else 'on'} {side}, {where_cols}, {where_rows}"


def _platform(key):
    return next((row for row in PLATFORMS if row[0] == key), PLATFORMS[0])


def _font_means(lang, platform=""):
    """What the font choice means: the system font is a different face on
    each platform, so a page's prompt names the one its platform has, and
    the language alone names them all."""
    if lang["font"] != "system":
        return _means(FONTS, lang["font"])
    if platform:
        return _platform(platform)[3]
    return ("the platform's own sans-serif: " + ", ".join(
        f"{row[3].split(',')[0].split(' (')[0]} on {row[1].split(' ')[0]}" for row in PLATFORMS))


def language_text(lang, platform=""):
    """The language as prose a session applies: every choice and its meaning."""
    themes = lang["themes"]
    lines = []
    if not themes:
        lines.append("Colours: none chosen yet. Choose them as tokens a stylesheet names once and every "
                     "surface reads, and put them into the design (bb design save) as a theme, named, dark or light.")
    elif len(themes) == 1:
        t = themes[0]
        lines.append(f"Colours ({t['name']}, {t['mode']}), as tokens a stylesheet names once and every "
                     "surface reads, never a hex in a component:")
        lines.extend(f"  {c['name']} {c['hex']}" + (f": {c['means']}" if c["means"] else "") for c in t["colors"])
    else:
        lines.append(f"Themes, each a set of the same tokens, which a stylesheet names once and every "
                     f"surface reads, never a hex in a component. The app starts on {themes[0]['name']}; "
                     "a theme picker, where the app has one, offers them by name:")
        for i, t in enumerate(themes):
            lines.append(f"  {t['name']} ({t['mode']}{', the default' if i == 0 else ''}):")
            lines.extend(f"    {c['name']} {c['hex']}" + (f": {c['means']}" if c["means"] else "") for c in t["colors"])
            lines.extend(_rule_lines(t.get("rules") or [], f"{t['name']}'s own rules", _slug(t["name"]), "    "))
    if len(themes) == 1:
        lines.extend(_rule_lines(themes[0].get("rules") or [], f"{themes[0]['name']}'s own rules", _slug(themes[0]["name"]), "  "))
    lines.append("A filled accent surface carries the text colour on it, at AA contrast.")
    lines.append(f"Type: {_font_means(lang, platform)}"
                 + (f", set as {lang['fonts']}" if lang.get("fonts") else "")
                 + "; monospace for data (names, paths, numbers).")
    lines.append(f"Shape: {_means(CORNERS, lang['corners'])}; hairlines 1px in the edge colour.")
    lines.append(f"Space: {_means(DENSITY, lang['density'])}.")
    lines.append(f"Motion: {_means(MOTION, lang['motion'])}.")
    standing = [r for r in lang["rules"] if not (r["words"] or r["paths"])]
    named = [r for r in lang["rules"] if r["words"] or r["paths"]]
    for r in standing:
        lines.append(f"{r['name']}: {r['text']}")
    if named:
        lines.append("Design rules, named, not quoted: `bb design show NAME` reads one, and its text "
                     "arrives on the turn you edit a file or are asked about a word it names.")
        lines.extend(f"  {r['name']}: " + "; ".join(x for x in [", ".join(r["paths"]), ", ".join(r["words"])] if x)
                     for r in named)
    return "\n".join(lines)


def _rule_lines(rules, head, scope, indent):
    """A theme's or a page's own rules as prose under it: a standing one
    whole, a triggered one by its scoped name and what fires it."""
    if not rules:
        return []
    out = [f"{indent}{head}:"]
    for r in rules:
        on = "; ".join(x for x in [", ".join(r["paths"]), ", ".join(r["words"])] if x)
        out.append(f"{indent}  {scope}/{r['name']}: " + (f"{on} (`bb design show {scope}/{r['name']}` reads it)" if on else r["text"]))
    return out


def _slug(name):
    """A colour's name as a CSS token: letters, digits and dashes."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "colour"


def _cap(text):
    """The first letter up and the rest as written: str.capitalize lowers
    the rest, and Material became material."""
    return text[:1].upper() + text[1:]


def page_text(page):
    """A page's layout as prose: each block, what it is for, and where."""
    g = FRAMES[page["frame"]]
    plat = _platform(page["platform"])
    lines = [f"Platform: {plat[4]}.",
             f"Layout of {page['name'] or 'this page'} on a {page['frame']} frame "
             f"({g['cols']} columns by {g['rows']} rows), from the {_label([(t['key'], t['label'], '') for t in TEMPLATES], page['template'])} template:"]
    if not page["blocks"]:
        lines.append("  (no blocks placed yet)")
    for b in sorted(page["blocks"], key=lambda b: (b["y"], b["x"])):
        what = f": {b['label']}" if b["label"] else ""
        lines.append(f"  {_label(KINDS, b['kind'])} ({_means(KINDS, b['kind'])}){what}, {_where(b, page['frame'])}")
    if page.get("notes"):
        lines.append("Notes:")
        lines.extend("  " + ln for ln in page["notes"].splitlines() if ln.strip())
    lines.extend(_rule_lines(page.get("rules") or [], "This page's own rules",
                             _slug(page["name"] or f"page-{page['id']}"), ""))
    return "\n".join(lines)


def prompt(lang, page=None):
    """What a session is asked to do, in full: the text the tab shows under
    a page and `bb design show` prints. The language alone when no page."""
    scope = lang.get("scope") or "the project's user interface"
    if page is None:
        head = (f"Apply this design language to {scope}. Put the tokens in one place the whole "
                f"stylesheet reads, and keep {FILE_PATH} in step with what you build.")
        return head + "\n\n" + language_text(lang)
    target = page["name"] or "this page"
    head = (f"Build or restyle {target} to this layout, in the project's design language. "
            f"Keep what the blocks are for, at every width, and keep {FILE_PATH} in step.")
    return head + "\n\n" + page_text(page) + "\n\n" + language_text(lang, page["platform"])


def file_text(rec):
    """docs/design-language.md for a project: its language and its pages,
    the shape BuilderBot's own file has, generated from the saved state so
    it cannot say what the notebook no longer does."""
    lang, pages = rec["language"], rec["pages"]
    out = ["# The design language", "",
           "What this project looks like, in one place. Written by BuilderBot's Design view "
           "from the notebook, so edit it there, or edit here and say so in the notebook. "
           "Every surface follows it; a change to the look is a change to this file first.", ""]
    if lang.get("scope"):
        out += [f"It governs {lang['scope']}.", ""]
    themes = lang["themes"]
    out += ["## Colour", "",
            ("No theme chosen yet: the colours are tokens named once in the stylesheet, and the first "
             "session to choose them puts them here." if not themes else
             "Colour comes only from these tokens, named once in the stylesheet"
             + (f". The app starts on {themes[0]['name']}; a theme picker, where the app has one, "
                "offers the themes by name, and every theme names the same tokens:" if len(themes) > 1 else ":"))]
    for i, t in enumerate(themes):
        if len(themes) > 1:
            out += ["", f"### {t['name']} ({t['mode']}{', the default' if i == 0 else ''})"]
        out += ["", "| token | value | for |", "|---|---|---|"]
        out += [f"| `--{_slug(c['name'])}` | `{c['hex']}` | {c['means']} |" for c in t["colors"]]
        out += _file_rules(t.get("rules") or [], _slug(t["name"]), f"Rules of {t['name']}'s own", "####")
    out += ["", "A filled accent surface carries the text colour on it, at AA contrast.", "",
            "## Type", "", _cap(_font_means(lang)) + (f", set as {lang['fonts']}" if lang.get("fonts") else "")
            + ". Monospace for data: names, paths, numbers.", "",
            "## Shape", "", _cap(_means(CORNERS, lang["corners"])) + ". Hairlines are 1px in `--line`.", "",
            "## Space", "", _cap(_means(DENSITY, lang["density"])) + ".", "",
            "## Motion", "", _cap(_means(MOTION, lang["motion"])) + "."]
    if lang["rules"]:
        out += ["", "## Rules", "",
                "Each is one rule of the design, by name; a session is handed one on the turn it edits a "
                "file or is asked about a word the rule names, and `bb design show NAME` reads one."]
        for r in lang["rules"]:
            on = "; ".join(x for x in [", ".join(r["paths"]), ", ".join(r["words"])] if x)
            out += ["", f"### {r['name']}", ""] + ([f"Applies to: {on}", ""] if on else []) + [r["text"]]
    if pages:
        out += ["", "## Pages", "",
                "Each page is a layout of labelled blocks on a frame, named for what it is for, "
                "on the platform it is built for."]
        for p in pages:
            out += ["", f"### {p['name'] or 'unnamed page'} ({_platform(p['platform'])[1]})", "", page_text(p)]
            out += _file_rules(p.get("rules") or [], _slug(p["name"] or f"page-{p['id']}"),
                               f"Rules of {p['name'] or 'this page'}'s own", "####")
    return "\n".join(out).rstrip() + "\n"


def _file_rules(rules, scope, head, level):
    """A theme's or a page's own rules in the file, each under its scoped
    name, the way the language's rules are under Rules."""
    if not rules:
        return []
    out = ["", f"{level} {head}"]
    for r in rules:
        on = "; ".join(x for x in [", ".join(r["paths"]), ", ".join(r["words"])] if x)
        out += ["", f"{level}# {scope}/{r['name']}", ""] + ([f"Applies to: {on}", ""] if on else []) + [r["text"]]
    return out


# ---- writes ----------------------------------------------------------------------
def save(project, req, who=""):
    """The notebook's Save, and a session's bb design save: the whole record
    replaced by what was staged, each page keeping its id (a new one gets
    the next), with who saved it and when. (payload, status)."""
    try:
        lang = _clean_language(req.get("language") or {})
        raw = req.get("pages") if isinstance(req.get("pages"), list) else []
        if len(raw) > MAX_PAGES:
            raise _Refused(f"a project holds at most {MAX_PAGES} pages")
    except _Refused as e:
        return {"error": str(e)}, 400
    with statefile.locked(FILE):
        d = _load()
        rec = _record(d, project)
        nxt = rec["next"]
        pages = []
        try:
            for p in raw:
                pid = p.get("id") if isinstance(p, dict) else None
                if not isinstance(pid, int) or pid < 1:
                    pid, nxt = nxt, nxt + 1
                pages.append(_clean_page(p, pid))
        except _Refused as e:
            return {"error": str(e)}, 400
        seen = set()
        for p in pages:
            if p["id"] in seen:
                return {"error": "two pages carry one id"}, 400
            seen.add(p["id"])
        d[project] = {"language": lang, "pages": pages, "next": nxt,
                      "by": str(who or ""), "at": int(time.time())}
        write_json(FILE, d)
    return {"ok": True, "language": lang, "pages": pages}, 200


def write_file(project, who=""):
    """Write docs/design-language.md from the saved state, not committed:
    the session applying the design commits it with the work, and the Git
    view shows it changed until then. (payload, status)."""
    rec = _record(_load(), project)
    p = WORKSPACE / project / FILE_PATH
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(file_text(rec), encoding="utf-8")
    except OSError as e:
        return {"error": f"could not write {FILE_PATH}: {e}"}, 500
    return {"ok": True, "path": FILE_PATH, "file": _file_state(project, rec)}, 200


def _unfinished_out(holder):
    """`holder` (a language, a theme or a page as sent) without the rules
    that have no text yet, at every level, for a preview asked mid-typing."""
    if not isinstance(holder, dict):
        return holder
    out = dict(holder)
    if isinstance(out.get("rules"), list):
        out["rules"] = [r for r in out["rules"] if isinstance(r, dict) and str(r.get("text") or "").strip()]
    if isinstance(out.get("themes"), list):
        out["themes"] = [_unfinished_out(t) for t in out["themes"]]
    return out


def verb(project, req, who, session):
    """POST /api/design. A person saves from the tab; a session saves the
    same record through `bb design save`, asked to put a design language
    it was given, or found in the tree, into the notebook. The file is a
    person's: a session writes it itself with bb design file.
    (payload, status)."""
    act = str(req.get("action") or "")
    if session and act == "write":
        return {"error": "a session reads the design with bb design and writes the file with "
                         "bb design file; Write the file is the tab's"}, 403
    if act == "preview":
        # A preview is asked for mid-typing, a keystroke after Add rule, so
        # a rule with no text yet is left out of it rather than refused:
        # the refusal is Save's, and a 400 here was a console error and a
        # flake in the whole run (B341).
        try:
            lang = _clean_language(_unfinished_out(req.get("language") or {}))
            page = _clean_page(_unfinished_out(req["page"]), 0) if isinstance(req.get("page"), dict) else None
        except _Refused as e:
            return {"error": str(e)}, 400
        return {"text": prompt(lang, page)}, 200
    if act == "save":
        # A session's save is the project's dial, Claude may: Add to the
        # design (auto lands it, ask holds it for the operator, deny refuses
        # it by name); a person's from the tab always lands.
        if session and not pending.replaying():
            g = pending.mode(project, "design")
            if g == "deny":
                return {"error": pending.refusal("design")}, 403
            if g == "ask":
                try:
                    lang = _clean_language(req.get("language") or {})
                    pages = [_clean_page(p, 0) for p in (req.get("pages") if isinstance(req.get("pages"), list) else [])]
                except _Refused as e:
                    return {"error": str(e)}, 400
                names = ", ".join(t["name"] for t in lang["themes"])
                r = pending.hold(project, "design", "save",
                                 {"language": req.get("language") or {}, "pages": req.get("pages") or []},
                                 summary=f"the design: {len(lang['themes'])} theme{'' if len(lang['themes']) == 1 else 's'} ({names}), "
                                         f"{len(lang['rules'])} rule{'' if len(lang['rules']) == 1 else 's'}, {len(pages)} page{'' if len(pages) == 1 else 's'}")
                if r.get("error"):
                    return r, 400
                return {"ok": True, "held": r["held"]}, 202
        return save(project, req, who)
    if act == "write":
        return write_file(project, who)
    return {"error": f"unknown action: {act}"}, 400


def text_for(project, which=""):
    """bb design: the list (`list`), the prompt for the language
    (`language`) or for one page by id or name, or the file's text
    (`file`). (text, error)."""
    rec = _record(_load(), project)
    if which == "list":
        return listing(project), ""
    if which == "json":
        return json.dumps({"language": rec["language"], "pages": rec["pages"],
                           "presets": presets()}, indent=1), ""
    if which == "file":
        return file_text(rec), ""
    if which == "language":
        return prompt(rec["language"]), ""
    hit = next(((n, r, h) for n, r, h in scoped_rules(rec) if n == which.lower()), None)
    if hit is not None:
        name, rule, holder = hit
        on = "; ".join(x for x in [", ".join(rule["paths"]), ", ".join(rule["words"])] if x)
        return (name + (f" (for {holder})" if holder else "") + (f" (applies to: {on})" if on else "")
                + "\n\n" + rule["text"]), ""
    theme = next((t for t in rec["language"]["themes"] if t["name"].lower() == which.lower()
                  or _slug(t["name"]) == which.lower()), None)
    if theme is not None:
        lines = [f"{theme['name']} ({theme['mode']}), one theme of {len(rec['language']['themes'])}:"]
        lines.extend(f"  {c['name']} {c['hex']}" + (f": {c['means']}" if c["means"] else "") for c in theme["colors"])
        for r in theme.get("rules") or []:
            on = "; ".join(x for x in [", ".join(r["paths"]), ", ".join(r["words"])] if x)
            lines += ["", f"{_slug(theme['name'])}/{r['name']}" + (f" (applies to: {on})" if on else ""), r["text"]]
        return "\n".join(lines), ""
    page = next((p for p in rec["pages"] if str(p["id"]) == which or p["name"].lower() == which.lower()), None)
    if page is None:
        return "", f"no page, theme or rule here called {which!r}: bb design lists them"
    return prompt(rec["language"], page), ""


def listing(project):
    """bb design with no words: the language in one line and the pages."""
    rec = _record(_load(), project)
    lang = rec["language"]
    themes = ", ".join(f"{t['name']} ({t['mode']})" for t in lang["themes"]) or "no theme yet"
    lines = [f"{project}'s design language: {themes}; {_label(FONTS, lang['font']).lower()}, "
             f"{lang['corners']} corners, {lang['density']}, {lang['motion']} motion"
             + (f"; it governs {lang['scope']}" if lang.get("scope") else "")]
    if lang["rules"]:
        lines.append(f"  {len(lang['rules'])} design rule{'' if len(lang['rules']) == 1 else 's'}: "
                     + ", ".join(r["name"] for r in lang["rules"][:12]) + (", ..." if len(lang["rules"]) > 12 else ""))
    own = [n for n, _, h in scoped_rules(rec) if h]
    if own:
        lines.append(f"  {len(own)} rule{'' if len(own) == 1 else 's'} of a theme's or a page's own: "
                     + ", ".join(own[:8]) + (", ..." if len(own) > 8 else ""))
    if not rec["pages"]:
        lines.append("  no pages yet: the notebook's Design view adds one")
    for p in rec["pages"]:
        lines.append(f"  {p['id']:>3}  {p['name'] or '(unnamed)'}  ({_platform(p['platform'])[1].lower()}, {p['frame']}, {len(p['blocks'])} block"
                     f"{'' if len(p['blocks']) == 1 else 's'})")
    if rec["by"]:
        lines.append(f"  last saved by {rec['by']} {time.strftime('%d %b %H:%M', time.localtime(rec['at']))}")
    lines.append(f"bb design show [ID|NAME] prints one in full; bb design file prints {FILE_PATH}; "
                 "bb design json prints the record, and bb design save FILE writes one back")
    return "\n".join(lines)


# Every preset passes its own validation, so a template or a scheme that
# drifts from the vocabulary fails at import rather than at the first save.
for _k, _l, _c in SCHEMES:
    _clean_language({"scheme": _k, "colors": _c})
for _t in TEMPLATES:
    _clean_page({"frame": _t["frame"], "template": _t["key"],
                 "blocks": [dict(zip(("kind", "label", "x", "y", "w", "h"), b, strict=True)) for b in _t["blocks"]]}, 1)
