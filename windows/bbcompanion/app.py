"""The companion app's window (R270 step 4): sign this machine in, see every
project its account is on (R104), pick a folder for the ones to keep, and
watch them: in step,
copying, waiting to send, or what went wrong; what Windows could not hold;
the conflict copies. Plain tkinter, so the app needs nothing but Python.
"""
import os
import platform
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import core, creds, settings

PAD = {"padx": 12, "pady": 6}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BuilderBot")
        self.minsize(560, 360)
        self.comp = None
        self.body = None
        # The projects the account is on, as the controller last said: read
        # on a thread of its own so the window never waits on the network.
        self.mine, self.mine_said = {}, ""
        # A lent verb asked under Ask (R270 step 6): the worker waits while
        # the window, on its own thread, puts the question to its person.
        self.asks = queue.Queue()
        self.show()

    def ask(self, req):
        """From a worker thread: whether the person at this PC says yes."""
        done, said = threading.Event(), []
        self.asks.put((req, done, said))
        done.wait(300)
        return bool(said and said[0])

    def clear(self):
        if self.body:
            self.body.destroy()
        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)
        return self.body

    def show(self):
        self.signin() if not creds.load().get("token") else self.main()

    # -- signing in ----------------------------------------------------------------
    def signin(self):
        f = self.clear()
        ttk.Label(f, text="Sign this machine in to BuilderBot", font=("", 13, "bold")).pack(anchor="w", **PAD)
        ttk.Label(f, text="Your password is used once, for this machine's own token, and kept nowhere.").pack(anchor="w", padx=12)
        s = settings.load()
        fields = {}
        for key, label, default, show in (("url", "Controller address", s.get("url", "https://"), ""),
                                          ("user", "Your account", "", ""), ("password", "Password", "", "*"),
                                          ("name", "This machine's name", platform.node(), "")):
            ttk.Label(f, text=label).pack(anchor="w", padx=12, pady=(8, 0))
            e = ttk.Entry(f, show=show, width=48)
            e.insert(0, default)
            e.pack(anchor="w", padx=12)
            fields[key] = e
        said = ttk.Label(f, text="", foreground="#c0392b")
        said.pack(anchor="w", **PAD)

        def go():
            r = core.sign_in(fields["url"].get().strip(), fields["user"].get().strip(),
                             fields["password"].get(), fields["name"].get().strip())
            if r.get("error"):
                said.config(text=r["error"])
                return
            url = fields["url"].get().strip().rstrip("/")
            creds.save({"url": url, "token": r["token"], "device": r["device"]["id"], "account": r["account"]})
            s2 = settings.load()
            s2["url"] = url
            settings.save(s2)
            self.main()
        ttk.Button(f, text="Sign in", command=go).pack(anchor="e", **PAD)

    # -- the projects kept here -----------------------------------------------------
    def main(self):
        f = self.clear()
        c, s = creds.load(), settings.load()
        top = ttk.Frame(f)
        top.pack(fill="x", **PAD)
        ttk.Label(top, text=f"{c.get('account', '')} on {c.get('url', '')}").pack(side="left")
        ttk.Button(top, text="Sign out", command=self.signout).pack(side="right")
        self.tree = ttk.Treeview(f, columns=("folder", "state"), show="tree headings", height=8)
        self.tree.heading("#0", text="Project")
        self.tree.heading("folder", text="Folder")
        self.tree.heading("state", text="State")
        self.tree.pack(fill="both", expand=True, padx=12)
        bar = ttk.Frame(f)
        bar.pack(fill="x", **PAD)
        ttk.Button(bar, text="Sync to a folder", command=self.add).pack(side="left")
        ttk.Button(bar, text="Stop syncing", command=self.remove).pack(side="left", padx=6)
        ttk.Button(bar, text="Open folder", command=self.open_folder).pack(side="left")
        ttk.Button(bar, text="Conflicts", command=self.show_conflicts).pack(side="right")
        self.note = ttk.Label(f, text="", foreground="#7f8c8d", wraplength=520, justify="left")
        self.note.pack(anchor="w", padx=12, pady=(0, 8))
        self.restart(s)
        threading.Thread(target=self.read_mine, daemon=True).start()
        self.tick()

    def read_mine(self):
        """Every half minute, the projects this account is on and what it
        may do in each, for the list; a project added to it shows up on its
        own (R104)."""
        while creds.load().get("token"):
            c = creds.load()
            try:
                st, r = core.DeviceDoor(c["url"], c["token"]).ctl.call("projects", {})
            except Exception as e:  # noqa: BLE001 - said under the list
                st, r = 0, {"error": f"{type(e).__name__}: {e}"}
            if st == 200:
                self.mine = {p["project"]: p for p in r.get("projects") or []}
                self.mine_said = ""
            else:
                self.mine_said = (r or {}).get("error") or f"the controller answered {st}"
            threading.Event().wait(30)

    def restart(self, s=None):
        s = s or settings.load()
        if self.comp:
            self.comp.stop()
        c = creds.load()
        self.comp = core.Companion(c["url"], c["token"], s["picked"], settings.data_dir(), pin=s.get("pin", ""),
                                   lend=s.get("lend"), asker=self.ask) \
            if s["picked"] else None
        if self.comp:
            self.comp.start()

    def tick(self):
        while not self.asks.empty():
            req, done, said = self.asks.get()
            said.append(messagebox.askyesno(
                "BuilderBot", f"{req.get('by') or 'A session'} asks this PC to {req['verb']} for {req['project']}"
                + (f":\n\n{req['why']}" if req.get("why") else ".") + "\n\nLet it?"))
            done.set()
        s = settings.load()
        st = self.comp.status() if self.comp else {"error": "", "projects": {}}
        self.tree.delete(*self.tree.get_children())
        left = 0
        keep = self.selected()
        # An archived project is out of sight on the dashboard (R119): one
        # not synced here goes to the foot of the list, and says so.
        def row(n):
            return self.mine.get(n) or {}

        def order(n):
            return (bool(row(n).get("archived")) and n not in s["picked"], n.lower())
        for name in sorted(set(self.mine) | set(s["picked"]), key=order):
            folder = s["picked"].get(name, "")
            if folder:
                p = st["projects"].get(name, {})
                word = (p.get("error") or ("copying " + str(p.get("copying")) if p.get("copying") else "")
                        or (f"{p.get('pending')} to send" if p.get("pending") else "")
                        or ("in step" if p.get("ready") else "starting"))
                left += len(p.get("left_out") or {})
                access = p.get("access") or (self.mine.get(name) or {}).get("access")
            else:
                word, access = "not synced", (self.mine.get(name) or {}).get("access")
            if access == "r":
                word += ", read-only"
            # Its lock (R119): one that holds this account out keeps the
            # copy read-only, and the note under the list says whose it is.
            word += core.lock_word(row(name))
            if row(name).get("archived"):
                word += ", archived"
            self.tree.insert("", "end", iid=name, text=name, values=(folder, word))
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)
        said = st.get("error") or self.mine_said or ""
        held = (self.mine.get(self.selected()) or {}).get("locked_why") or ""
        if held:
            said += (" " if said else "") + held
        up = st.get("update") or {}
        if up.get("pending"):
            said += (" " if said else "") + f"BuilderBot companion {up['pending']} is fetched: it starts the next time this app does."
        if left:
            said += (" " if said else "") + f"{left} file{'s' if left != 1 else ''} with names Windows cannot hold left out of the copy."
        self.note.config(text=said)
        self.after(2000, self.tick)

    def add(self):
        """The selected project kept in a folder picked here, or moved to
        another; with none selected, the first one not synced yet."""
        s = settings.load()
        name = self.selected() or next((n for n in sorted(self.mine, key=str.lower) if n not in s["picked"]), "")
        if not name:
            messagebox.showinfo("BuilderBot", self.mine_said or "You are not on any project yet: an owner adds you on "
                                "its People section, and it shows up here.")
            return
        folder = filedialog.askdirectory(title=f"The folder {name} is kept in")
        if not folder:
            return
        s["picked"][name] = os.path.abspath(folder)
        settings.save(s)
        self.restart(s)

    def selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else ""

    def remove(self):
        name = self.selected()
        if name and name in settings.load()["picked"] and messagebox.askyesno(
                "BuilderBot", f"Stop keeping {name} in step? Its folder stays as it is."):
            s = settings.load()
            s["picked"].pop(name, None)
            settings.save(s)
            self.restart(s)

    def open_folder(self):
        folder = settings.load()["picked"].get(self.selected())
        if folder:
            if sys.platform == "win32":
                os.startfile(folder)                       # noqa: S606 (the person's own folder)
            else:
                subprocess.Popen(["xdg-open", folder])     # noqa: S603,S607

    def show_conflicts(self):
        found = self.comp.conflicts() if self.comp else []
        messagebox.showinfo("BuilderBot", "\n".join(found) if found else
                            "No conflict copies. When a change here and one on the controller meet, the one that "
                            "arrived first is kept and the other is saved beside it as NAME.conflict-WHO-TIME.")

    def signout(self):
        if messagebox.askyesno("BuilderBot", "Sign this machine out? Its folders stay; Disconnect it on your Devices "
                                             "list to end its token at the controller too."):
            if self.comp:
                self.comp.stop()
            creds.forget()
            self.signin()


def main():
    App().mainloop()
    return 0
