#!/usr/bin/env python3
"""
Thin re-export wrapper — delegates to the shared canonical version at
~/.claude/skills/shared/chrome_cookies.py

Uses importlib to load by absolute path (avoids circular import since this file
is also named chrome_cookies.py).
"""

import importlib.util
from pathlib import Path

_SHARED = Path.home() / ".claude/skills/shared/chrome_cookies.py"
_spec = importlib.util.spec_from_file_location("_shared_chrome_cookies", _SHARED)
assert _spec is not None and _spec.loader is not None, f"Cannot load {_SHARED}"
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# Re-export all public symbols
extract_cookies = _mod.extract_cookies
get_chrome_encryption_key = _mod.get_chrome_encryption_key
decrypt_cookie_value = _mod.decrypt_cookie_value
chrome_timestamp_to_unix = _mod.chrome_timestamp_to_unix
CHROME_COOKIE_PATH = _mod.CHROME_COOKIE_PATH
CHROME_LOCAL_STATE = _mod.CHROME_LOCAL_STATE
KEY_CACHE_FILE = _mod.KEY_CACHE_FILE
main = _mod.main

if __name__ == "__main__":
    main()
