# ChatGPT CLI — Sprint Tracker

> **Goal**: Expand ChatGPT CLI from prompt-only to a full-featured wrapper of the ChatGPT web interface, matching and exceeding Grok CLI parity.

## Current Status: Phases 1-4 COMPLETE (25/25 features implemented)

---

## Phase 1: Grok CLI Parity *(TESTED & VERIFIED)*

Port features that the Grok CLI already has, using it as a reference implementation.

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 1 | `dom_debug.py` diagnostic tool | `DONE` | Adapted from Grok's dom_debug.py for ChatGPT DOM |
| 2 | Refactor: extract `_setup_authenticated_browser()` | `DONE` | Shared browser setup for all operations |
| 3 | `--list-chats [--limit N]` | `DONE` | Sidebar scraping, extract titles + IDs + date groups |
| 4 | `--get-chat ID/TITLE` | `DONE` | Click into chat, extract turn-by-turn messages |
| 5 | `--verbose` flag | `DONE` | Debug logging to stderr (bundled with refactor) |
| 6 | Update SKILL.md + run.py | `DONE` | Document new commands |

### Architecture Decisions
- **Chose refactor-first**: Extract `_setup_authenticated_browser()` before adding features, to avoid duplicating the cookie/browser setup code in 3 functions.
- **ChatGPT sidebar uses `<a href="/c/{id}">`**: Cleaner than Grok's sidebar — we get real conversation IDs directly from the DOM.
- **Message turn detection via `data-message-author-role`**: ChatGPT marks each message with `user` or `assistant` role in a data attribute, so HTML-based parsing should be more reliable than Grok's heuristic approach.

---

## Phase 2: ChatGPT-Specific Core *(TESTED & VERIFIED)*

| # | Feature | Status | Complexity | Notes |
|---|---------|--------|------------|-------|
| 7 | `--new-chat` | `DONE` | Easy | Force fresh conversation via sidebar button or URL nav |
| 8 | Model switch hardening | `DONE` | Hard | Full rewrite: testid-based selection + CDP mouse events + legacy submenu |
| 9 | `--continue-chat CHAT_ID` | `DONE` | Medium | Send prompt in existing chat (idx-N, title, or UUID) |
| 10 | `--list-projects` | `DONE` | Medium | Sidebar Projects section scraping via button expand + `a[href*="/g/g-p-"]` |
| 11 | `--project NAME` | `DONE` | Medium | Navigate to project URL before sending prompt, name/ID resolution |
| 12 | `--search-chats QUERY` | `DONE` | Medium | Cmd+K search dialog via CDP Meta key events |

---

## Phase 3: Productivity Multipliers *(TESTED & VERIFIED)*

| # | Feature | Status | Complexity | Notes |
|---|---------|--------|------------|-------|
| 13 | `--code-only` | `DONE` | Easy | Extract fenced code blocks from response |
| 14 | `--temp-chat` | `DONE` | Easy | Temporary chat toggle (DOM selector + URL fallback) |
| 15 | `--search` / `--no-search` | `DONE` | Easy-Medium | Web search toggle via toolbar detection |
| 16 | `--export CHAT_ID --format` | `DONE` | Easy-Medium | Export as md/json/txt via `format_chat_export()` |
| 17 | `--delete-chat ID` | `DONE` | Medium | Delete via sidebar hover menu + confirmation |
| 18 | `--archive-chat ID` | `DONE` | Medium | Archive via sidebar hover menu |

---

## Phase 4: Advanced *(COMPLETE)*

| # | Feature | Status | Complexity | Notes |
|---|---------|--------|------------|-------|
| 19 | `--file PATH` | `DONE` | Hard | File upload via CDP file chooser interception + ⌘U shortcut |
| 20 | `--image PATH` | `DONE` | Hard | Image upload for vision (same pipeline as --file) |
| 21 | `--gpt NAME` | `DONE` | Medium-Hard | Custom GPT selection via sidebar search + navigation |
| 22 | `--list-memories` | `DONE` | Hard | Settings → Personalization → Memory extraction |
| 23 | `--share CHAT_ID` | `DONE` | Medium | Sidebar hover menu → "Share" → extract share URL |
| 24 | `--rename-chat CHAT_ID` | `DONE` | Easy-Medium | Sidebar hover menu → "Rename" → inline edit |
| 25 | `--generate-image PROMPT` | `DONE` | Medium | DALL-E image gen via prompt + image download |

