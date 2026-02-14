---
name: chatgpt-cli
description: CLI interface to ChatGPT. Send prompts and get responses via command line, with support for GPT-5.2 thinking modes (Auto, Instant, Thinking, Pro) and legacy models (o3, GPT-4.5). Upload files and images for analysis/vision. Continue existing conversations, start new chats, search/list/export/delete/archive history, extract code blocks, toggle temp chat and web search. Uses stealth browser with Chrome auth for authenticated access.
---

# ChatGPT CLI Skill

Query ChatGPT from the command line using your existing Chrome authentication. Supports GPT-5.2 with 4 thinking modes (Auto, Instant, Thinking, Pro) and legacy models (o3, GPT-4.5) behind a submenu. Upload files for analysis and images for vision. Continue existing conversations, start fresh chats, search/export/delete/archive history, extract code blocks, use temporary chats, and toggle web search.

## When to Use This Skill

Trigger when user:
- Wants to query ChatGPT/OpenAI
- Mentions "ask ChatGPT", "prompt GPT", "ChatGPT says"
- Needs extended reasoning on complex problems
- Wants to compare responses between Claude and ChatGPT
- Specifically requests GPT-5.2 Pro, o3, or other OpenAI models
- Wants to list or browse ChatGPT conversations/chat history
- Wants to retrieve or read a specific ChatGPT conversation
- Asks "what did ChatGPT say about..." or wants to find a previous chat
- Wants to continue an existing ChatGPT conversation with a follow-up
- Wants to start a fresh/new ChatGPT conversation
- Wants to export or save a ChatGPT conversation
- Wants to delete or archive a ChatGPT conversation
- Wants to extract just the code from a ChatGPT response
- Wants to use temporary/ephemeral chat mode
- Wants to enable or disable web search in ChatGPT
- Wants to search ChatGPT conversations
- Wants to see ChatGPT projects
- Wants to upload a file to ChatGPT for analysis
- Wants to send an image to ChatGPT for vision/description
- Says "have ChatGPT look at this file" or "analyze this with GPT"

## Prerequisites

1. **Logged into ChatGPT in Chrome**: The skill uses your Chrome session
2. **ChatGPT Pro subscription**: Required for GPT-5.2 Pro access (optional for other models)

## Critical: Always Use run.py Wrapper

**NEVER call scripts directly. ALWAYS use `python3 scripts/run.py [script]`:**

```bash
# CORRECT:
python3 scripts/run.py chatgpt.py --prompt "Your question here"

# WRONG:
python3 scripts/chatgpt.py --prompt "..."  # Fails without venv!
```

## Core Usage

### Basic Query (uses GPT-5.2 Auto by default)
```bash
cd ~/.claude/skills/chatgpt-cli
python3 scripts/run.py chatgpt.py --prompt "Explain quantum entanglement" --show-browser
```

### With Different Models
```bash
# Auto mode — ChatGPT decides how long to think (default)
python3 scripts/run.py chatgpt.py --prompt "Hello" --model auto

# Instant — answers right away, no thinking
python3 scripts/run.py chatgpt.py --prompt "What is 2+2?" --model instant

# Thinking — thinks longer for better answers
python3 scripts/run.py chatgpt.py --prompt "Analyze this algorithm" --model thinking

# Pro — research-grade intelligence, up to 30 min
python3 scripts/run.py chatgpt.py --prompt "Prove this theorem" --model pro

# Legacy model (o3 reasoning)
python3 scripts/run.py chatgpt.py --prompt "Solve this step by step" --model o3
```

### Continue an Existing Conversation
```bash
# By index from --list-chats (0 = most recent)
python3 scripts/run.py chatgpt.py --continue-chat idx-0 --prompt "Follow up on that" --show-browser

# By conversation UUID
python3 scripts/run.py chatgpt.py --continue-chat "abc123-def456-..." --prompt "Tell me more"

# By title substring (case-insensitive)
python3 scripts/run.py chatgpt.py --continue-chat "quantum" --prompt "What about entanglement?"
```

### Start a New Chat
```bash
# Force a fresh conversation (ignores any existing chat context)
python3 scripts/run.py chatgpt.py --new-chat --prompt "Start fresh: explain relativity" --show-browser
```

