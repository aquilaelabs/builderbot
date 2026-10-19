# Changelog

## Unreleased

### Added

- bb nodes shows the agent each node runs and whether it needs Update agent, and bb nodes show NAME gives one node in full (6404f8b)
- Tool packs: an administrator adds a toolchain from a git repository with a bbtool.json, pinned to the commit they looked at; it installs like any toolchain, gives sessions bb tool commands, and each project's Settings → Toolchains says which toolchains and packs its sessions may use (f6c5013)

### Fixed

- A session knows each project by the name the dashboard shows as well as its folder, and bb -p takes either (6404f8b)
- The Android app's update offer comes from the project linked to BuilderBot's repository, whatever its folder is called (6404f8b)
- A long bb command from a session on a node arrives whole; one past 1024 words is refused by name instead of being cut short (6404f8b)
- A page's screenshot taken with no file named goes to the project's dist/shot and is listed and swept with the other captures (6404f8b)
- bb devapp probe finds a dev instance's port from what its containers publish when the compose file sets the port from the environment (6404f8b)
- A session's git config user.name and user.email name the author from your Profile, the same one its commits carry (6404f8b)
