"""The notebook's Design view: a project's design language and its pages.

The one thing the dashboard had no say in was what a project looks like:
every color, font and layout was a sentence typed into a session and
gone with the conversation. This keeps them. A project has ONE design
language (colors as tokens, type, shape, space, and the design notes the
operator adds in their own words, for everything the settings cannot say) and any number of PAGES, each a layout of labeled
blocks arranged on a phone or desktop frame and named for what it is for
("the settings page"). The name is the target: applying a page's design
means applying it there.

Two things come out of it, both generated here and nowhere else, so the
tab, `bb design` and the file cannot drift:

  * the prose a session reads piece by piece with `bb design show`: the
    language, one page, one theme or one rule. The tab shows none of it
    (the operator, 29 Sep: a whole dump is not how a session should read
    a design), and nothing on the view reaches into a session;
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
import threading
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
# What a kind IS, and no more than that: a session reads the meaning beside
# every block, and one that said what the block must contain ("fields with
# one Save or Submit at the foot", "each opening to detail") held a page to
# things its design never said (a report from another project, 29 Sep).
KINDS = [
    ("button", "Button", "an action to press"),
    ("card", "Card", "a box holding one thing"),
    ("chart", "Chart", "a chart or a meter"),
    ("content", "Content", "the main reading or working area"),
    ("footer", "Footer", "the band at the foot"),
    ("form", "Form", "fields a person fills in"),
    ("header", "Header", "the band at the top"),
    ("hero", "Hero", "a large opening block"),
    ("image", "Image", "a picture or a media block"),
    ("list", "List", "rows of like things"),
    ("nav", "Navigation", "the way around: tabs or a menu"),
    ("overlay", "Overlay", "a dialog, sheet, drawer, popover or toast over the page"),
    ("search", "Search", "a search box"),
    ("sidebar", "Sidebar", "a side column"),
    ("table", "Table", "columns of data"),
    ("tabs", "Tabs", "a strip of tabs switching one area"),
    ("text", "Text", "a block of prose"),
]
KIND_KEYS = [k for k, _, _ in KINDS]

# The frames a page is laid out on: the grid a block's cells are counted in.
FRAMES = {"phone": {"cols": 6, "rows": 12, "label": "Phone"},
          "landscape": {"cols": 12, "rows": 6, "label": "Phone, sideways"},
          "desktop": {"cols": 12, "rows": 8, "label": "Desktop"}}
# A frame is one screen, and a page may be longer than one: it scrolls. Its
# rows are the frame's unless it says more, up to this many. Twelve stacked
# blocks did not fit the six rows of a phone held sideways at all. Twenty
# phone screens: at sixty, five of them, a page of 6012px on a phone (seven
# screens) had to be drawn shorter than it is (two projects, 29 Sep).
ROWS_MAX = 240

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

# The color tokens a language names, in the order a reader meets them:
# what the page is painted on, what sits on it, the text, the edges, then
# the four states. The names are the dashboard's own, so a session that
# knows one knows the other.
TOKENS = [
    ("bg", "Background", "the page"),
    ("panel", "Surface", "a raised box, a card, a bar"),
    ("ink", "Text", "the text"),
    ("dim", "Muted", "secondary text and labels"),
    ("line", "Edge", "hairlines and borders"),
    ("accent", "Accent", "the one color that means \"this is the one\": the active tab, the primary button, a link"),
    ("warn", "Warning", "a warning"),
    ("bad", "Danger", "an error, a destructive verb"),
    ("note", "Note", "an informational mark"),
    ("good", "Good", "success: a passing check, a legal move, a safe state"),
]
# A theme is a named list of colors, each a name, a hex and what it is
# for: the ten above are what a preset fills it with, and the operator adds
# a second surface, a chart ramp, a game's card colors, or takes one away.
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
    ("custom", "Custom", "as the design's own rules say"),
]
CORNERS = [
    ("square", "Square", "no rounding anywhere"),
    ("soft", "Soft", "small radii: 6px on controls, 8px on boxes, 4px on tags"),
    ("round", "Round", "generous radii: 10px on controls, 14px on boxes, and pills for tags"),
    ("custom", "Custom", "as the design's own rules say"),
]
DENSITY = [
    ("compact", "Compact", "tight rows and small gaps, for a tool used all day"),
    ("comfortable", "Comfortable", "an ordinary rhythm: 11px by 14px bands, 10px between fields"),
    ("spacious", "Spacious", "generous space around everything, for a page read rather than worked"),
    ("custom", "Custom", "as the design's own rules say"),
]
MOTION = [
    ("quiet", "Quiet", "short eases on state changes, nothing decorative, and none under prefers-reduced-motion"),
    ("none", "None", "no animation at all"),
    ("lively", "Lively", "things arrive and leave with motion, still off under prefers-reduced-motion"),
    ("custom", "Custom", "as the design's own rules say"),
]
CHOICES = {"font": FONTS, "corners": CORNERS, "density": DENSITY, "motion": MOTION}

def theme_from(scheme_key, name=""):
    """A theme filled from a preset scheme: the ten colors, named and
    explained, in the scheme's hexes, dark or light by its background."""
    key, label, colors = next((row for row in SCHEMES if row[0] == scheme_key), SCHEMES[0])
    # The preset's label says "(light)" to tell the pickers apart; a theme
    # says its mode beside its name, so the name is the bare word.
    return {"name": name or label.replace(" (light)", ""), "mode": "light" if _luma(colors["bg"]) > 0.5 else "dark",
            "colors": [{"name": k, "hex": colors[k], "means": means} for k, _, means in TOKENS]}


