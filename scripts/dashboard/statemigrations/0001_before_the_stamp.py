"""State 0 to 1: a /config from before the stamp, brought to what 0.5.0
writes. The one-off migrators that ran at every start until then, in their
order; each is idempotent and marks itself done in the store where it can,
so an install that ran them already is not changed by any.

  * roles as areas (R152): an account on `user` carries no role, and each
    project's owner holds PROJECT_owner on it;
  * a role on a project given on the project alone (R155), once the
    project records are in step with the disk;
  * an owner record that carried "*" (every project) gets the projects
    that exist now by name (R135);
  * apps_token, a setting from when the apps' releases were private, taken
    off disk.

Shipped with 0.5.0: never edited (stateversion.py says why).
"""
import membership
import registry
import settings
import users


def run(ctx):
    users.migrate_r152({p: (r or {}).get("owner") or "" for p, r in membership._owners()["projects"].items()})
    registry.sync()
    users.migrate_r155()
    moved = users.migrate_star(ctx["project_names"]())
    if moved:
        print(f"dashboard: {moved} account(s) moved from every project to the ones that exist (R135)", flush=True)
    with settings._lock:
        d = settings.load()
        if "apps_token" in d:
            d.pop("apps_token")
            settings.write_json(settings.FILE, d)