### With Options
```bash
# Custom timeout for very complex reasoning
python3 scripts/run.py chatgpt.py --prompt "Complex math proof" --timeout 2400 --show-browser

# Save screenshot
python3 scripts/run.py chatgpt.py --prompt "Design a system" --screenshot /tmp/chatgpt.png

# JSON output for parsing
python3 scripts/run.py chatgpt.py --prompt "Quick question" --json

# Raw output (just the response text, for piping)
python3 scripts/run.py chatgpt.py --prompt "One word: capital of France?" --raw

# Run in background with headless mode (if Cloudflare permits)
python3 scripts/run.py chatgpt.py --prompt "Research task" --headless
```

### Piping to Other Tools
```bash
# Get ChatGPT's response and pipe it
python3 scripts/run.py chatgpt.py --prompt "List 5 trending topics" --raw | head -5

# Use in shell scripts
CHATGPT_RESPONSE=$(python3 scripts/run.py chatgpt.py --prompt "Explain briefly" --raw)
echo "ChatGPT says: $CHATGPT_RESPONSE"
```

## Chat History

### List Recent Conversations
```bash
cd ~/.claude/skills/chatgpt-cli

# List chats with formatted output
python3 scripts/run.py chatgpt.py --list-chats --show-browser

# JSON output with metadata
python3 scripts/run.py chatgpt.py --list-chats --json

# Limit to 10 most recent
python3 scripts/run.py chatgpt.py --list-chats --limit 10

# With debug logging
python3 scripts/run.py chatgpt.py --list-chats --verbose --show-browser
```

### Retrieve a Specific Conversation
```bash
# By conversation ID (from --list-chats output)
python3 scripts/run.py chatgpt.py --get-chat "abc123-def456-..." --show-browser

# By index from --list-chats (0-based)
python3 scripts/run.py chatgpt.py --get-chat idx-0 --show-browser

# By title substring (case-insensitive match)
python3 scripts/run.py chatgpt.py --get-chat "quantum entanglement" --show-browser

# Raw output (role-tagged messages, good for piping)
python3 scripts/run.py chatgpt.py --get-chat idx-0 --raw

# JSON output with full metadata
python3 scripts/run.py chatgpt.py --get-chat idx-0 --json
```

### Search Conversations
```bash
# Search chats by keyword (uses Cmd+K search dialog)
python3 scripts/run.py chatgpt.py --search-chats "quantum" --show-browser
python3 scripts/run.py chatgpt.py --search-chats "database schema" --json
```

### Projects
```bash
# List all ChatGPT Projects
python3 scripts/run.py chatgpt.py --list-projects --show-browser

# Send prompt within a project context
python3 scripts/run.py chatgpt.py --project "OmniModel" --prompt "Summarize this project"
python3 scripts/run.py chatgpt.py --project "CS Tutor" --prompt "Explain recursion" --json
```

### Export Conversations
```bash
# Export as markdown (default)
python3 scripts/run.py chatgpt.py --export idx-0

# Export as JSON
python3 scripts/run.py chatgpt.py --export "quantum" --format json > chat.json

# Export as plain text
python3 scripts/run.py chatgpt.py --export idx-3 --format txt
```

### Delete and Archive Conversations
```bash
# Delete a conversation (with confirmation)
python3 scripts/run.py chatgpt.py --delete-chat idx-5 --show-browser

# Archive a conversation
python3 scripts/run.py chatgpt.py --archive-chat "old project" --show-browser

# With JSON output for scripting
python3 scripts/run.py chatgpt.py --delete-chat "test chat" --json
```

### Code Extraction
```bash
# Extract only code blocks from response (strips markdown)
python3 scripts/run.py chatgpt.py --prompt "Write a Python quicksort" --code-only

# Code-only with JSON (includes code_blocks array)
python3 scripts/run.py chatgpt.py --prompt "Write a bash script" --code-only --json
```

### File Upload
```bash
# Upload a file for analysis
python3 scripts/run.py chatgpt.py --prompt "Summarize this file" --file report.pdf --show-browser

# Upload code for review
python3 scripts/run.py chatgpt.py --prompt "Review this code" --file main.py --show-browser

# Upload multiple files
python3 scripts/run.py chatgpt.py --prompt "Compare these" --file a.py --file b.py --show-browser
```

### Image Upload (Vision)
```bash
# Describe an image
python3 scripts/run.py chatgpt.py --prompt "What's in this image?" --image photo.jpg --show-browser

# Analyze a screenshot
python3 scripts/run.py chatgpt.py --prompt "Find the bug in this UI" --image screenshot.png --show-browser

# Mix files and images
python3 scripts/run.py chatgpt.py --prompt "Does this code match this diagram?" --file code.py --image diagram.png --show-browser
```