def _luma(hexcol):
    r, g, b = (int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# A design nobody has touched chooses nothing (the operator, 29 Sep): no
# theme, and no type, corners, space or motion either. Each of those four
# carries a sentence a session holds the work to, and while "quiet" was
# here by default a project's stylesheet was reported as falling short of
# a promise nobody had made.
# A language is its themes and what it governs; the choices (type, corners,
# space, motion), the font families, the custom rule each choice may name
# and the rules are each THEME's (the operator, 29 Sep). The first theme is
# the default, and its choices and rules are the design's: said bare, as
# the design's own; another theme's are said under it, where they differ.
LANGUAGE_DEFAULT = {"themes": [], "scope": ""}
THEME_CHOICES = {"font": "", "corners": "", "density": "", "motion": "", "fonts": "", "custom": {}}
# The four choices by the word the view labels each with.
CHOICE_WORDS = (("font", "type"), ("corners", "corners"), ("density", "space"), ("motion", "motion"))


def lead(lang):
    """The default theme, whose choices and rules are the design's, or a
    theme with nothing chosen when there is none yet."""
    themes = lang.get("themes") or []
    return themes[0] if themes else {"name": "", "mode": "", "colors": [], "rules": [], **THEME_CHOICES}


def open_choices(lang):
    """The choices of a language nobody has made yet, by the view's words:
    the default theme's."""
    t = lead(lang)
    return [word for key, word in CHOICE_WORDS if not t.get(key)]


# The four choices as the words and the file head them.
SAID = (("font", "Type", FONTS), ("corners", "Shape", CORNERS), ("density", "Space", DENSITY),
        ("motion", "Motion", MOTION))


def _custom_rule(theme, key):
    """The rule a theme's custom choice names, or None."""
    name = (theme.get("custom") or {}).get(key) if theme.get(key) == "custom" else None
    return next((r for r in theme.get("rules") or [] if r["name"] == name), None) if name else None


def _open_line(lang):
    """What is said of the choices still open, or "": a session makes them
    from what it builds and puts them into the design."""
    left = open_choices(lang)
    if not left:
        return ""
    return ("Not chosen yet: " + ", ".join(left) + ". Choose " + ("it" if len(left) == 1 else "each")
            + " from what you build, and put it into the design with `bb design save` "
              "(`bb design schema` names the choices; custom is the one for a design whose "
              "rules say it better than a choice can).")

# Six hex digits, or eight when a color carries its alpha: a glass theme's
# tokens do (B342), and a stylesheet reads #rrggbbaa as it reads #rrggbb.
_HEX = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")


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


# A save is refused whole with EVERYTHING wrong with it listed, so it is
# corrected once. While problems() collects, a validator that meets a
# problem notes it and goes on with a stand-in; outside that it refuses at
# once. Per thread: the server answers several at a time.
_collecting = threading.local()


def _bad(msg):
    found = getattr(_collecting, "found", None)
    if found is None:
        raise _Refused(msg)
    if msg not in found:
        found.append(msg)


def _choice(value, keys, what, dflt):
    """One of the vocabulary's, or "" for a choice nobody has made."""
    v = str(value or dflt)
    if v and v not in keys:
        _bad(f"{what}: no such choice, {v!r}; it is one of {', '.join(keys)}")
        return dflt
    return v


def _line(value, cap, what):
    v = " ".join(str(value or "").split())
    if len(v) > cap:
        _bad(f"{what} is at most {cap} characters, and this is {len(v)}: {v[:40]}...")
        return v[:cap]
    return v


def _clean_color(m, what):
    if not isinstance(m, dict):
        _bad(f"a color in {what} is an object (name, hex, means), not {str(m)[:40]!r}")
        return None
    name = _line(m.get("name"), 40, "a color's name")
    hexv = str(m.get("hex") or "").strip().lower()
    if not name and not hexv:
        return None                      # a row added and left blank
    if not name:
        _bad(f"a color in {what} has no name ({hexv})")
    if not _HEX.match(hexv):
        _bad(f"{name or 'a color'} in {what}: a color is #rrggbb or #rrggbbaa, not {hexv!r}")
        hexv = "#000000"
    return {"name": name, "hex": hexv, "means": _line(m.get("means"), NAME_MAX, "what a color is for")}


def _clean_theme(t, n):
    """A theme as stored: a name, dark or light, and its colors, each
    named once."""
    if not isinstance(t, dict):
        _bad(f"theme {n} is an object (name, mode, colors), not {str(t)[:40]!r}")
        t = {}
    name = _line(t.get("name"), 40, "a theme's name") or f"Theme {n}"
    mode = str(t.get("mode") or "")
    if mode and mode not in MODES:
        _bad(f"{name}: a theme is {' or '.join(MODES)}, not {mode!r}")
    raw = t.get("colors") if isinstance(t.get("colors"), list) else []
    if len(raw) > COLORS_MAX:
        _bad(f"{name} holds at most {COLORS_MAX} colors, and this has {len(raw)}")
        raw = raw[:COLORS_MAX]
    colors, seen = [], set()
    for c in raw:
        c = _clean_color(c, name)
        if c is None:
            continue
        if c["name"].lower() in seen:
            _bad(f"{name} names {c['name']} twice")
            continue
        seen.add(c["name"].lower())
        colors.append(c)
    if mode not in MODES:
        bg = _role({"colors": colors}, "bg")
        mode = "light" if bg and _luma(bg) > 0.5 else "dark"
    out = {"name": name, "mode": mode, "colors": colors,
           "rules": _clean_rules(t.get("rules"), f"the theme {name}")}
    for key, rows in CHOICES.items():
        out[key] = _choice(t.get(key), [k for k, _, _ in rows], key, "")
    out["fonts"] = _line(t.get("fonts"), 200, "the font families")
    out["custom"] = _clean_custom(t.get("custom"), out)
    return out


def _clean_language(lang):
    """A language as stored, from whatever arrived: every choice one of the
    vocabulary's, every color a hex, the notes capped. A record from before
    themes (one scheme and its ten colors) is read as one theme."""
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
    raw = [dict(t) if isinstance(t, dict) else t for t in raw]
    # A record from before the choices and the rules were each theme's
    # (29 Sep) carried them on the language: every theme takes a choice it
    # has none of its own for, and the language's rules go to the default
    # theme, ahead of its own. A language that made choices with no theme
    # yet gets a theme to hold them.
    carried = {k: lang.get(k) for k in ("font", "corners", "density", "motion", "fonts", "custom") if lang.get(k)}
    old_rules = lang.get("rules") if isinstance(lang.get("rules"), list) else []
    if (carried or old_rules) and not raw:
        raw = [{"name": "Default", "mode": "dark", "colors": []}]
    for i, t in enumerate(raw):
        if not isinstance(t, dict):
            continue
        for k, v in carried.items():
            if not t.get(k):
                t[k] = v
        if i == 0 and old_rules:
            t["rules"] = old_rules + (t.get("rules") if isinstance(t.get("rules"), list) else [])
    if len(raw) > THEMES_MAX:
        _bad(f"a language holds at most {THEMES_MAX} themes, and this has {len(raw)}")
        raw = raw[:THEMES_MAX]
    themes, names = [], set()
    for i, t in enumerate(raw):
        t = _clean_theme(t, i + 1)
        if t["name"].lower() in names:
            _bad(f"two themes are called {t['name']}")
            continue
        names.add(t["name"].lower())
        themes.append(t)
    # None is a language too (the operator, 29 Sep): a project designed by
    # its first session starts empty, and the session fills it in.
    out["themes"] = themes
    out["scope"] = _line(lang.get("scope"), NAME_MAX, "what the language governs")
    return out


def _clean_custom(raw, theme):
    """Which of the theme's rules says each choice that is custom:
    {choice: rule name}. 'Shape: as the design's own rules say' named no
    rule, and the rule that held the radii was ninety lines further down
    among thirty others (a report from another project, 29 Sep)."""
    out = {}
    if raw in (None, "", {}):
        return out
    if not isinstance(raw, dict):
        _bad(f"custom is an object, a choice to the name of its rule, not {str(raw)[:40]!r}")
        return out
    names = {r["name"] for r in theme["rules"]}
    for key, rule in raw.items():
        rule = str(rule or "").strip().lower()
        if key not in CHOICES:
            _bad(f"custom names {key!r}, which is not a choice: the choices are {', '.join(CHOICES)}")
        elif not rule:
            continue
        elif theme.get(key) != "custom":
            _bad(f"custom names a rule for {key}, which is {theme.get(key) or 'not chosen'} and not custom")
        elif rule not in names:
            _bad(f"custom names the rule {rule} for {key}, and {theme['name']} has no rule called that")
        else:
            out[key] = rule
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
        _bad(f"the rule {name} is at most {RULE_TEXT_MAX} characters, and this is {len(text)}")
        text = text[:RULE_TEXT_MAX]
    if not text:
        _bad(f"the rule {name} says nothing")
    # Each trigger once, in the order given: the briefing lists them, and a
    # word typed twice read "color, color" there.
    return {"name": name, "text": text,
            "words": list(dict.fromkeys(w.lower() for w in _bits(r.get("words")))),
            "paths": list(dict.fromkeys(p.replace("\\", "/").lstrip("/") for p in _bits(r.get("paths"))
                                        if ".." not in p.split("/")))}


def _clean_rules(raw, whose):
    """A list of rules as stored, each named once within `whose` (the
    language, a theme or a page): the operator asked for rules of a theme's
    own and a page's own (28 Sep), since the Nostromo scheme has needs no
    other theme shares."""
    if isinstance(raw, str):
        # The notes from before rules: one standing rule, kept whole.
        raw = [{"name": "design-notes", "text": raw}] if raw.strip() else []
    raw = raw if isinstance(raw, list) else []
    # A rule that is not an object is refused by what it is, not dropped: a
    # session that sent ["some rule"] found its rules gone with no word
    # said (B342).
    for r in raw:
        if not isinstance(r, dict):
            _bad(f"a rule of {whose} is an object with a name and a text, not {str(r)[:60]!r}")
    raw = [r for r in raw if isinstance(r, dict)]
    if len(raw) > RULES_MAX:
        _bad(f"{whose} holds at most {RULES_MAX} rules, and this has {len(raw)}")
        raw = raw[:RULES_MAX]
    rules, names = [], set()
    for i, r in enumerate(raw):
        r = _clean_rule(r, i)
        if r["name"] in names:
            _bad(f"{whose} has two rules called {r['name']}")
            continue
        names.add(r["name"])
        rules.append(r)
    return rules


def scoped_rules(rec):
    """Every rule the design carries, with the theme's or the page's rules
    named under it: `nostromo/hull` is the Nostromo theme's rule hull, and
    `bb design show nostromo/hull` reads it. [(name, rule, holder)]."""
    lang = rec["language"]
    themes = lang["themes"]
    # The default theme's rules are the design's, bare; the others' under
    # their theme's slug.
    out = [(r["name"], r, "") for r in (themes[0].get("rules") if themes else [])]
    for t in themes[1:]:
        out += [(f"{_slug(t['name'])}/{r['name']}", r, f"the {t['name']} theme") for r in t.get("rules") or []]
    for p in rec["pages"]:
        out += [(f"{page_key(p)}/{r['name']}", r, p["name"] or f"page {p['id']}")
                for r in p.get("rules") or []]
    return out


def saved(project):
    """The project's record when somebody saved one (the briefing's line),
    None when the design is still the default nobody touched. Asked of a
    store nobody configured, it says so: the answer None there read as
    "nothing designed", and a briefing said that of a designed project (B355)."""
    if FILE is None:
        raise RuntimeError("the design store is not configured")
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


# What a color is for, by the names a design gives it: the board and the
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


def _place(b, cols, rows, what):
    """A place on a grid, as given or refused: never moved to fit. A block
    sent 13 wide came back 12 wide and a place outside the frame came back
    inside it, with the save saying only that it had saved (two reports
    from other projects, 29 Sep)."""
    try:
        x, y, w, h = (int(b.get(k, 0)) for k in ("x", "y", "w", "h"))
    except (TypeError, ValueError, AttributeError):
        _bad(f"{what}: x, y, w and h are whole numbers")
        return {"x": 0, "y": 0, "w": 1, "h": 1}
    if w < 1 or h < 1:
        _bad(f"{what} is {w} wide and {h} high: a block is at least one cell each way")
    if x < 0:
        _bad(f"{what} has x {x}, which is left of the frame: x is 0 at the first column")
    elif x + w > cols:
        _bad(f"{what} runs from column {x + 1} to {x + w}, and the frame has {cols}")
    if y < 0:
        _bad(f"{what} has y {y}, which is above the page: y is 0 at the first row")
    elif y + h > rows:
        _bad(f"{what} runs from row {y + 1} to {y + h}, and the page has {rows}"
             + (f": give the page more rows (rows, up to {ROWS_MAX}) where it is longer than one screen"
                if rows < ROWS_MAX and 0 <= y and y + h <= ROWS_MAX else ""))
    w, h = max(1, w), max(1, h)
    x = min(max(0, x), cols - 1)
    y = min(max(0, y), rows - 1)
    return {"x": x, "y": y, "w": min(w, cols - x), "h": min(h, rows - y)}


def _clean_block(b, cols, rows, what, n):
    if not isinstance(b, dict):
        _bad(f"{what} is an object (kind, label, x, y, w, h), not {str(b)[:40]!r}")
        b = {}
    out = {"kind": _choice(b.get("kind"), KIND_KEYS, f"{what}'s kind", "content"),
           "label": _line(b.get("label"), NAME_MAX, f"{what}'s label"), **_place(b, cols, rows, what)}
    # The block this one lies inside (its parent), by the number the
    # messages count blocks by: a card in a list, a form in a card. The
    # board keeps a child within its parent; here it is held to that.
    inside = b.get("in")
    if inside not in (None, "", 0):
        try:
            k = int(inside)
        except (TypeError, ValueError):
            k = -1
        if not 1 <= k <= n:
            _bad(f"{what} is inside block {inside!r}, and the page has blocks 1 to {n}")
        elif what.endswith(f"block {k}"):
            _bad(f"{what} is inside itself")
        else:
            out["in"] = k
    return out


def _inside_parents(blocks, places, what, where):
    """A child lies within its parent, on the frame the page is on and on
    every other it has a layout for, and no chain of parents loops."""
    for i, b in enumerate(blocks):
        seen, k = {i}, b.get("in")
        while k:
            j = k - 1
            if j in seen:
                _bad(f"{what} {i + 1} is inside a chain of blocks that comes back to itself")
                b.pop("in", None)
                break
            seen.add(j)
            k = blocks[j].get("in")
    for i, (b, r) in enumerate(zip(blocks, places, strict=True)):
        k = b.get("in")
        if not k:
            continue
        # ...and is drawn over it: a later block draws over an earlier one,
        # so a child comes after its parent in the list (the operator, 29 Sep).
        if k - 1 > i and not where:
            _bad(f"{what} {i + 1} is inside block {k} but comes before it, so it would draw under it: "
                 "a block comes after the one it is inside")
        p = places[k - 1]
        if r["x"] < p["x"] or r["y"] < p["y"] or r["x"] + r["w"] > p["x"] + p["w"] or r["y"] + r["h"] > p["y"] + p["h"]:
            _bad(f"{what} {i + 1} is inside block {k} but reaches outside it{where}: a block inside "
                 "another stays within it")


PAGE_KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,23}")


