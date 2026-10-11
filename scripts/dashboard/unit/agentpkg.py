"""The node agent for a test, as one object, the way the single file was.

The agent is the builderbot_agent package now (scripts/agent). load() reads
a fresh copy of it under a name of its own, so one test file's patches never
reach another's, as when each loaded the file by path. Reading agent.NAME
finds the name wherever the package defines it; agent.NAME = value sets it
in every module that holds it, which is where the code under test looks it
up (a module that did `from .base import log` has its own `log`).
"""
import importlib
import importlib.util
import itertools
import os
import sys

PKG = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "agent", "builderbot_agent"))
_seq = itertools.count()


class Agent:
    def __init__(self, mods):
        object.__setattr__(self, "_mods", mods)

    def __getattr__(self, name):
        for m in self._mods:
            if name in vars(m):
                return vars(m)[name]
        raise AttributeError(f"the agent has no {name}")

    def __setattr__(self, name, value):
        held = [m for m in self._mods if name in vars(m)]
        for m in held or self._mods[:1]:
            setattr(m, name, value)

    def module(self, name):
        """One module of the package (base, census, sessions, ...)."""
        return next(m for m in self._mods if m.__name__.rsplit(".", 1)[-1] == name)


def load(tag="agent"):
    name = f"bb_{tag}_{next(_seq)}"
    spec = importlib.util.spec_from_file_location(name, os.path.join(PKG, "__init__.py"),
                                                  submodule_search_locations=[PKG])
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[name] = pkg
    spec.loader.exec_module(pkg)
    subs = sorted(f[:-3] for f in os.listdir(PKG) if f.endswith(".py") and f != "__init__.py")
    # the modules that define things first, so a read finds a name's home
    mods = [importlib.import_module(f"{name}.{s}") for s in subs]
    return Agent(mods + [pkg])