### Temporary Chat
```bash
# Temporary chat (not saved to history)
python3 scripts/run.py chatgpt.py --prompt "One-off question" --temp-chat
```

> **Note**: `--search`/`--no-search` flags are accepted but have no effect — ChatGPT removed the manual web search toggle in Feb 2026. GPT-5.2 Auto mode decides whether to search automatically.

### Diagnostics
```bash
# Run DOM diagnostic tool to verify selectors against current ChatGPT UI
python3 scripts/run.py dom_debug.py

# With custom timeout for slow connections
python3 scripts/run.py dom_debug.py --timeout 30
```

## Script Reference

### `chatgpt.py` - Main Interface
```bash
python3 scripts/run.py chatgpt.py <mode> [options]

Modes (mutually exclusive, one required):
  --prompt, -p TEXT         Send a prompt to ChatGPT
  --list-chats              List recent conversations from sidebar
  --get-chat ID             Retrieve a conversation (by ID, index, or title)
  --search-chats QUERY      Search conversations by keyword
  --list-projects           List ChatGPT Projects from sidebar
  --export ID               Export conversation as md/json/txt
  --delete-chat ID          Delete a conversation
  --archive-chat ID         Archive a conversation
  --continue-chat ID        Send prompt in existing chat (by idx-N, title, or UUID)
  --new-chat                Force a fresh conversation before sending prompt

Options:
  --model, -m        Model: auto, instant, thinking, pro, o3, gpt-4.5 (default: auto)
  --file PATH        Upload file(s) with prompt (repeatable: --file a.py --file b.py)
  --image PATH       Upload image(s) for vision (repeatable: --image a.png --image b.jpg)
  --timeout, -t      Response timeout in seconds (default: model-dependent)
  --screenshot       Save screenshot to this path
  --show-browser     Show browser window (recommended for first use)
  --headless         Run in headless mode (may be blocked)
  --json             Output full JSON response with metadata
  --raw              Output only response text (no formatting)
  --code-only        Extract only fenced code blocks from response
  --format, -f       Export format: md, json, txt (default: md, for --export)
  --project NAME     Send prompt within a project context
  --temp-chat        Temporary chat mode (not saved to history)
  --search           Enable web search for this prompt
  --no-search        Disable web search for this prompt
  --session-id       Unique ID for concurrent queries
  --limit N          Max chats to list (default: 50, for --list-chats)
  --engine ENGINE    Browser engine: nodriver (default) or camoufox
  --verbose, -v      Enable debug logging to stderr
```

### `dom_debug.py` - DOM Diagnostic Tool
```bash
python3 scripts/run.py dom_debug.py [--timeout N]

Inspects the live ChatGPT DOM to verify CSS selectors are working.
Tests: sidebar links, input field, send button, response containers, model selector.
Sends "Hello" test prompt and saves screenshot to /tmp/chatgpt-dom-debug.png.
```

## Model Reference

### GPT-5.2 Thinking Modes (primary)
| Model | Timeout | Use Case |
|-------|---------|----------|
| `auto` | 2 min | ChatGPT decides how long to think (default) |
| `instant` | 1 min | Answers right away, no thinking overhead |
| `thinking` | 5 min | Thinks longer for better answers |
| `pro` | 30 min | Research-grade intelligence, extended reasoning |

### Legacy Models (behind submenu)
| Model | Timeout | Use Case |
|-------|---------|----------|
| `o3` | 10 min | OpenAI's reasoning model |
| `gpt-4.5` | 2 min | GPT-4.5 |
| `gpt-5.1-pro` | 30 min | GPT-5.1 Pro reasoning |
| `gpt-5.1-thinking` | 5 min | GPT-5.1 Thinking |
| `gpt-5.1-instant` | 1 min | GPT-5.1 Instant |
| `gpt-5-pro` | 30 min | GPT-5 Pro |
| `gpt-5-mini` | 5 min | GPT-5 Thinking mini |

> **Note**: GPT-4o and o3-mini have been removed from ChatGPT (Feb 2026).

## Output Formats

### Default (formatted)
```
============================================================
Prompt: What is the capital of France?
Model: GPT-5.2 Pro
Thinking time: 3s
Total time: 8s
Tokens: ~25 (response: 20)
============================================================

The capital of France is Paris.

============================================================
```