def _page_key(value, called):
    """A page's short name for its rules' addresses, or "": a page is named
    for what it is for, in as many words as that takes, and a rule of
    'Now: who is listening, and is it safe to restart' reached a session
    under all of them (a report from another project, 29 Sep)."""
    key = str(value or "").strip().lower()
    if key and not PAGE_KEY.fullmatch(key):
        _bad(f"{called}'s key is {key!r}: a key is up to 24 lowercase letters, digits and dashes")
        return ""
    return key


def page_key(p):
    """What a page's rules are addressed under: its key where it has one,
    else its name as a slug, which is what it always was."""
    return p.get("key") or _slug(p["name"] or f"page-{p['id']}")


def page_rows(p):
    """How many rows a page has: its frame's, or more where it is longer
    than one screen."""
    return max(FRAMES[p["frame"]]["rows"], int(p.get("rows") or 0))


def _clean_page(p, pid):
    if not isinstance(p, dict):
        _bad(f"a page is an object, not {str(p)[:40]!r}")
        p = {}
    name = _line(p.get("name"), NAME_MAX, "a page's name")
    called = name or f"page {pid}"
    platform = _choice(p.get("platform"), PLATFORM_KEYS, f"{called}'s platform", "web")
    frames = _platform(platform)[2]
    frame = str(p.get("frame") or frames[0])
    if frame not in frames:
        _bad(f"{called} is on the {frame} frame, which {_platform(platform)[1].lower()} has not: "
             f"it has {', '.join(frames)}")
        frame = frames[0]
    g = FRAMES[frame]
    try:
        rows = int(p.get("rows") or g["rows"])
    except (TypeError, ValueError):
        rows = -1
    if not g["rows"] <= rows <= ROWS_MAX:
        _bad(f"{called} has {p.get('rows')!r} rows: a page on the {frame} frame has "
             f"{g['rows']} (one screen) to {ROWS_MAX}")
        # The most a page can have, for the rest of the look: held to the
        # frame's one screen, every block under it was reported as outside
        # the page, and one bad number came back as ten messages.
        rows = ROWS_MAX
    blocks = p.get("blocks") if isinstance(p.get("blocks"), list) else []
    if len(blocks) > MAX_BLOCKS:
        _bad(f"{called} holds at most {MAX_BLOCKS} blocks, and this has {len(blocks)}")
        blocks = blocks[:MAX_BLOCKS]
    notes = str(p.get("notes") or "").strip()
    if len(notes) > NOTES_MAX:
        _bad(f"{called}'s notes are at most {NOTES_MAX} characters, and these are {len(notes)}")
        notes = notes[:NOTES_MAX]
    clean = [_clean_block(b, g["cols"], rows, f"{called}, block {i + 1}", len(blocks)) for i, b in enumerate(blocks)]
    _inside_parents(clean, clean, f"{called}, block", "")
    return {"id": pid, "name": name,
            "platform": platform, "template": _choice(p.get("template"), TEMPLATE_KEYS, f"{called}'s template", "blank"),
            "key": _page_key(p.get("key"), called),
            "frame": frame, "rows": rows, "blocks": clean,
            "layouts": _clean_layouts(p.get("layouts"), frame, clean, called),
            "notes": notes, "rules": _clean_rules(p.get("rules"), f"the page {called}"),
            "at": int(time.time())}


