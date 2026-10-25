# The dashboard's API

Written from `scripts/dashboard/server.py` by `tools/api-doc.py`; `bb lint` holds this page equal to it.
Every request carries the account's credential (a session's token, or the person's cookie or
basic auth); who may call what is decided in the handler, and the last column names the
permission a handler refuses on (`refused: NAME`), or that it refuses a locked project
(`readonly`) or a name that is not a project the account sees (`not_project`). A `prefix`
route takes every path it prefixes, in the order listed; an `exact` one takes its path alone.
The companion app's own contract is `android/api-surface.json`.

| Method | Path | Match | Handler | What it does | Refuses on |
|---|---|---|---|---|---|
| GET | `/api/revs` | prefix | `_get_revs` | GET /api/revs. |  |
| GET | `/api/live` | exact | `_get_live` | GET /api/live: who has a Claude session on each project this account sees, which of them are working and which asking, the maps the status payload also carries (projsessions.maps), alone and cheap. |  |
| GET | `/api/trace` | prefix | `_get_trace` | GET /api/trace?since=T: what this server was asked since T, grouped by endpoint (R75 step 4). |  |
| GET | `/api/status` | prefix | `_get_status` | GET /api/status. |  |
| GET | `/api/reset` | exact | `_get_reset` | GET /api/reset: how a Reset that un-enrolls its nodes first is getting on: each node, done or why not, and the error that stopped it. | refused: controller-read |
| GET | `/api/findings` | prefix | `_get_findings` | GET /api/findings: findings.view, scoped to the projects this account sees, and for a session to its own. |  |
| GET | `/api/profile` | prefix | `_profile` | The signed-in account's own settings (the Profile page): read on GET, saved on POST, by profiletab.py. |  |
| GET | `/api/transcripts` | prefix | `_get_transcripts` | GET /api/transcripts?project=NAME: the signed-in account's own conversations with Claude on that project, newest first (transcripts.mine); with audit=DAYS, what they did against the house rules that can be counted instea |  |
| GET | `/api/snapshots` | prefix | `_get_snapshots` | GET /api/snapshots?project=NAME: the days kept of the project's tree (snapshots.py), newest first, and how many it keeps. | refused: settings |
| GET | `/api/transcript` | prefix | `_get_transcript` | GET /api/transcript?project=NAME&id=SESSION: one of the signed-in account's own conversations with Claude on that project as a text file, every command and answer in it (transcripts.render); as JSON with as=json, which i |  |
| GET | `/api/git` | prefix | `_get_git` | GET /api/git: the notebook's Git view (gitview.view), for a project this account may see. |  |
| GET | `/api/project-sessions` | prefix | `_get_project_sessions` | GET /api/project-sessions?project=NAME: every account's sessions on the project, for its settings dialog. | refused: settings |
| GET | `/api/changelog` | prefix | `_get_changelog` | GET /api/changelog: changelog.reading, for a project this account sees. |  |
| GET | `/api/version` | prefix | `_get_version` | GET /api/version. |  |
| GET | `/api/artifacts` | prefix | `_get_artifacts` | GET /api/artifacts: artifacts.tab_view, for a project this account sees. |  |
| GET | `/api/artifact?` | prefix | `_get_artifact` | GET /api/artifact: one file of a project's, as a download (artifacts.download). |  |
| GET | `/api/signing-backup?` | prefix | `_get_signing_backup` | GET /api/signing-backup: a project's keystore for an administrator's own copy (signing.backup), which marks it backed up. |  |
| GET | `/api/node-busy` | prefix | `_get_node_busy` | GET /api/node-busy: whether one of a project's nodes is quiet enough to time anything on (busy.report, R108). |  |
| GET | `/api/meta` | prefix | `_get_meta` | GET /api/meta. |  |
| GET | `/api/welcome` | prefix | `_get_welcome` | GET /api/welcome: BuilderBot's own changelog for the welcome panel (changelog.welcome), and where this account last looked. |  |
| GET | `/api/source?` | prefix | `_get_source` | GET /api/source: the code base as a zip, from the Artifacts view (artifacts.source_download). |  |
| GET | `/logs/download` | prefix | `_get_logs_download` | GET /logs/download: the container's own log, every project's traffic in it, or the diagnostics whole (logs.download). | refused: controller-read, refused: debug |
| GET | `/api/phone/wait` | prefix | `_get_phone_wait` | GET /api/phone/wait?since=T: the companion app's live connection (R125). |  |
| GET | `/api/phone` | prefix | `_get_phone` | GET /api/phone. |  |
| GET | `/api/toolchains` | prefix | `_get_toolchains` | GET /api/toolchains. |  |
| GET | `/api/agents` | prefix | `_get_agents` | GET /api/agents?node=ID: the coding agents on one node (R95, the Agents page): each agent's row, the version against the latest and any job of its own, and the asking account's own plugins and MCP servers there. |  |
| GET | `/api/emulator` | prefix | `_get_emulator` | GET /api/emulator?node=ID: that node's system images, what could be added, and the image job there. |  |
| GET | `/api/roles` | prefix | `_get_roles` | GET /api/roles: the Roles page (R152): the areas, every role, and each account with its Global roles, the roles it holds on each project and the projects it is on. |  |
| GET | `/api/users` | prefix | `_get_users` | GET /api/users. |  |
| GET | `/api/nginx` | prefix | `_get_nginx` | The nginx page (nginxproxy.view): every node's nginx, for an account that may read the Nodes page; never a session's. |  |
| GET | `/api/storage` | prefix | `_get_storage` | The Storage page (storage.view, R169): every node this account holds the Storage area on, what its disks hold, by project where the account sees the project and as one line otherwise. |  |
| GET | `/api/v1/nodes` | prefix | `_get_nodes` | GET /api/v1/nodes: the Nodes page's read (nodes.tab_view), scoped to this account. |  |
| GET | `/api/v1/jobs` | prefix | `_get_jobs` | GET /api/v1/jobs: nodes.jobs_view, narrowed to the projects this account may see unless it administers. |  |
| GET | `/api/home` | prefix | `_get_home` | GET /api/home: home.read, the overview's numbers (R218 step 5). |  |
| GET | `/api/apps` | prefix | `_get_apps` | GET /api/apps: the apps this controller offers and holds (apps.view), for the Apps page and the Settings section. |  |
| GET | `/api/notices` | prefix | `_get_notices` | GET /api/notices: notices.listing, this account's own (R218 step 6). |  |
| GET | `/api/help` | prefix | `_get_help` | GET /api/help: the docs on the Help page (helpdocs.py, R258): the listing, ?doc=NAME one of them, ?q=WORDS a search across them. |  |
| GET | `/api/docker` | prefix | `_get_docker` | GET /api/docker: the manager's whole page, containers.manager_view, for the node this account may read. |  |
| GET | `/api/containers` | prefix | `_get_containers` | GET /api/containers. | refused: containers-read |
| GET | `/api/vms` | exact | `_get_vms` | GET /api/vms (R91): the VMs of the projects this account may read them on (a session: its own), the OS catalog and the VM hosts. |  |
| GET | `/api/project-job` | prefix | `_get_project_job` | GET /api/project-job. | refused: create |
| GET | `/api/trash` | prefix | `_get_trash` | GET /api/trash. | refused: trash |
| GET | `/api/claude-now` | prefix | `_get_claude_now` | GET /api/claude-now. |  |
| GET | `/api/roadmap` | prefix | `_get_todo` | GET /api/roadmap. |  |
| GET | `/api/rules` | prefix | `_get_rules` | GET /api/rules. |  |
| GET | `/api/global-rules` | prefix | `_get_global_rules` | GET /api/global-rules. |  |
| GET | `/api/preamble` | prefix | `_get_preamble` | GET /api/preamble. |  |
| GET | `/api/brief` | prefix | `_get_brief` | GET /api/brief: brief.view, the brief waiting in a project's tree and the one kept after it left, for a project this account sees. |  |
| GET | `/api/design` | prefix | `_get_design` | GET /api/design: design.view, a project's design language, its pages and the vocabulary they are drawn from, for a project this account sees; a session reads it too, through bb design. |  |
| GET | `/api/wiki-export` | prefix | `_get_wiki_export` | GET /api/wiki-export: the wiki as a zip of its Markdown pages, whether or not the project has a remote. |  |
| GET | `/api/wiki` | prefix | `_get_wiki` | GET /api/wiki: the project's wiki (wiki.view), or one page of it with ?page=, for an account that sees the project; a session reads it too, through bb wiki. |  |
| GET | `/api/ci-runs` | prefix | `_get_ci_runs` | GET /api/ci-runs: a project's runs on GitHub's own runners, or with ?run=N (0 the newest finished) that run's jobs and the end of each failed job's log (cilogs), for an account that sees the project; a session reads it t |  |
| GET | `/api/ci-watch` | prefix | `_get_ci_watch` | GET /api/ci-watch: what the last look at a project's CI found (ciwatch.read), for an account that sees the project. |  |
| GET | `/api/codebase` | prefix | `_get_codebase` | GET /api/codebase. |  |
| GET | `/api/pending` | prefix | `_get_pending` | GET /api/pending. |  |
| GET | `/api/memory` | prefix | `_get_memory` | GET /api/memory. |  |
| GET | `/api/tests` | prefix | `_get_tests` | GET /api/tests. |  |
| GET | `/api/bugs` | prefix | `_get_bugs` | GET /api/bugs. |  |
| GET | `/api/pubkeys` | prefix | `_get_pubkeys` | GET /api/pubkeys. | refused: create |
| POST | `/api/v1/nodes` | prefix | `_nodes` | The Nodes page's verbs. |  |
| POST | `/api/v1/jobs` | prefix | `_jobs` | The Jobs page's one verb, and where `bb run`, `bb build`, `bb test` and `bb emu` land from the controller (nodes.run_job). |  |
| POST | `/api/v1/bb` | exact | `_bb_relay` | A bb verb from a session on a NODE, run here (roadmap #24). | refused: bb |
| POST | `/api/v1/claude-login` | exact | `_claude_login` | A node saying what this account is signed in to Claude, or another coding agent, AS there (R47), or that it is not: never the login itself, which stays on the machine that made it (claudegrant.py says why). |  |
| POST | `/api/v1/hook` | exact | `_hook` | What a session's hooks have to say, from a NODE (roadmap #24): hooks.py says what each kind means. |  |
| POST | `/api/v1/tty-grant` | exact | `_tty_grant` | Whose terminal a node's bb-tty is about to start, answered here (B166). |  |
| POST | `/api/lock` | prefix | `_lock` | Lock or unlock a project (R119), never a session's. |  |
| POST | `/api/archive` | prefix | `_archive` | Archive or unarchive a project (R119): out of sight, and nothing else; the project's owner or an administrator, never a session. |  |
| POST | `/api/repos` | prefix | `_repos` | Projects and their repositories (R138): create (a project with a name and nothing in it), rename, move (a repository into another project) and delete (a project with no repository left). | refused: create |
| POST | `/api/project-pin` | prefix | `_project_pin` | Pin or unpin a project: whether the sidebar card shows it (projects.pin). |  |
| POST | `/api/project-group` | prefix | `_project_group` | Put a project in one of this account's groups, take it out, or rename a group (projects.set_group, rename_group), or delete one (delete_group): a label for the Projects page, nothing more. |  |
| POST | `/api/apps` | prefix | `_apps` | POST /api/apps: look at the release again now (apps.check_now). | refused: controller |
| POST | `/api/pc` | prefix | `_pc` | POST /api/pc: a session's word with a PC lent to its project (pcwork.py, bb pc): lent (which PCs lend which verbs), run (ask one, under the project's Agents may: Use a lent PC) and result (an ask's answer, held a while). |  |
| POST | `/api/project-color` | prefix | `_project_color` | Give a project one of the colors for this account alone, or none (projects.set_mark): worn by its card, its tabs and its bar. |  |
| POST | `/api/project-auth` | prefix | `_project_auth` | What credential this project's remote uses, and what else it could: projects.auth_answer. | refused: rename |
| POST | `/api/project-ftp` | exact | `_project_ftp` | A project's file access over FTP (ftp.py, R151): what it is, for whoever sees the project, and a change, for an account with the ftp grant (named only: the owner, until a role names it). | refused: ftp |
| POST | `/api/container` | prefix | `_container` | A container from a compose file written here, with no project: containers.tab_verb. | refused: docker-write |
| POST | `/api/vms` | exact | `_vms` | POST /api/vms (R91): new, start, stop, restart, remove, snapshot, revert, snapshot-rm. | refused: vms-write, refused: node |
| POST | `/api/dockerctl` | prefix | `_docker_ctl` | Start, stop, restart or read the log of ONE container on a node. | refused: docker-write |
| POST | `/api/rename` | prefix | `_rename` | Rename a project: projects.rename. | refused: rename |
| POST | `/api/trash-restore` | prefix | `_trash_restore` | A repository out of the bin, back into the project it was in, or into the one named (`project`) where that one is gone or another is wanted (R138): it is never put back into none. | refused: trash |
| POST | `/api/trash-purge` | prefix | `_trash_purge` | Delete a trashed project for good. | refused: trash |
| POST | `/api/trash` | prefix | `_trash` | Move a project out of the workspace: projects.trash, once project_busy says nothing holds it (the same guards as renaming). | refused: trash |
| POST | `/api/session` | prefix | `_session` | Kill a session. |  |
| POST | `/api/send` | prefix | `_send` | Type a macro's command lines into a shell session of the caller's and press Enter: macros.send. |  |
| POST | `/api/say` | prefix | `_say` | Type a message into a CLAUDE session and press Enter. |  |
| POST | `/api/chat` | prefix | `_chat` | Read a conversation, send into one, or mark one seen: chat.converse. |  |
| POST | `/api/layout` | prefix | `_layout` | Store this account's open tabs: layout.save_tabs. |  |
| POST | `/api/bell` | exact | `_bell` | Put a bell note away for this account, bring every one back (bellseen.py), or resume a session an outage held (R251). |  |
| POST | `/api/notices` | exact | `_notices` | Keep, delete or clear what the page said to this account: notices.act. |  |
| POST | `/api/nginx` | exact | `_nginx` | Deploy, save, certificate, remove, check and update on one node's nginx (nginxproxy.py): writing a compose file and building it on a node, so docker-write like a written container, and never a session's. | refused: docker-write |
| POST | `/api/images` | exact | `_images` | Check for updates on the Containers page (imagecheck.py, R195): every container's registry images on one node, or all, asked now. | refused: docker-write |
| POST | `/api/storage` | exact | `_storage` | Measure now on the Storage page: a node's disks walked at once (nodes.node_storage_measure). |  |
| POST | `/api/pin` | prefix | `_pin` | Pin or unpin a command: macros.pin. | refused: command-pin |
| POST | `/api/reset` | exact | `_reset` | POST /api/reset: start over at onboarding (settings.reset), and the dashboard re-executes itself so the next page is Create the owner. | refused: controller |
| POST | `/api/create` | prefix | `_create` | New project: a fresh local repo, a clone or a link, and what the dialog chose besides (projects.create_from_dialog). | refused: create |
| POST | `/api/profile` | prefix | `_profile` | The signed-in account's own settings (the Profile page): read on GET, saved on POST, by profiletab.py. |  |
| POST | `/api/git` | prefix | `_git_act` | The Git view's actions (roadmap R36 step 2): fixed git commands on the project's tree on the controller, under the acting account's author and the project's own credentials (gitview.verb). |  |
| POST | `/api/project-sessions` | prefix | `_project_sessions` | POST /api/project-sessions {project, action: "end", session, node}: an administrator ending one of them (projsessions.py). | refused: settings |
| POST | `/api/unlink` | prefix | `_unlink` | Take the remote off a project, with the credential and the push grant that came with it. | refused: create |
| POST | `/api/link` | prefix | `_link` | Link an existing local repo to an empty repo on a host. | refused: create |
| POST | `/api/project-job` | prefix | `_project_job` | Stop the running project job, or clear the last one's outcome. | refused: create |
| POST | `/api/roadmap` | prefix | `_roadmap` | Add, send, edit or drop one item on a project's list: roadmap.verb says what each action means. | refused: settings |
| POST | `/api/roles` | prefix | `_roles` | POST /api/roles: assign (an account's Everywhere roles and its roles on each project, as far as the asker may, R152 and R155), set (make or change a role: its scope, its areas and note) or remove one; owner and admin are | refused: admin |
| POST | `/api/users` | prefix | `_users` | The Users page's verbs. | refused: admin |
| POST | `/api/toolchains` | prefix | `_toolchains` | Queue installs or removals of the toolchains the Tools card offers: an administrator's, and toolchains.verb says what each action does with which names. |  |
| POST | `/api/agents` | exact | `_agents` | POST /api/agents: install (or update), remove or check one coding agent on one node (agentcode.verb), the one way an agent is managed (R95, the operator 22 Oct): whoever may install toolchains there. |  |
| POST | `/api/toolpacks` | exact | `_toolpacks` | POST /api/toolpacks: look at a tool pack by its repository's address, or at one made here from a pasted manifest or an uploaded archive (/api/upload-archive's id); add it as it was shown; read a pack made here's manifest | refused: admin |
| POST | `/api/emulator` | prefix | `_emulator` | Add system images to a node, or remove one: a job there, against its toolchain store. | refused: toolchains-write |
| POST | `/api/logs` | prefix | `_logs` | The log policy, and the two things that can be done to the pile: logs.verb. | refused: controller |
| POST | `/api/idle` | prefix | `_idle` | The idle rule for every agent's sessions (idle.py): minutes, 0 for never. | refused: controller |
| POST | `/api/paths` | prefix | `_paths` | Where the controller keeps one kind of what grows (paths.py), and what is there moved across. | refused: controller |
| POST | `/api/snapshots` | prefix | `_snapshots` | POST /api/snapshots: take one now, or restore the whole tree as of a day or one file of it (snapshots.restore, which snapshots the tree first so it can be undone). | refused: settings |
| POST | `/api/transcripts` | exact | `_transcripts` | POST /api/transcripts {project, id, action}: one of the signed-in person's own conversations deleted, or made visible to every session on the project (share) or private again (unshare). |  |
| POST | `/api/settings` | prefix | `_settings_post` | POST /api/settings. | refused: controller, refused: debug |
| POST | `/api/rules` | prefix | `_rules` | The operator's house rules for one project: the whole list, saved (rules.verb). | refused: rules |
| POST | `/api/global-rules` | prefix | `_global_rules` | The rules that apply to EVERY project (R63): rules.global_verb. | refused: controller |
| POST | `/api/pending` | prefix | `_pending` | Approve or deny what a session has waiting (roadmap #27): pending.verb. | refused: pending |
| POST | `/api/memory` | prefix | `_memory` | Edit, create or delete one of this project's memories, rewrite their index, or read the history: memory.verb, behind the gates here. |  |
| POST | `/api/prefs` | prefix | `_prefs_post` | POST /api/prefs: a project's settings dialog, saved by prefs.dialog_save behind the gates here. | refused: node, refused: nodes-write, refused: debug, refused: docker-write, refused: vms-write, refused: settings |
| POST | `/api/brief` | prefix | `_brief` | POST /api/brief: the first Claude press's Build it and Start without it, and a session's take as it starts: brief.verb, behind the gates here. |  |
| POST | `/api/design` | prefix | `_design` | POST /api/design: a Design section's Save of the language and the pages, and the file written into the tree: design.verb, for an account that works on the project. |  |
| POST | `/api/wiki` | exact | `_wiki` | POST /api/wiki: a page saved, removed or renamed, and the wiki pushed to or pulled from the forge's (wiki.verb), for an account that works on the project. |  |
| POST | `/api/ci-watch` | exact | `_ci_watch` | POST /api/ci-watch: look at a project's CI now (ciwatch.look), for an account that sees the project; the answer is what it found. |  |
| POST | `/api/devapp` | prefix | `_devapp` | The dev-instance controls: the Containers page's buttons, and `bb devapp` from a session. | refused: docker-write, refused: node |
| POST | `/api/changelog` | prefix | `_changelog` | Write back the Unreleased section a person rearranged: changelog.editor_verb. |  |
| POST | `/api/version` | prefix | `_version` | Move a project's version, or change who is allowed to: version.verb, behind the gates here. | refused: version |
| POST | `/api/signing` | exact | `_signing` | A project's Android signing keys (signing.verb, R106). | refused: signing |
| POST | `/api/members` | exact | `_members` | A project's owner, whether it is invite only, its people and its invitations, and an invitee's answer (membership.verb). |  |
| POST | `/api/signing-backup` | exact | `_post_signing_backup` | POST /api/signing-backup: the same, with the project's backup password in the body, never in a URL that lands in a log. |  |
| POST | `/api/artifacts` | prefix | `_artifacts` | Push an .xpi from a project's dist/ to the paired phone, install an .apk there, or stop a push: phone.artifact_verb, behind the gates here. |  |
| POST | `/api/nodelog` | prefix | `_nodelog` | A machine's own log, for a session that has been granted it. | refused: debug |
| POST | `/api/diag` | exact | `_diag` | The controller's diagnostics (diag.py). |  |
| POST | `/api/reports` | exact | `_reports` | Problems with BuilderBot itself, reported by any project's session (reports.py, bb report). |  |
| POST | `/api/v1/files` | exact | `_files` | A project's files for a person's own editor (files.py, R159): the account this request proved, a project it sees, and the file access its settings give it through the editor's door, asked on this request (ftp.access_for) |  |
| POST | `/api/phone` | prefix | `_phone` | Pair, connect, and push an extension, and the asking: a session's ask for adb, root or a container, and a person's answer. |  |
| POST | `/api/findings` | prefix | `_findings_log` | The Analysis view's log. |  |
| POST | `/api/tests` | prefix | `_tests` | The hand-written half of the registry: testreg.verb. |  |
| POST | `/api/presence` | prefix | `_presence` | This browser is in a project's notebook, and who else is (roadmap #26): presence.heartbeat, for a signed-in account on a project it sees. |  |
| POST | `/api/bugs` | prefix | `_bugs` | Report, edit, or close one bug: bugs.verb, behind the gates here. |  |
| POST | `/api/custom` | prefix | `_custom` | Save or delete one of the operator's own command lists: macros.custom_edit. | refused: terminal |
| POST | `/api/doctor` | prefix | `_doctor` | Re-run bb doctor now and answer with the fresh verdict. | refused: controller |
| POST | `/api/signout` | prefix | `_signout` | Sign this account out of a coding agent on one node (signin.sign_out): the login is that machine's, so that machine lets go of it. |  |
| POST | `/api/login-code` | prefix | `_login_code` | Hand the code from the browser to the sign-in flow: signin.take_code, for the person whose flow it is. |  |
| POST | `/api/signin` | prefix | `_signin` | Start a sign-in on one node, or stop the one that is running: signin.verb. |  |
