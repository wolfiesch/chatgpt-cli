# ChatGPT CLI

Query ChatGPT from the command line using your existing Chrome authentication. Supports GPT-5.2 with 4 thinking modes (Auto, Instant, Thinking, Pro) and legacy models (o3, GPT-4.5). Upload files for analysis and images for vision. Continue existing conversations, start fresh chats, search/export/delete/archive/rename/share history, use custom GPTs, generate images with DALL-E, manage memories, extract code blocks, and use temporary chats.

## Features

- **GPT-5.2 Thinking Modes**: Auto, Instant, Thinking, Pro — each with different reasoning depth
- **Legacy Models**: o3, GPT-4.5, GPT-5.1 variants behind a submenu
- **File Upload**: Send documents for analysis (`--file report.pdf`)
- **Image Upload**: GPT-5.2 vision for screenshots, diagrams, photos (`--image photo.jpg`)
- **Conversation Management**: List, search, continue, export, delete, archive, rename, share chats
- **Custom GPTs**: Route prompts to any custom GPT by name (`--gpt "CS Tutor"`)
- **Image Generation**: Generate images with DALL-E and download them (`--generate-image`)
- **Memory Management**: List ChatGPT's saved memories (`--list-memories`)
- **Code Extraction**: Pull just the code blocks from responses (`--code-only`)
- **Multiple Output Formats**: Formatted, JSON, raw text
- **Project Context**: Send prompts within ChatGPT Projects
- **Temporary Chat**: Ephemeral mode that doesn't save to history

## Prerequisites

- **macOS** (cookie decryption uses macOS Keychain)
- **Python 3.10+**
- **Chrome** with an active ChatGPT login session
- **ChatGPT Plus/Pro** subscription (required for GPT-5.2 Pro; optional for other models)

## Installation

```bash
git clone https://github.com/wolfiesch/chatgpt-cli.git
cd chatgpt-cli
```

The virtual environment and dependencies are set up automatically on first run. If auto-setup fails:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Quick Start

```bash
# Check version
python3 scripts/run.py --version

# Basic query (GPT-5.2 Auto mode)
python3 scripts/run.py chatgpt.py --prompt "Explain quantum entanglement" --show-browser

# Use specific thinking mode
python3 scripts/run.py chatgpt.py --prompt "Prove this theorem" --model pro

# Upload a file for analysis
python3 scripts/run.py chatgpt.py --prompt "Review this code" --file main.py --show-browser

# Upload an image for vision
python3 scripts/run.py chatgpt.py --prompt "What's in this image?" --image photo.jpg --show-browser
```

> **Important**: Always use `python3 scripts/run.py` as the entry point — it manages the virtual environment automatically.

## Usage

### Sending Prompts

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

### Conversation Management

```bash
# List recent conversations
python3 scripts/run.py chatgpt.py --list-chats --show-browser

# Continue an existing conversation (by index, title, or UUID)
python3 scripts/run.py chatgpt.py --continue-chat idx-0 --prompt "Follow up on that"
python3 scripts/run.py chatgpt.py --continue-chat "quantum" --prompt "What about entanglement?"

# Start a fresh conversation
python3 scripts/run.py chatgpt.py --new-chat --prompt "Start fresh: explain relativity"

# Search conversations
python3 scripts/run.py chatgpt.py --search-chats "database schema" --json

# Export a conversation
python3 scripts/run.py chatgpt.py --export idx-0 --format json > chat.json
```

### File & Image Upload

```bash
# Upload files for analysis
python3 scripts/run.py chatgpt.py --prompt "Summarize this" --file report.pdf --show-browser

# Upload multiple files
python3 scripts/run.py chatgpt.py --prompt "Compare these" --file a.py --file b.py --show-browser

# Upload images for vision
python3 scripts/run.py chatgpt.py --prompt "Describe this" --image photo.jpg --show-browser

# Mix files and images
python3 scripts/run.py chatgpt.py --prompt "Does this code match this diagram?" \
  --file code.py --image diagram.png --show-browser
```

### Output Options

```bash
# JSON output for parsing
python3 scripts/run.py chatgpt.py --prompt "Quick question" --json

# Raw text (for piping)
python3 scripts/run.py chatgpt.py --prompt "Capital of France?" --raw

# Extract only code blocks
python3 scripts/run.py chatgpt.py --prompt "Write a Python quicksort" --code-only

# Save screenshot
python3 scripts/run.py chatgpt.py --prompt "Design a system" --screenshot /tmp/chatgpt.png

# Temporary chat (not saved to history)
python3 scripts/run.py chatgpt.py --prompt "One-off question" --temp-chat
```

### Custom GPTs

```bash
# Send prompt to a custom GPT by name (fuzzy match)
python3 scripts/run.py chatgpt.py --gpt "CS Tutor" --prompt "Explain recursion" --show-browser

# Custom GPT with a specific thinking mode
python3 scripts/run.py chatgpt.py --gpt "Code Reviewer" --prompt "Review this function" --model thinking
```