def _clean_layouts(raw, frame, blocks, called):
    """Where the page's blocks sit on the other frames it has: per frame,
    one place per block, in the blocks' order (B348). A layout that is not
    that is refused and says why: one about another number of blocks was
    dropped whole, and the save said it had saved. One for a frame the
    page's platform has not is kept and not said: a page moved to Android
    and back to the web finds its desktop layout where it left it."""
    out = {}
    if raw in (None, ""):
        return out
    if not isinstance(raw, dict):
        _bad(f"{called}'s layouts are an object, a frame to its places, not {str(raw)[:40]!r}")
        return out
    for f, places in raw.items():
        if f not in FRAMES:
            _bad(f"{called} has a layout for {f!r}, which is not a frame: the frames are {', '.join(FRAMES)}")
            continue
        if f == frame:
            _bad(f"{called} has a layout for the {f} frame, which is the frame it is on: its blocks are that layout")
            continue
        n = len(blocks)
        if not isinstance(places, list) or len(places) != n:
            have = len(places) if isinstance(places, list) else 0
            _bad(f"{called}'s {f} layout has {have} place{'' if have == 1 else 's'} "
                 f"for {n} block{'' if n == 1 else 's'}: one place per block, in the blocks' order")
            continue
        out[f] = [_place(r, FRAMES[f]["cols"], ROWS_MAX, f"{called}, place {i + 1} of its {f} layout")
                  for i, r in enumerate(places)]
        _inside_parents(blocks, out[f], f"{called}, block", f" in its {f} layout")
    return out


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
            "rows_max": ROWS_MAX,
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


