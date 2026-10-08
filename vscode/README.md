# BuilderBot for VS Code

Open a BuilderBot project in VS Code without mounting a share, see what a
Claude session changes as it saves, and work in that session's terminal from
a VS Code panel. You use it as your own BuilderBot account. The controller
decides what the account may do on every request, so the extension can do
nothing the dashboard would not let you do.

## Before you start

A project opens in an editor only when its settings allow it. In the
project's settings, under **File access**:

1. Tick **Open them in an editor with BuilderBot for VS Code**.
2. Give each person **Read** or **Read and write**.

Your roles must also include **File access** on that project. A role that
gives only Read keeps you read-only whatever the list says. Only BuilderBot's
owner, or a role that grants ftp, can change these settings.

## Install

Download `builderbot-vscode-VERSION.vsix` from the project's Artifacts tab,
or from `dist/` in the BuilderBot repository. Then, in VS Code, open the
Extensions view, open the **…** menu and choose **Install from VSIX…**.

## Use

- **BuilderBot: Sign In**: enter the controller's address (as you open the
  dashboard), your BuilderBot name and your password. The password is not
  kept. The extension keeps the same signed cookie a browser gets, in VS
  Code's secret storage. Changing your password signs it out.
- **BuilderBot: Open Project**: pick a project. It opens as a folder named
  `builderbot:/PROJECT`. A read-only project opens read-only.
- **BuilderBot: Open Claude Session**: the project's Claude session in a
  terminal panel. This is the same terminal the dashboard opens, and the
  same rules decide whether you may type into it.
- **BuilderBot: Search Project Files**: search the project's files on the
  controller, then open a match.
- **BuilderBot: Sign Out**.

When the session saves a file you have open, the editor reloads it. If you
save over a file that changed after you opened it, the save is refused, and
VS Code offers to compare the two versions so that neither side is lost.

`.git` is never served, because its config can hold a token. Git stays in
the session or in the notebook's Git view.

## Limits

- Language features run on your machine against files fetched one at a
  time, so they work less well on large projects.
- The Source Control view does not show the project.
- A file over 20 MB does not open.
- Changes are not followed in a project of more than 50,000 files.