### JSON (`--json`)
```json
{
  "success": true,
  "response": "The capital of France is Paris.",
  "prompt": "What is the capital of France?",
  "model": "GPT-5.2 Pro",
  "thinking_time_seconds": 3,
  "total_time_seconds": 8,
  "cookies_used": 15,
  "tokens": {
    "response": 20,
    "prompt": 8,
    "total": 28
  }
}
```

### Raw (`--raw`)
```
The capital of France is Paris.
```

## Integration with Claude Code

Use this skill when Claude Code needs:
- A second opinion from a different AI model
- Extended reasoning capabilities (GPT-5.2 Pro can think for 30 minutes)
- OpenAI-specific capabilities or knowledge
- Following up on a previous ChatGPT conversation
- GPT-5.2 vision to analyze images, screenshots, or diagrams
- File analysis with a different model's perspective

Example workflow in Claude Code:
```bash
# Get GPT-5.2 Pro's analysis of a complex problem
cd ~/.claude/skills/chatgpt-cli
python3 scripts/run.py chatgpt.py \
  --prompt "$(cat <<'EOF'
Analyze this database schema for potential issues:
[schema here]
Consider: normalization, indexing, scalability, and query patterns.
EOF
)" \
  --model pro \
  --json

# Continue a previous ChatGPT conversation with follow-up
python3 scripts/run.py chatgpt.py \
  --continue-chat "database schema" \
  --prompt "What about adding an index on the created_at column?" \
  --json
```

## Environment Management

The virtual environment is automatically managed:
- First run creates `.venv` automatically
- Dependencies install automatically
- Everything isolated in skill directory

Manual setup (only if automatic fails):
```bash
cd ~/.claude/skills/chatgpt-cli
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Data Storage

All data stored in `~/.claude/skills/chatgpt-cli/data/`:
- `screenshots/` - Saved screenshots
- `browser_profile/` - Browser state for stealth
- `.chrome_key_cache` - Cached Chrome encryption key

## Configuration

Optional `.env` file:
```env
HEADLESS=false             # Default browser visibility
DEFAULT_TIMEOUT=300        # Response timeout (seconds)
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cloudflare challenge detected" | Use `--show-browser` flag |
| "Cookie extraction failed" | Login to ChatGPT in Chrome |
| "Not logged in" | Re-login to ChatGPT in Chrome |
| "Rate limit reached" | Wait for reset or use different model |
| "Could not find input field" | ChatGPT UI may have changed, check for updates |
| "Timeout waiting for response" | Increase `--timeout`, reasoning may need more time |
| ModuleNotFoundError | Use `run.py` wrapper |

## Limitations

- **macOS only** - Cookie decryption uses macOS Keychain
- **--show-browser recommended** - Cloudflare may block headless mode
- **ChatGPT Pro/Plus required** - For GPT-5.2 Pro and some legacy models
- **Rate limits apply** - Varies by subscription tier
- **`--search`/`--no-search` deprecated** - Web search toggle removed from ChatGPT UI (Feb 2026); GPT-5.2 auto-searches
- Conversation retrieval depends on sidebar rendering (may need scrolling for older chats)

## How It Works

1. **Cookie Extraction**: Reads ChatGPT cookies from Chrome's database (shared extractor at `~/.claude/skills/shared/chrome_cookies.py`)
2. **Decryption**: Decrypts encrypted cookie values using macOS Keychain
3. **Stealth Browser**: Launches via shared engine abstraction (`~/.claude/skills/shared/browser_engine.py`) — nodriver (Chromium, default) or camoufox (Firefox + fingerprint spoofing) via `--engine` flag
4. **Cookie Injection**: Sets cookies via CDP (nodriver) or Playwright context (camoufox)
5. **Navigation**: Opens ChatGPT (or navigates to existing chat for `--continue-chat`)
6. **Model Selection**: Selects model via `data-testid`-based CDP mouse events (React requires full `mouseMoved → mousePressed → mouseReleased` sequence)
7. **File Upload** (if `--file`/`--image`): Intercepts file chooser via CDP, triggers ⌘U shortcut, sets files on the exact input element React opened via `DOM.setFileInputFiles` with `backend_node_id`
8. **Interaction**: Types prompt via ProseMirror editor, clicks send
9. **Response Polling**: Monitors for stop button disappearance and text stability
10. **Extraction**: Returns stabilized response text
