#!/usr/bin/env python3
"""BuilderBot's node agent, the entry: the agent itself is the builderbot_agent
package beside this file (its __init__ says what it is and how it runs).

The controller ships the two as one zip with this file as its __main__.py
(builderbot_agent/bundle.py), and python runs that zip as it runs this file,
so a node still keeps one file at one path. From a checkout, this runs the
package beside it.
"""
import os
import sys

if __name__ == "__main__":
    # Inside the zip this is the zip itself, already on the path.
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    from builderbot_agent.cli import main
    main(sys.argv[1:])
