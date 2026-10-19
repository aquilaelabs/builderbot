# BuilderBot companion for Windows

A folder on your Windows machine kept in step with a BuilderBot project,
both ways, the way a node's copy of a project is kept (R270). Open it in a
tool that only runs on Windows (GameMaker, Unity, Unreal, Visual Studio)
while Claude works on the same project from its session on a node: a change
Claude makes lands in your folder within seconds, and one you save goes up
to the project.

Claude never runs on your machine. The app signs in as you and does only
what your account may: a project comes down when its settings give you
editor access, and goes up when that access is read and write.

## Signing in

Start the app and give it the controller's address, your account and your
password. The password is used once, to give this machine a token of its
own, and is kept nowhere; the token is kept in Windows' credential store.
The machine is then listed under your devices on the Profile page, where
Disconnect ends its token.

## Picking a project

Add a project and choose the folder it is kept in. The first copy comes
down whole; after that a change on either side reaches the other in a few
seconds. What the app does not bring:

- `.git`: the folder is a working copy; the project's history stays on the
  controller, where its sessions commit.
- Symbolic links, which Windows makes only with a privilege it seldom grants.
- A file whose name Windows cannot hold (`CON`, a name ending in a dot,
  `a:b`, or two names that differ only by case): left out, and the window
  says how many.

When a change of yours and one on the controller meet, the one that
arrived first is kept and the other is saved beside it as
`NAME.conflict-WHO-TIME.EXT`. The window's Conflicts lists them.

## From a command line

    python -m bbcompanion signin https://builderbot.example YOU
    python -m bbcompanion add MyGame C:\Games\MyGame
    python -m bbcompanion run

## Building it

    tools/companion-build.py --version X.Y.Z        # one .pyz, for any machine with Python 3.9+

The `.exe` is built by the `companion app` workflow on a published release
(or by hand for one), and attached to the release. It uses the node agent's
own sync (`scripts/agent/builderbot_agent/wssync.py`), not a copy of it.
