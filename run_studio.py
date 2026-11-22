#!/usr/bin/env python3
"""Launcher for Keeper Studio. Run this file to open the app.

  --selftest   load config and models, then exit (used by the Windows build)
  --browser    open in the default web browser instead of an app window
"""

import sys

from keeperstudio.app import main

if __name__ == "__main__":
    raise SystemExit(main())