def _where(b, frame, rows=0):
    """A block's place in words: which part of the page, and how much.
    `rows` is how long the page is where that is more than its frame."""
    g = FRAMES[frame]
    cols, rows = g["cols"], max(g["rows"], rows)
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
    if not lang["font"]:
        return ""
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
        lines.append("Colors: none chosen yet. Choose them as tokens a stylesheet names once and every "
                     "surface reads, and put them into the design (bb design save) as a theme, named, dark or light.")
    elif len(themes) == 1:
        t = themes[0]
        lines.append(f"Colors ({t['name']}, {t['mode']}), as tokens a stylesheet names once and every "
                     "surface reads, never a hex in a component:")
        lines.extend(f"  {c['name']} {c['hex']}" + (f": {c['means']}" if c["means"] else "") for c in t["colors"])
    else:
        lines.append(f"Themes, each a set of the same tokens, which a stylesheet names once and every "
                     f"surface reads, never a hex in a component. The app starts on {themes[0]['name']}; "
                     "a theme picker, where the app has one, offers them by name:")
        for i, t in enumerate(themes):
            lines.append(f"  {t['name']} ({t['mode']}{', the default' if i == 0 else ''}):")
            lines.extend(f"    {c['name']} {c['hex']}" + (f": {c['means']}" if c["means"] else "") for c in t["colors"])
            if i:
                # Another theme's choices where they differ from the default's.
                lines.extend("    " + ln for ln in _choice_lines(t, platform, themes[0]))
                lines.extend(_rule_lines(t.get("rules") or [], f"{t['name']}'s own rules", _slug(t["name"]), "    "))
    # Each choice says what it means once somebody has made it, and only
    # that: the sentences this used to add by itself (monospace for data,
    # hairlines of 1px, AA contrast on a filled accent) were BuilderBot's
    # own design said of every project's, and one of them contradicted a
    # project's rules (a report from another project, 29 Sep). What a
    # design holds to beyond its choices is in its rules. The default
    # theme's, said as the design's.
    first = lead(lang)
    lines.extend(_choice_lines(first, platform))
    if _open_line(lang):
        lines.append(_open_line(lang))
    standing = [r for r in first["rules"] if not (r["words"] or r["paths"])]
    named = [r for r in first["rules"] if r["words"] or r["paths"]]
    for r in standing:
        lines.append(f"{r['name']}: {r['text']}")
    if named:
        lines.append("Design rules, named, not quoted: `bb design show NAME` reads one, and its text "
                     "arrives on the turn you edit a file or are asked about a word it names.")
        lines.extend(f"  {r['name']}: " + "; ".join(x for x in [", ".join(r["paths"]), ", ".join(r["words"])] if x)
                     for r in named)
    return "\n".join(lines)


