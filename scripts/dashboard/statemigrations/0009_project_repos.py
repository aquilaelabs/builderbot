"""State 8 to 9: a project may hold several repositories (R136).

  * nothing is rewritten here: project-repos.json starts absent, which is
    every project one repository, as before, and the registry's new `repos`
    state is only ever written by a merge.
  * the number is what moves: once a project of repositories exists, other
    projects' reads name its key, which an older build reads as a folder
    that is not there, and a repository in it reads its own settings rather
    than its project's; so an older build refuses to start on this /config
    rather than running sessions with the wrong grants.

Never edited once shipped (stateversion.py).
"""


def run(ctx):
    return
