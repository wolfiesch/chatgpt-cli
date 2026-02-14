# ChatGPT CLI

## Overview

CLI tool that queries ChatGPT using Chrome authentication cookies and stealth browser automation. Supports GPT-5.2 thinking modes, file/image upload, conversation management, and dual browser engines (nodriver/camoufox).

**Repo**: `~/.claude/skills/chatgpt-cli/` (also GitHub: `wolfiesch/chatgpt-cli`)
**Also a Claude Code skill**: Trigger via `chatgpt` skill or direct CLI invocation.

## Commands

```bash
# Run any command (auto-manages venv)
python3 scripts/run.py chatgpt.py --prompt "Hello" --show-browser

# Help & version
python3 scripts/run.py chatgpt.py --help
python3 scripts/run.py chatgpt.py --version

# Lint & format
ruff check scripts/
ruff format --check scripts/

# Install deps manually (usually auto-handled by run.py)
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

## Architecture

### Entry Point
`scripts/run.py` -> `scripts/chatgpt.py` (main CLI)

### Shared Modules (CRITICAL)
These files live OUTSIDE this repo at `~/.claude/skills/shared/`:
- **`browser_engine.py`** — `BrowserEngine` Protocol + `create_engine()` factory. Provides engine-agnostic interface (`run_js`, `mouse_click`, `key_press`, `inject_cookies`, etc.)
- **`chrome_cookies.py`** — Canonical Chrome cookie extractor (macOS Keychain decryption)

Local `scripts/chrome_cookies.py` is a thin re-export wrapper via `importlib`.

### Key Patterns
- **Strategy Pattern**: `BrowserEngine` protocol allows swapping nodriver ↔ camoufox at runtime via `--engine`
- **CDP File Upload**: `Page.setInterceptFileChooserDialog` + `FileChooserOpened` event + `DOM.setFileInputFiles` with `backend_node_id` (nodriver path)
- **Playwright File Upload**: `set_input_files()` on `input[type="file"]` (camoufox path)
- **ProseMirror Input**: ChatGPT uses contenteditable divs, not textareas. Input via `execCommand('insertText')` with proper InputEvent dispatch.
- **React Click Simulation**: Full `mouseMoved -> mousePressed -> mouseReleased` sequence required for React's synthetic events.

### Model Selection
Uses `data-testid` attributes for reliable targeting:
- `model-switcher-dropdown-button` — opens dropdown
- `gpt-5.2-auto`, `gpt-5.2-instant`, `gpt-5.2-thinking`, `gpt-5.2-pro` — primary models
- Legacy models behind a submenu (`CHATGPT_LEGACY_SUBMENU_TESTID`)

## Configuration

`scripts/config.py` contains all selectors, URLs, timeouts, and model mappings. Edit there first when ChatGPT UI changes.

## Gotchas

- **macOS only** — Cookie decryption uses macOS Keychain (`security find-generic-password`)
- **`--show-browser` recommended** — Cloudflare blocks headless Chrome; always use for debugging
- **Shared module path**: `sys.path.insert(0, str(Path.home() / ".claude/skills/shared"))` in chatgpt.py
- **`clean_browser_locks()`** removed — was in config.py, no longer called after engine abstraction
- **`import nodriver`** only happens inside `if engine.has_cdp:` blocks (lazy import for camoufox compat)
- **File upload timeout**: 10s for file chooser event; increase if uploading large files
- **Cookie caching**: Encryption key cached at `data/.chrome_key_cache` to avoid repeated Keychain prompts