### Architecture Decisions (Phase 4)
- **CDP file chooser interception over DOM manipulation**: React's synthetic event system doesn't see manual JS `change` events on file inputs. The `FileChooserOpened` event provides the exact `backend_node_id` React opened, making `DOM.setFileInputFiles` work natively.
- **⌘U keyboard shortcut over menu navigation**: ChatGPT's '+' menu has container elements that make click targeting fragile. The ⌘U shortcut ("Add photos & files") is a single keypress that reliably triggers the file chooser.
- **Unified `--file` and `--image` pipeline**: Both use the same `_upload_attachments()` function. ChatGPT's file picker accepts all types, and GPT-5.2 auto-detects images for vision. The CLI distinction is purely for user ergonomics.
- **`Page.handleFileChooser` doesn't exist**: This CDP method was removed from Chrome. Workaround: disable interception (dismisses pending chooser) then `DOM.setFileInputFiles` with `backend_node_id` from the event.

---

## Changelog

### 2026-02-13
- Created sprint tracker
- Started Phase 1 implementation
- Completed Phase 1:
  - `dom_debug.py` diagnostic tool (inspects sidebar, input, send button, response containers, model selector)
  - Extracted `_setup_authenticated_browser()` shared browser setup (~130 lines of cookie/browser boilerplate)
  - `--list-chats [--limit N]` with dual strategy (DOM extraction + innerText fallback)
  - `--get-chat ID/TITLE` supporting index (`idx-N`), conversation ID, and title substring lookup
  - `--verbose` debug logging to stderr
  - Updated SKILL.md + run.py with all new commands
- Architecture: chatgpt.py refactored from 809 → 1212 lines with clean separation of concerns
- **CRITICAL BUG FIX**: nodriver's `page.evaluate()` silently returns `None` on chatgpt.com
  - Root cause: nodriver execution context mismatch on sites with heavy JS
  - Fix: Created CDP helper using raw `Runtime.evaluate` protocol (not Python eval)
  - Migrated all 19 calls in chatgpt.py to CDP helper
  - Migrated all 21 calls in dom_debug.py to CDP helper
  - Arrow functions wrapped as IIFEs: `(() => { ... })()` for correct return values
  - Complex objects serialized via `call_function_on` + `JSON.stringify`
- Validated dom_debug.py against live ChatGPT:
  - `document.readyState: complete` (was `None` before fix)
  - 28 sidebar chat links found with full conversation IDs
  - Input field located, send button clicked successfully
  - Response containers detected (`.agent-turn`, `article[data-testid*="conversation-turn"]`)
  - DOM observation: `data-message-author-role="assistant"` only appears after thinking completes
- **End-to-end testing PASSED** — all 3 modes verified against live ChatGPT:
  - `--list-chats --limit 10 --json`: 10 chats with full UUIDs, titles, URLs
  - `--get-chat idx-0 --json`: Retrieved 2-turn conversation with correct role attribution
  - `--prompt "What is 2+2?" --model gpt-4o --json`: Got response "4" in 13s, 1 token response
- Phase 1 status: **TESTED & VERIFIED**

### 2026-02-13 (continued)
- **Phase 2 implementation — features 7, 8, 9 completed:**
  - `--new-chat`: Force fresh conversation via sidebar "New chat" button (JS click fallback: URL navigation)
  - `--continue-chat CHAT_ID`: Navigate to existing chat by idx-N, title substring, or UUID, then send follow-up prompt
  - Model switch hardening — **complete rewrite required** due to ChatGPT UI restructure:
    - ChatGPT model dropdown completely redesigned (Feb 2026): no longer separate models
    - **Primary**: GPT-5.2 with 4 thinking modes (Auto, Instant, Thinking, Pro)
    - **Legacy**: GPT-5.1, GPT-5, GPT-4.5, o3 behind "Legacy models" submenu
    - GPT-4o and o3-mini removed from ChatGPT UI entirely
    - Selection uses `data-testid` attributes (e.g., `model-switcher-gpt-5-2-instant`) for reliable targeting
    - **Critical fix**: React's synthetic event system requires full `mouseMoved + mousePressed + mouseReleased` CDP sequence — nodriver's `.click()` and JS `.click()` both fail
    - Added `_cdp_click()` helper for reliable CDP mouse event dispatch
    - Added `_get_element_center()` helper for testid-based coordinate lookup
  - Updated config.py: New model structure with `CHATGPT_MODEL_TESTIDS`, `CHATGPT_LEGACY_MODELS`, `CHATGPT_LEGACY_SUBMENU_TESTID`
  - Default model changed from `gpt-5.2-pro` to `auto` (GPT-5.2 Auto)
