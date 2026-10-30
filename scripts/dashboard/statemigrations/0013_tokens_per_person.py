"""State 12 to 13: every git action is a person's, with their own token
(R159, the operator, 27 Oct).

  * nothing is rewritten here: a project's gitcreds file, one `account:UID:ID`
    line since 0.8.0 naming the token its owner's store keeps, is read as the
    first of the people who gave it one; from here each person who pushes or
    pulls on the project gives their own, a line each, and a token is used
    only while its person is signed in. The project's settings say who has
    given one and ask the rest for theirs;
  * the number moves because a file of several lines is a shape an older
    build reads as one token, the first line's, and because /config/logins.json,
    which says who is signed in now, is a file an older build never writes,
    so a start on it would push with nobody's token.

Never edited once shipped (stateversion.py).
"""


def run(ctx):
    return