def _choice_lines(theme, platform="", against=None):
    """A theme's four choices in words, each as it is made: the rule itself
    where a choice is custom (a session restyling a page reads this and has
    the figures in it). With `against`, only where this theme differs from
    that one, which is how another theme is said under the default."""
    lines = []
    for key, word, rows in SAID:
        if against is not None and theme.get(key) == against.get(key) and theme.get("fonts") == against.get("fonts") \
                and (theme.get("custom") or {}).get(key) == (against.get("custom") or {}).get(key):
            continue
        rule = _custom_rule(theme, key)
        fonts = f", set as {theme['fonts']}" if key == "font" and theme.get("fonts") else ""
        if rule:
            lines.append(f"{word}{fonts}, as the rule {rule['name']} says:")
            lines.extend("  " + ln for ln in rule["text"].splitlines() if ln.strip())
        elif theme.get(key):
            lines.append(f"{word}: " + (_font_means(theme, platform) if key == "font" else _means(rows, theme[key]))
                         + fonts + ".")
        elif fonts:
            lines.append(f"Type: set as {theme['fonts']}.")
    return lines


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
    """A color's name as a CSS token: letters, digits and dashes."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "color"


def _cap(text):
    """The first letter up and the rest as written: str.capitalize lowers
    the rest, and Material became material."""
    return text[:1].upper() + text[1:]


def _reach(places, frame):
    """How many rows a set of places comes to on a frame: the frame's own,
    or more where they run past one screen."""
    return max([FRAMES[frame]["rows"]] + [r["y"] + r["h"] for r in places])


def _frame_words(frame, rows):
    g = FRAMES[frame]
    return (f"{g['cols']} columns by {rows} rows"
            + (f": the frame shows {g['rows']} of them, and the page scrolls" if rows > g["rows"] else ""))


def page_text(page):
    """A page's layout as prose: each block, what it is for, and where, on
    the frame it is on and then on every other frame it has a layout for.
    Those were kept and never said: a phone layout a session saved reached
    neither this nor the file (two reports from other projects, 29 Sep)."""
    rows = page_rows(page)
    plat = _platform(page["platform"])
    name = page["name"] or "this page"

    # In the order they are drawn, first at the bottom: a block later in
    # the list draws over an earlier one where the two overlap, and one
    # inside another says so, which is how a card in a list is read.
    def said(blocks, frame, n):
        out = []
        for i, b in enumerate(blocks):
            what = f": {b['label']}" if b["label"] else ""
            par = blocks[b["in"] - 1] if b.get("in") else None
            # The parent by its number and the first clause of its label:
            # six children of one parent said its whole label six times (B384).
            first = re.split(r"[:;,.] ", par["label"], maxsplit=1)[0][:40] if par and par["label"] else ""
            inside = (f", inside block {b['in']} ({_label(KINDS, par['kind'])}"
                      f"{': ' + first if first else ''})") if par else ""
            out.append(f"  {i + 1}. {_label(KINDS, b['kind'])} ({_means(KINDS, b['kind'])}){what}, "
                       f"{_where(b, frame, n)}{inside}")
        return out
    lines = [f"Platform: {plat[4]}.",
             f"Layout of {name} on a {page['frame']} frame ({_frame_words(page['frame'], rows)}), from the "
             f"{_label([(t['key'], t['label'], '') for t in TEMPLATES], page['template'])} template, "
             "numbered in drawing order (a later block draws over an earlier one where they overlap):"]
    if not page["blocks"]:
        lines.append("  (no blocks placed yet)")
    lines += said(page["blocks"], page["frame"], rows)
    for frame, places in (page.get("layouts") or {}).items():
        if frame not in plat[2] or len(places) != len(page["blocks"]):
            continue
        n = _reach(places, frame)
        lines.append(f"The same blocks on a {frame} frame ({_frame_words(frame, n)}):")
        lines += said([{**b, **r} for b, r in zip(page["blocks"], places, strict=True)], frame, n)
    if page.get("notes"):
        lines.append("Notes:")
        lines.extend("  " + ln for ln in page["notes"].splitlines() if ln.strip())
    lines.extend(_rule_lines(page.get("rules") or [], "This page's own rules",
                             page_key(page), ""))
    return "\n".join(lines)


def prompt(lang, page=None):
    """What a session is asked to do, in full: the text the tab shows under
    a page and `bb design show` prints. The language alone when no page."""
    scope = lang.get("scope") or "the project's user interface"
    # Whose the file is, said outright: a session read "keep it in step",
    # found no file in the tree, and had to guess whether to make one (B344).
    keep = (f"{FILE_PATH} is yours to write and commit with the work, from what is saved here: "
            f"`bb design file > {FILE_PATH}`; the notebook never writes it into the tree by itself.")
    if page is None:
        head = (f"Apply this design language to {scope}. Put the tokens in one place the whole "
                f"stylesheet reads. {keep}")
        return head + "\n\n" + language_text(lang)
    target = page["name"] or "this page"
    head = (f"Build or restyle {target} to this layout, in the project's design language. "
            f"Keep what the blocks are for, at every width. {keep}")
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
    out += ["## Color", "",
            ("No theme chosen yet: the colors are tokens named once in the stylesheet, and the first "
             "session to choose them puts them here." if not themes else
             "Color comes only from these tokens, named once in the stylesheet"
             + (f". The app starts on {themes[0]['name']}; a theme picker, where the app has one, "
                "offers the themes by name, and every theme names the same tokens:" if len(themes) > 1 else ":"))]
    first = lead(lang)
    for i, t in enumerate(themes):
        if len(themes) > 1:
            out += ["", f"### {t['name']} ({t['mode']}{', the default' if i == 0 else ''})"]
        out += ["", "| token | value | for |", "|---|---|---|"]
        out += [f"| `--{_slug(c['name'])}` | `{c['hex']}` | {c['means']} |" for c in t["colors"]]
        if i:
            # Where this theme's choices differ from the default's, and its own rules.
            differs = _choice_lines(t, "", themes[0])
            if differs:
                out += ["", f"{t['name']} differs from the default in:", ""] + [f"- {ln}" for ln in differs]
            out += _file_rules(t.get("rules") or [], _slug(t["name"]), f"Rules of {t['name']}'s own", "####")
    for key, word, rows in SAID:
        rule = _custom_rule(first, key)
        fonts = f", set as {first['fonts']}" if key == "font" and first.get("fonts") else ""
        if rule:
            out += ["", f"## {word}", "", f"As the rule `{rule['name']}` says" + fonts + ":", "", rule["text"]]
        elif first.get(key):
            out += ["", f"## {word}", "", _cap(_font_means(first) if key == "font" else _means(rows, first[key]))
                    + fonts + "."]
        elif fonts:
            out += ["", "## Type", "", f"Set as {first['fonts']}."]
    if open_choices(lang):
        out += ["", "## Not chosen yet", "", _cap(", ".join(open_choices(lang)))
                + ": nobody has made " + ("this choice" if len(open_choices(lang)) == 1 else "these choices")
                + ". What the rules say of " + ("it" if len(open_choices(lang)) == 1 else "them") + " holds."]
    if first["rules"]:
        out += ["", "## Rules", "",
                "Each is one rule of the design, by name; a session is handed one on the turn it edits a "
                "file or is asked about a word the rule names, and `bb design show NAME` reads one."]
        for r in first["rules"]:
            on = "; ".join(x for x in [", ".join(r["paths"]), ", ".join(r["words"])] if x)
            out += ["", f"### {r['name']}", ""] + ([f"Applies to: {on}", ""] if on else []) + [r["text"]]
    if pages:
        out += ["", "## Pages", "",
                "Each page is a layout of labeled blocks on a frame, named for what it is for, "
                "on the platform it is built for."]
        for p in pages:
            out += ["", f"### {p['name'] or 'unnamed page'} ({_platform(p['platform'])[1]})", "", page_text(p)]
            out += _file_rules(p.get("rules") or [], page_key(p),
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
def problems(lang, pages):
    """Everything wrong with a record, in one pass, so a save is corrected
    once rather than one refusal at a time (B342): every validator notes
    what it meets and goes on (_bad)."""
    found = _collecting.found = []
    try:
        _clean_language(lang)
        if len(pages) > MAX_PAGES:
            _bad(f"a project holds at most {MAX_PAGES} pages, and this has {len(pages)}")
        keys = [str(p.get("key") or "").strip().lower() for p in pages if isinstance(p, dict)]
        for k in sorted({k for k in keys if k and keys.count(k) > 1}):
            _bad(f"two pages carry the key {k}")
        ids = [p.get("id") for p in pages if isinstance(p, dict) and isinstance(p.get("id"), int)]
        for pid in sorted({i for i in ids if ids.count(i) > 1}):
            _bad(f"two pages carry the id {pid}")
        for i, p in enumerate(pages[:MAX_PAGES]):
            _clean_page(p, i + 1)
    finally:
        _collecting.found = None
    return found


def schema_text():
    """bb design schema: the record's shape and every limit, so a session
    writes a record that saves the first time (B342)."""
    kinds = ", ".join(k for k, _, _ in KINDS)
    return "\n".join([
        "The record bb design save takes (and bb design json prints), as JSON:",
        "",
        "{",
        '  "language": {',
        f'    "themes": [ {{   at most {THEMES_MAX}; the first is the default, whose choices and rules are the design\'s',
        '      "name": "Night", "mode": "dark" | "light",',
        f'      "colors": [ {{ "name": "bg", "hex": "#1a1f26" or "#1a1f26cc", "means": "the page" }} ],   at most {COLORS_MAX}, a color name once per theme',
        f'      "font": {" | ".join(k for k, _, _ in FONTS)},   each of these four may be "" while nobody has chosen it, and custom where the theme\'s rules say it',
        f'      "corners": {" | ".join(k for k, _, _ in CORNERS)},',
        f'      "density": {" | ".join(k for k, _, _ in DENSITY)},',
        f'      "motion": {" | ".join(k for k, _, _ in MOTION)},',
        '      "custom": { "corners": "radii" },   optional: for a choice that is custom, the name of the rule of this theme that says it; its text is printed in the choice\'s place',
        '      "fonts": "Inter for text, JetBrains Mono for code",   the exact families, at most 200 characters',
        f'      "rules": [RULE]   at most {RULES_MAX}, each named once; the default theme\'s are addressed bare, another\'s as THEME/RULE',
        '    } ],',
        f'    "scope": "the web app in site/",   what the language governs, at most {NAME_MAX} characters',
        "  },",
        '  "pages": [ {',
        '    "id": 3,   a saved page keeps its id; leave it out for a new page; a saved page left out is removed',
        f'    "name": "the settings page",   what it is for, at most {NAME_MAX} characters',
        '    "key": "settings",   optional: a short name of its own, up to 24 lowercase letters, digits and dashes, once per design; its rules are addressed KEY/RULE and bb design show KEY prints it. Without one they are addressed by the whole name as a slug',
        f'    "platform": {" | ".join(PLATFORM_KEYS)},',
        f'    "frame": {" | ".join(FRAMES)},   one the platform allows: phone and landscape for a phone app. '
        + ", ".join(f"{k} is {v['cols']} columns by {v['rows']} rows" for k, v in FRAMES.items()),
        f'    "rows": 14,   optional: how long the page is where it is longer than one screen, the frame\'s rows to {ROWS_MAX}',
        f'    "template": {" | ".join(TEMPLATE_KEYS)},',
        f'    "blocks": [ {{ "kind": one of {kinds}, "label": "one line, at most {NAME_MAX} characters", "x": 0, "y": 0, "w": 4, "h": 2, "in": 1 }} ],   at most {MAX_BLOCKS}, each inside the frame\'s columns and the page\'s rows, in drawing order (a later block draws over an earlier one where they overlap); "in" is optional: the number of the block this one lies within and is drawn over, any block that is part of another (a card in a list, a cover in a card, a pill in a bar), which it then stays inside, and which comes before it in the list; a child can hold children of its own',
        f'    "layouts": {{ "phone": [ {{ "x": 0, "y": 0, "w": 6, "h": 2 }} ] }},   optional: where the same blocks sit on another frame, one place per block in the blocks\' order, a block inside another still within it; a layout is as long as its places reach, up to {ROWS_MAX} rows, and rows above is the length on the page\'s own frame; bb design show and the file say each',
        f'    "notes": "...",   at most {NOTES_MAX} characters',
        '    "rules": [RULE]',
        f'  }} ],   at most {MAX_PAGES} pages',
        "}",
        "",
        f'RULE is {{ "name": "dialogs", "text": "...", "words": ["dialog", "modal"], "paths": ["src/ui"] }}: an object, never a bare string; '
        f"the name a slug of at most 40 characters, the text at most {RULE_TEXT_MAX}, words and paths optional (a rule with neither stands in every briefing). "
        "A rule of a theme's or a page's own reaches a session as HOLDER/NAME.",
        "",
        "A save is refused whole, with every problem it found listed; nothing is dropped silently. "
        "A session's save goes through the project's dial, Claude may: Add to the design.",
    ])


def save(project, req, who=""):
    """The notebook's Save, and a session's bb design save: the whole record
    replaced by what was staged, each page keeping its id (a new one gets
    the next), with who saved it and when. (payload, status)."""
    raw = req.get("pages") if isinstance(req.get("pages"), list) else []
    bad = problems(req.get("language") or {}, raw)
    if bad:
        return {"error": "; ".join(bad), "problems": bad}, 400
    lang = _clean_language(req.get("language") or {})
    with statefile.locked(FILE):
        d = _load()
        rec = _record(d, project)
        nxt = rec["next"]
        pages = []
        for p in raw:
            pid = p.get("id") if isinstance(p, dict) else None
            if not isinstance(pid, int) or pid < 1:
                pid, nxt = nxt, nxt + 1
            pages.append(_clean_page(p, pid))
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
                nrules = sum(len(t.get("rules") or []) for t in lang["themes"]) + sum(len(p.get("rules") or []) for p in pages)
                r = pending.hold(project, "design", "save",
                                 {"language": req.get("language") or {}, "pages": req.get("pages") or []},
                                 summary=f"the design: {len(lang['themes'])} theme{'' if len(lang['themes']) == 1 else 's'} ({names}), "
                                         f"{nrules} rule{'' if nrules == 1 else 's'}, {len(pages)} page{'' if len(pages) == 1 else 's'}")
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
    if which == "schema":
        return schema_text(), ""
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
        first = rec["language"]["themes"][0] is theme
        lines = [f"{theme['name']} ({theme['mode']}), {'the default of' if first else 'one theme of'} {len(rec['language']['themes'])}:"]
        lines.extend(f"  {c['name']} {c['hex']}" + (f": {c['means']}" if c["means"] else "") for c in theme["colors"])
        lines.extend("  " + ln for ln in _choice_lines(theme))
        for r in theme.get("rules") or []:
            on = "; ".join(x for x in [", ".join(r["paths"]), ", ".join(r["words"])] if x)
            lines += ["", (r['name'] if first else f"{_slug(theme['name'])}/{r['name']}") + (f" (applies to: {on})" if on else ""), r["text"]]
        return "\n".join(lines), ""
    page = next((p for p in rec["pages"] if str(p["id"]) == which or p["name"].lower() == which.lower()
                 or (p.get("key") and p["key"] == which.lower())), None)
    if page is None:
        return "", f"no page, theme or rule here called {which!r}: bb design lists them"
    return prompt(rec["language"], page), ""


def listing(project):
    """bb design with no words: the language in one line and the pages."""
    rec = _record(_load(), project)
    lang = rec["language"]
    themes = ", ".join(f"{t['name']} ({t['mode']})" for t in lang["themes"]) or "no theme yet"
    first = lead(lang)
    # Each with its noun: "custom corners, custom, quiet motion" left the
    # reader to work out what the second custom was.
    made = [x for x in ((_label(FONTS, first["font"]).lower() + (" type" if first["font"] == "custom" else ""))
                        if first["font"] else "",
                        f"{first['corners']} corners" if first["corners"] else "",
                        f"{first['density']} spacing" if first["density"] else "",
                        f"{first['motion']} motion" if first["motion"] else "") if x]
    left = open_choices(lang)
    lines = [f"{project}'s design language: {themes}"
             + (f"; {', '.join(made)}" if made else "")
             + (f"; {', '.join(left)} not chosen yet" if left else "")
             + (f"; it governs {lang['scope']}" if lang.get("scope") else "")]
    if first["rules"]:
        lines.append(f"  {len(first['rules'])} design rule{'' if len(first['rules']) == 1 else 's'}: "
                     + ", ".join(r["name"] for r in first["rules"][:12]) + (", ..." if len(first["rules"]) > 12 else ""))
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
    if not rec["at"]:
        lines.insert(1, "  nothing saved here yet: build as you would, and put what you arrive at into it with bb design save")
    lines.append(f"bb design show [ID|NAME] prints one in full; bb design file prints {FILE_PATH}; "
                 "bb design json prints the record, bb design save FILE writes one back, and bb design schema says its shape")
    return "\n".join(lines)


# Every preset passes its own validation, so a template or a scheme that
# drifts from the vocabulary fails at import rather than at the first save.
for _k, _l, _c in SCHEMES:
    _clean_language({"scheme": _k, "colors": _c})
for _t in TEMPLATES:
    _clean_page({"frame": _t["frame"], "template": _t["key"],
                 "blocks": [dict(zip(("kind", "label", "x", "y", "w", "h"), b, strict=True)) for b in _t["blocks"]]}, 1)