- **End-to-end testing PASSED** — all Phase 2 features verified:
  - `--model instant`: Switched to GPT-5.2 Instant, got response "10" for "5+5" in 6s (no thinking)
  - `--model o3`: Opened dropdown → Legacy submenu → o3, button verified "ChatGPT o3"
  - `--continue-chat idx-0`: Resolved to UUID, follow-up response correctly referenced prior conversation
  - `--new-chat`: Verified in prior session (clicked "New Chat" button)
- Phase 2 core features status: **TESTED & VERIFIED**
- **SKILL.md updated** for Phase 2:
  - Description updated: GPT-5.2 thinking modes, `--continue-chat`, `--new-chat`
  - Trigger list: Added "continue conversation" and "start fresh chat" triggers
  - Core Usage: New sections for `--continue-chat` and `--new-chat` with examples
  - Model examples: Replaced `gpt-4o`/`gpt-5.2-pro` with `auto`/`instant`/`thinking`/`pro`/`o3`
  - Script Reference: Added `--continue-chat` and `--new-chat` modes
  - Model Reference: Split into GPT-5.2 Thinking Modes + Legacy Models tables
  - Removed GPT-4o and o3-mini (no longer in ChatGPT UI)
  - Integration example: Updated `--model pro` + added `--continue-chat` workflow
  - How It Works: Updated model selection to describe `data-testid` + CDP mouse events

### 2026-02-13 (Phase 2 features 10-12)
- **Phase 2 implementation — features 10, 11, 12 completed:**
  - `--search-chats QUERY`: Search conversations via Cmd+K (CDP Meta+K key events)
    - Opens search dialog overlay, types query via CDP key events
    - Extracts results from `[role="dialog"]` containing `a[href*="/c/"]` links
    - Returns chat ID, title, URL for each match
  - `--list-projects`: List ChatGPT Projects from sidebar
    - Finds "Projects" button by text match (no testid available)
    - Checks if section expanded before clicking (avoids toggle-collapse)
    - Extracts project links via `a[href*="/g/g-p-"]` selector
    - Returns project ID, name, URL
  - `--project NAME`: Send prompt within project context
    - Resolves project by name (case-insensitive substring) or ID
    - Navigates to project URL before sending prompt
    - Model selection skipped when in project context (project has its own model config)
  - Fixed `_cdp_js` → `_cdp_eval` naming bug (5 occurrences from probe script copy-paste)
  - Added CLI arguments: `--search-chats`, `--list-projects`, `--project` with proper validation
  - Updated argparse validation: `--project` requires `--prompt`, mutually exclusive with `--continue-chat`
  - Updated CLI epilog with new command examples
- **DOM discovery** (via 2 probe scripts against live ChatGPT):
  - ChatGPT has no visible search button — Cmd+K opens command-palette search dialog
  - Search input identified by `placeholder="Search chats..."`
  - Projects section is collapsible sidebar, button targeted by text content (no testid)
  - Project URL pattern: `/g/g-p-{uuid}-{slug}/project`
  - 5 projects found: OmniModel, CS Tutor, Nothing, Bash Explain, CDS - Other
- Phase 2 status: **ALL FEATURES TESTED & VERIFIED**

### 2026-02-13 (Phase 3)
- **Phase 3 implementation — all 6 features completed:**
  - `--code-only` (feature 13): Extract fenced code blocks from response
    - Regex pattern: `` ```(?:\w*)\n(.*?)``` `` with `re.DOTALL`
    - Works with both `--json` (adds `code_blocks` array) and plain output
    - Falls back to full response if no code blocks found
  - `--temp-chat` (feature 14): Temporary chat mode
    - Multi-strategy DOM detection (testid, text content, `div[role="switch"]`)
    - URL parameter fallback: `?temporary-chat=true`
  - `--search`/`--no-search` (feature 15): Web search toggle
    - Detects toggle state via `aria-checked`, `data-state`, `aria-pressed`
    - Only clicks if current state differs from desired state
  - `--export CHAT_ID --format` (feature 16): Export conversations
    - Three formats: `md` (markdown with headers), `json` (raw data), `txt` (plain text)
    - Uses existing `get_chatgpt_chat()` + new `format_chat_export()` helper
  - `--delete-chat ID` (feature 17): Delete conversations
    - Hover menu interaction: mouseMoved → find options button → click → find "Delete" → click → confirm
    - Supports idx-N, title substring, and UUID identifiers
  - `--archive-chat ID` (feature 18): Archive conversations
    - Same hover menu pattern as delete, without confirmation step
    - Shared `delete_or_archive_chat()` function for both operations
  - Added `temp_chat: bool` and `web_search: bool | None` parameters to `prompt_chatgpt()`
  - Updated CLI epilog with Phase 3 command examples
  - Fixed pre-existing Pyright error: `chat_index` type annotation (`int | None` → `int`)