### Rename, Share & Memories

```bash
# Rename a conversation
python3 scripts/run.py chatgpt.py --rename-chat idx-0 --new-name "Quantum Physics Notes" --show-browser

# Generate a shareable link for a conversation
python3 scripts/run.py chatgpt.py --share idx-0 --show-browser

# List ChatGPT's saved memories
python3 scripts/run.py chatgpt.py --list-memories --show-browser --json
```

### Image Generation

```bash
# Generate an image with DALL-E
python3 scripts/run.py chatgpt.py --generate-image "A sunset over mountains in watercolor style" --show-browser

# Generate and download to a specific directory
python3 scripts/run.py chatgpt.py --generate-image "Logo for a coffee shop" --output /tmp/images --show-browser
```

### Projects

```bash
# List ChatGPT Projects
python3 scripts/run.py chatgpt.py --list-projects --show-browser

# Send prompt within a project
python3 scripts/run.py chatgpt.py --project "CS Tutor" --prompt "Explain recursion"
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

## CLI Reference

```
python3 scripts/run.py chatgpt.py <mode> [options]

Global:
  --version, -V           Show version and exit
  --help, -h              Show help and exit

Modes (mutually exclusive, one required):
  --prompt, -p TEXT         Send a prompt to ChatGPT
  --list-chats              List recent conversations from sidebar
  --get-chat ID             Retrieve a conversation (by ID, index, or title)
  --search-chats QUERY      Search conversations by keyword
  --list-projects           List ChatGPT Projects from sidebar
  --export ID               Export conversation as md/json/txt
  --delete-chat ID          Delete a conversation
  --archive-chat ID         Archive a conversation
  --rename-chat ID          Rename a conversation (requires --new-name)
  --share ID                Generate a shareable link for a conversation
  --list-memories           List ChatGPT's saved memories
  --generate-image PROMPT   Generate an image with DALL-E and download it
  --continue-chat ID        Send prompt in existing chat (by idx-N, title, or UUID)
  --new-chat                Force a fresh conversation before sending prompt

Options:
  --model, -m        Model: auto, instant, thinking, pro, o3, gpt-4.5 (default: auto)
  --file PATH        Upload file(s) with prompt (repeatable)
  --image PATH       Upload image(s) for vision (repeatable)
  --gpt NAME         Use a custom GPT by name (fuzzy match)
  --new-name NAME    New name for --rename-chat
  --output, -o DIR   Output directory for --generate-image downloads
  --timeout, -t      Response timeout in seconds (default: model-dependent)
  --screenshot       Save screenshot to this path
  --show-browser     Show browser window (recommended for first use)
  --headless         Run in headless mode (may be blocked by Cloudflare)
  --json             Output full JSON response with metadata
  --raw              Output only response text (no formatting)
  --code-only        Extract only fenced code blocks from response
  --format, -f       Export format: md, json, txt (default: md)
  --project NAME     Send prompt within a project context
  --temp-chat        Temporary chat mode (not saved to history)
  --session-id       Unique ID for concurrent queries
  --limit N          Max chats to list (default: 50)
  --engine ENGINE    Browser engine: nodriver (default) or camoufox
  --verbose, -v      Enable debug logging to stderr
```

## How It Works

1. **Cookie Extraction** — Reads ChatGPT session cookies from Chrome's SQLite database
2. **Decryption** — Decrypts encrypted cookie values using macOS Keychain
3. **Stealth Browser** — Launches nodriver (undetected Chrome) to bypass Cloudflare
4. **Cookie Injection** — Sets cookies via Chrome DevTools Protocol (CDP)
5. **Navigation** — Opens ChatGPT (or navigates to an existing conversation)
6. **Model Selection** — Selects model via `data-testid`-based CDP mouse events
7. **File Upload** — Intercepts file chooser via CDP, triggers keyboard shortcut, sets files via `DOM.setFileInputFiles` with `backend_node_id`
8. **Prompt Input** — Types prompt via ProseMirror editor, clicks send
9. **Response Polling** — Monitors for stop button disappearance and text stability
10. **Extraction** — Returns the stabilized response text

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cloudflare challenge detected" | Use `--show-browser` flag |
| "Cookie extraction failed" | Login to ChatGPT in Chrome |
| "Not logged in" | Re-login to ChatGPT in Chrome |
| "Rate limit reached" | Wait for reset or use different model |
| "Could not find input field" | ChatGPT UI may have changed; run `dom_debug.py` |
| "Timeout waiting for response" | Increase `--timeout`; reasoning may need more time |
| ModuleNotFoundError | Use `run.py` wrapper instead of calling scripts directly |

## Limitations

- **macOS only** — Cookie decryption uses macOS Keychain
- **`--show-browser` recommended** — Cloudflare may block headless mode
- **ChatGPT Pro/Plus required** — For GPT-5.2 Pro and some legacy models
- **Rate limits apply** — Varies by subscription tier
- Conversation retrieval depends on sidebar rendering (may need scrolling for older chats)

## License

MIT
