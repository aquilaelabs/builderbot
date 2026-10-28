"""State 14 to 15: every account a Unix user of its own on every node, and
the coding agents' sign-ins sealed there (R125 step 11 and R126 step 6; the
operator, 26 Oct).

  * nothing is rewritten here: the two switches on a node's Sessions
    section, dev features in 0.8.x and off on every node by default, are
    gone, and the controller answers on for every node that runs sessions,
    whatever key an older build left in the node's config. The node moves
    each account's home to its own user once nothing of that account runs
    the old way (the sessions started before end on their own), and seals
    each sign-in the next time a login writes it or the person opens a
    terminal there;
  * the number moves because an older build reads the absent keys as off
    and would run every account as the shared session account again on a
    node whose homes have moved, with the sealed sign-ins unopened; it
    refuses to start on this /config instead.

Never edited once shipped (stateversion.py).
"""


def run(ctx):
    return
