"""A request body's fields, read one way (R77).

Every handler read its fields through the server's field(), and when a
handler's logic moved into its module (a gate plus one call, R77) the
module needed the same reader. One copy here rather than one handed to
each: no imports from the rest of the dashboard, so a module bb loads by
path can use it too.
"""


def field(req, key, default=""):
    """One string field out of a request body, or the default.

    JSON carries types, and `(req.get(k) or "").strip()` only defends against
    the field being absent. A number, a list or a dict reaches `.strip()` and
    the handler dies on an AttributeError, which is a 500 on a surface that
    runs commands, and a class of bug worth removing at the boundary rather
    than one field at a time.
    """
    v = req.get(key)
    return v if isinstance(v, str) else default


def field_list(req, key):
    """A list of strings out of a request body. Anything else is nothing."""
    v = req.get(key)
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []
