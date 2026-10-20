# Changelog

## Unreleased

### Added

- bb nodes shows the agent each node runs and whether it needs Update agent, and bb nodes show NAME gives one node in full (6404f8b)
- Tool packs: an administrator adds a toolchain from a git repository with a bbtool.json, pinned to the commit they looked at; it installs like any toolchain, gives sessions bb tool commands, and each project's Settings → Toolchains says which toolchains and packs its sessions may use (f6c5013)
- A tool pack can be made right on the Toolchains page, with no repository of its own: paste its bbtool.json or upload a zip or tar of its files. The controller keeps it as a version you approve, Edit changes it in place, and the nodes install it from the controller (37c6332)
- The Windows companion and the VS Code extension say which release they are on every call, and each says plainly when its controller is too old or too new for it, rather than failing partway

### Changed

- Installing a toolchain under an agreement (Google's Android SDK terms, NVIDIA's CUDA license) now asks you to accept it, named and linked, before anything downloads, and records who accepted (d06ec8e)
- Speech (bb tool sound say) uses the ljspeech voice, trained on a public-domain dataset, instead of lessac, whose dataset is licensed for research; install the audio toolchain again to switch (d06ec8e)

### Fixed

- A session knows each project by the name the dashboard shows as well as its folder, and bb -p takes either (6404f8b)
- The Android app's update offer comes from the project linked to BuilderBot's repository, whatever its folder is called (6404f8b)
- A long bb command from a session on a node arrives whole; one past 1024 words is refused by name instead of being cut short (6404f8b)
- A page's screenshot taken with no file named goes to the project's dist/shot and is listed and swept with the other captures (6404f8b)
- bb devapp probe finds a dev instance's port from what its containers publish when the compose file sets the port from the environment (6404f8b)
- A session's git config user.name and user.email name the author from your Profile, the same one its commits carry (6404f8b)
- A session's own isolated agents no longer hold its project's sync behind: Claude Code's .claude/worktrees is left out of sync, so bb git push is not refused while they exist (B68) (abbd90d)
