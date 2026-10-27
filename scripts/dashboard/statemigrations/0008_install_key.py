"""State 7 to 8: what the install keeps sealed under its install key (R135).

  * nothing is rewritten here: the settings' secrets (the tunnel's and
    Cloudflare's tokens) are sealed by the dashboard at its start
    (settings.seal_all), and the sign-in cookies' key is made from the
    install key and no longer kept (dashboard-secret goes), all under the
    install key, which is never in /config and so is not this migration's
    to read. A start with no key keeps everything as it was.
  * the number is what moves: a sealed setting is one an older build reads
    as a token that does not work, so an older build refuses to start on
    this /config rather than failing the tunnel quietly.

Never edited once shipped (stateversion.py).
"""


def run(ctx):
    return