- Architecture: chatgpt.py grew from 2082 → 2272 lines
  - New helper functions: `extract_code_blocks()`, `format_chat_export()`, `delete_or_archive_chat()`
  - 3 new CLI handler blocks in main() (export, delete, archive)
  - Code-only output handled as post-processing on prompt response
- Phase 3 status: **ALL FEATURES DONE** (awaiting end-to-end testing)

### 2026-02-14 (Bug Fixes + E2E Testing)
- **CRITICAL BUG FIX: Multi-line response extraction**
  - Bug: `wait_for_response()` only captured first non-UI-chrome line via `response_text = line; break`
  - For code block responses, `innerText` starts with "python" (language label), so only "python" was returned
  - Fix 1: Changed Method 1 and Method 2 to `'\n'.join(filtered)` — captures ALL filtered lines
  - Fix 2: Changed final extraction comparison from `if final_text == response_text:` to `if final_text:` — returns full DOM text without requiring equality with partial poll text
  - Added unified `_ui_chrome_re` compiled regex for UI chrome filtering
- **CRITICAL BUG FIX: DOM reconstruction for clean markdown**
  - Bug: `innerText` flattens HTML structure, including code block UI chrome ("python\nCopy code\n" prefix)
  - Bug: `extract_code_blocks()` needs ``` fences which `innerText` doesn't preserve → empty `code_blocks` array
  - Fix: Replaced simple `innerText` in final extraction JS with structured DOM walking:
    - `<PRE>` elements: extracts `<code>` child, detects language from `class="language-xxx"`, wraps with ``` fences
    - Other elements: uses `innerText` directly
    - Fallback: returns `container.innerText` if structured walk produces nothing
  - Result: Clean response text + populated `code_blocks` array for `--code-only`
- **End-to-end testing PASSED — ALL Phase 2 features 10-12 verified:**
  - `--search-chats "prime"`: Found matching conversations via Cmd+K search dialog
  - `--list-projects`: Found 5 projects (CS Tutor, OmniModel, Nothing, Bash Explain, CDS - Other)
  - `--project "CS Tutor" --prompt "Explain recursion"`: Response in 5s within project context
- **End-to-end testing PASSED — ALL Phase 3 features verified:**
  - `--code-only --json`: Clean code extraction with populated `code_blocks` array
  - `--temp-chat`: Temporary chat toggle working
  - `--export idx-0 --format md/json/txt`: All 3 export formats working
  - `--archive-chat idx-4`: Chat archived successfully
  - `--delete-chat idx-3`: Chat deleted with confirmation
- Phase 2 status: **TESTED & VERIFIED**
- Phase 3 status: **TESTED & VERIFIED**
- All 18 features across Phases 1-3 now fully implemented and E2E tested

