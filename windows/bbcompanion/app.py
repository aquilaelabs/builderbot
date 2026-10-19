"""The companion app's window (R270 step 4): sign this machine in, pick the
projects it keeps and the folder for each, and watch them: in step,
copying, waiting to send, or what went wrong; what Windows could not hold;
the conflict copies. Plain tkinter, so the app needs nothing but Python.
"""
import os
import platform
import subprocess
import sys
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
        self.show()

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
        ttk.Button(bar, text="Add a project", command=self.add).pack(side="left")
        ttk.Button(bar, text="Remove", command=self.remove).pack(side="left", padx=6)
        ttk.Button(bar, text="Open folder", command=self.open_folder).pack(side="left")
        ttk.Button(bar, text="Conflicts", command=self.show_conflicts).pack(side="right")
        self.note = ttk.Label(f, text="", foreground="#7f8c8d", wraplength=520, justify="left")
        self.note.pack(anchor="w", padx=12, pady=(0, 8))
        self.restart(s)
        self.tick()

    def restart(self, s=None):
        s = s or settings.load()
        if self.comp:
            self.comp.stop()
        c = creds.load()
        self.comp = core.Companion(c["url"], c["token"], s["picked"], settings.data_dir(), pin=s.get("pin", "")) \
            if s["picked"] else None
        if self.comp:
            self.comp.start()

    def tick(self):
        s = settings.load()
        st = self.comp.status() if self.comp else {"error": "", "projects": {}}
        self.tree.delete(*self.tree.get_children())
        left = 0
        for name, folder in s["picked"].items():
            p = st["projects"].get(name, {})
            word = (p.get("error") or ("copying " + str(p.get("copying")) if p.get("copying") else "")
                    or (f"{p.get('pending')} to send" if p.get("pending") else "")
                    or ("in step" if p.get("ready") else "starting"))
            if p.get("access") == "r":
                word += ", read-only"
            self.tree.insert("", "end", iid=name, text=name, values=(folder, word))
            left += len(p.get("left_out") or {})
        said = st.get("error") or ""
        if left:
            said += (" " if said else "") + f"{left} file{'s' if left != 1 else ''} with names Windows cannot hold left out of the copy."
        self.note.config(text=said)
        self.after(2000, self.tick)

    def add(self):
        c = creds.load()
        st, r = core.DeviceDoor(c["url"], c["token"]).ctl.call("projects", {})
        if st != 200:
            messagebox.showerror("BuilderBot", (r or {}).get("error") or f"the controller answered {st}")
            return
        names = [p["project"] for p in r.get("projects") or []]
        if not names:
            messagebox.showinfo("BuilderBot", "No project's editor access lets you in yet: it is set in each project's settings.")
            return
        win = tk.Toplevel(self)
        win.title("Add a project")
        ttk.Label(win, text="Project").pack(anchor="w", **PAD)
        pick = ttk.Combobox(win, values=names, state="readonly")
        pick.current(0)
        pick.pack(anchor="w", padx=12)

        def go():
            folder = filedialog.askdirectory(title=f"The folder {pick.get()} is kept in")
            if not folder:
                return
            s = settings.load()
            s["picked"][pick.get()] = os.path.abspath(folder)
            settings.save(s)
            win.destroy()
            self.restart(s)
        ttk.Button(win, text="Choose its folder", command=go).pack(anchor="e", **PAD)

    def selected(self):
        sel = self.tree.selection()
        return sel[0] if sel else ""

    def remove(self):
        name = self.selected()
        if name and messagebox.askyesno("BuilderBot", f"Stop keeping {name} in step? Its folder stays as it is."):
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