### 2026-02-14 (Phase 4 — features 19-20)
- **Phase 4 implementation — features 19, 20 completed:**
  - `--file PATH` (feature 19): Upload files to ChatGPT via CDP
    - Created `_upload_attachments()` function using CDP file chooser interception
    - **4 implementation iterations** to get working:
      1. `DOM.setFileInputFiles` + manual JS event dispatch → failed (React didn't see manual `change` events)
      2. `Page.handleFileChooser` via raw CDP generator + menu click → failed (wrong click target in container div)
      3. ⌘U shortcut + `Page.handleFileChooser` → failed (`Page.handleFileChooser` removed from Chrome, error `-32601`)
      4. ⌘U shortcut + `DOM.setFileInputFiles(backend_node_id=event.backend_node_id)` → **SUCCESS**
    - Final pipeline: register `FileChooserOpened` handler → enable interception → ⌘U → handler fires with `backend_node_id` → disable interception → `DOM.setFileInputFiles`
    - Cleanup in `finally` block: disables interception + removes event handler
    - Created probe script (`probe_file_upload.py`) for DOM discovery
  - `--image PATH` (feature 20): Upload images for GPT-5.2 vision
    - Uses same `_upload_attachments()` pipeline as `--file`
    - ChatGPT's ⌘U shortcut opens "Add photos & files" — accepts all file types
    - GPT-5.2 auto-detects images and uses vision capabilities
    - `--file` and `--image` merged into single list at CLI level, both supported via `action="append"`
  - Added `files` parameter to `prompt_chatgpt()` function signature
  - Added `--file` and `--image` CLI arguments with validation (`requires --prompt`)
  - Updated CLI epilog with file/image upload examples
- **DOM discovery** (via `probe_file_upload.py`):
  - 3 hidden `<input type="file">` elements on ChatGPT page
  - '+' button: `data-testid="composer-plus-btn"`
  - Menu items: "Add photos & files" (⌘U), "Take photo", "Add from OneDrive"
  - File input `accept` attribute varies but `DOM.setFileInputFiles` bypasses it
- **Key technical discoveries**:
  - `Page.handleFileChooser` CDP method removed from Chrome (error `-32601`)
  - `FileChooserOpened` event provides `backend_node_id` — the exact input React opened
  - `DOM.setFileInputFiles` with `backend_node_id` dispatches native browser events that React's capture-phase listeners pick up
  - ⌘U shortcut (modifiers=4 for Meta) is more reliable than menu navigation
  - nodriver's `page.add_handler(event_type, callback)` works with `asyncio.Future` for event-driven flows
- **End-to-end testing PASSED — features 19-20 verified:**
  - `--file /tmp/test_upload.py --prompt "What does this code do?"`: Correctly analyzed Fibonacci code, identified O(2^n) time complexity
  - `--image /tmp/test_upload.png --prompt "Describe this image"`: Correctly described test image ("dark blue rectangular box with light blue border... white text 'Test Image for ChatGPT'")
  - Both tests: `success: true`, 5-11s total time
- Phase 4 features 19-20 status: **TESTED & VERIFIED**

### 2026-02-14 (Phase 4 — features 21-25)
- **Phase 4 implementation — features 21-25 completed:**
  - `--gpt NAME` (feature 21): Custom GPT selection
    - Navigates to sidebar, searches for GPT by name (case-insensitive fuzzy match)
    - Uses CDP JS evaluation to find matching sidebar link, clicks to navigate
    - Sends prompt within the custom GPT context
    - `--gpt` and `--project` are mutually exclusive (validated at argparse level)
  - `--list-memories` (feature 22): Memory management
    - Navigates to Settings → Personalization → Memory section
    - Extracts memory items from the DOM
    - Returns list of saved memories with JSON/raw output support
  - `--share CHAT_ID` (feature 23): Generate share link
    - Locates chat in sidebar via `_find_chat_in_sidebar()` reuse
    - Hover menu → "Share" option → extracts generated share URL
    - Returns shareable link in JSON or plain output
  - `--rename-chat CHAT_ID --new-name NAME` (feature 24): Rename conversation
    - Sidebar hover → three-dot menu → "Rename" → inline text edit
    - Clears existing name, types new name, presses Enter to confirm
    - Requires `--new-name` flag (validated at argparse level)
  - `--generate-image PROMPT --output DIR` (feature 25): DALL-E image generation
    - Sends image generation prompt via `prompt_chatgpt()` with `_return_engine=True`
    - Extracts `<img>` URLs from the response, downloads via `httpx`
    - Saves to `--output` directory (defaults to current directory)
    - Returns download paths in JSON output
  - Added `gpt` and `_return_engine` parameters to `prompt_chatgpt()` signature
  - Added `--gpt`, `--new-name`, `--output` CLI arguments with proper validation
  - Updated CLI epilog with Phase 4 feature examples
- **Code quality fixes:**
  - Fixed Python 3.10 f-string backslash escape error in GPT search JS code
  - Fixed `headless: bool = None` → `headless: bool | None = None` type annotation
  - Added `py.typed` PEP 561 marker file
  - All `ruff check` and `ruff format` checks pass clean
- Updated README.md with new features, usage sections, and CLI reference
- All 25 features across Phases 1-4 now fully implemented
- Phase 4 status: **ALL FEATURES DONE** (features 21-25 awaiting E2E testing)
