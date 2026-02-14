#!/usr/bin/env python3
"""
Configuration for ChatGPT CLI skill
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
SKILL_DIR = Path(__file__).parent.parent
load_dotenv(SKILL_DIR / ".env")

# Data directories
DATA_DIR = SKILL_DIR / "data"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
USER_DATA_DIR = DATA_DIR / "browser_profile"

# Create directories
DATA_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR.mkdir(exist_ok=True)
USER_DATA_DIR.mkdir(exist_ok=True)


def clean_browser_locks():
    """Remove stale Chrome singleton locks left by crashed/killed browser processes."""
    for name in ('SingletonLock', 'SingletonSocket', 'SingletonCookie'):
        lock = USER_DATA_DIR / name
        if lock.exists() or lock.is_symlink():
            try:
                lock.unlink()
            except OSError:
                pass


# Browser settings
HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"  # Default to visible for Cloudflare
DEFAULT_TIMEOUT = int(os.getenv("DEFAULT_TIMEOUT", "300"))  # 5 min default for reasoning models

# Browser args for stealth
BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--remote-debugging-port=9234",
]

# ChatGPT URL
CHATGPT_URL = "https://chatgpt.com"

# Cookie domains to extract for authentication
CHATGPT_COOKIE_DOMAINS = [
    "chatgpt.com",
    ".chatgpt.com",
    "auth0.openai.com",
    ".auth0.openai.com",
    "openai.com",
    ".openai.com",
]

# Input field selectors for ChatGPT
# ChatGPT uses ProseMirror editor - a contenteditable div, not a textarea
CHATGPT_INPUT_SELECTORS = [
    # ProseMirror editor (primary - ChatGPT's main input)
    'div#prompt-textarea[contenteditable="true"]',
    'div[data-testid="prompt-textarea"]',
    'div.ProseMirror[contenteditable="true"]',
    # Fallback selectors
    'textarea[placeholder*="Message"]',
    'textarea[placeholder*="ChatGPT"]',
    'div[contenteditable="true"][data-placeholder*="Message"]',
    'div[contenteditable="true"][aria-label*="Message"]',
]

# Send button selectors
CHATGPT_SEND_SELECTORS = [
    'button[data-testid="send-button"]',
    'button[aria-label="Send prompt"]',
    'button[aria-label="Send"]',
    'button.send-button',
    # Voice/attach button area often contains send
    'form button[type="submit"]',
]

# Response container selectors
CHATGPT_RESPONSE_SELECTORS = [
    'div[data-message-author-role="assistant"]',
    'div.agent-turn',
    'div[data-testid="conversation-turn-*"]',
    'div.markdown',
]

# Thinking/reasoning indicators
CHATGPT_THINKING_INDICATORS = [
    "Thinking",
    "Reasoning",
    "Thought for",
    "seconds thinking",
]

# Stop generation button (indicates response in progress)
CHATGPT_STOP_SELECTORS = [
    'button[data-testid="stop-button"]',
    'button[aria-label="Stop generating"]',
    'button.stop-button',
]

# Model selector (actual data-testid discovered via DOM probing 2026-02-13)
CHATGPT_MODEL_SELECTOR = 'button[data-testid="model-switcher-dropdown-button"]'

# ChatGPT model dropdown structure (verified 2026-02-13):
# Primary: GPT-5.2 with 4 thinking modes (Auto, Instant, Thinking, Pro)
# Legacy: Behind "Legacy models" submenu (GPT-5.1, GPT-5, GPT-4.5, o3)
#
# Selection uses data-testid attributes for reliable targeting.

CHATGPT_MODELS = {
    # GPT-5.2 thinking modes (primary)
    "auto": "GPT-5.2 Auto",
    "instant": "GPT-5.2 Instant",
    "thinking": "GPT-5.2 Thinking",
    "pro": "GPT-5.2 Pro",
    # Legacy models (behind submenu)
    "o3": "o3",
    "gpt-4.5": "GPT-4.5",
    "gpt-5.1-instant": "GPT-5.1 Instant",
    "gpt-5.1-thinking": "GPT-5.1 Thinking",
    "gpt-5.1-pro": "GPT-5.1 Pro",
    "gpt-5-mini": "GPT-5 Thinking mini",
    "gpt-5-pro": "GPT-5 Pro",
}

# data-testid for each model in the dropdown (reliable CSS selector)
CHATGPT_MODEL_TESTIDS = {
    "auto": "model-switcher-gpt-5-2",
    "instant": "model-switcher-gpt-5-2-instant",
    "thinking": "model-switcher-gpt-5-2-thinking",
    "pro": "model-switcher-gpt-5-2-pro",
    "o3": "model-switcher-o3",
    "gpt-4.5": "model-switcher-gpt-4-5",
    "gpt-5.1-instant": "model-switcher-gpt-5-1-instant",
    "gpt-5.1-thinking": "model-switcher-gpt-5-1-thinking",
    "gpt-5.1-pro": "model-switcher-gpt-5-1-pro",
    "gpt-5-mini": "model-switcher-gpt-5-t-mini",
    "gpt-5-pro": "model-switcher-gpt-5-pro",
}

# Models that require opening the "Legacy models" submenu first
CHATGPT_LEGACY_MODELS = {
    "o3", "gpt-4.5",
    "gpt-5.1-instant", "gpt-5.1-thinking", "gpt-5.1-pro",
    "gpt-5-mini", "gpt-5-pro",
}
CHATGPT_LEGACY_SUBMENU_TESTID = "Legacy models-submenu"

DEFAULT_MODEL = "auto"

# Timeout presets per model (seconds)
MODEL_TIMEOUTS = {
    "auto": 120,
    "instant": 60,
    "thinking": 300,
    "pro": 1800,      # 30 minutes for extended reasoning
    "o3": 600,
    "gpt-4.5": 120,
    "gpt-5.1-instant": 60,
    "gpt-5.1-thinking": 300,
    "gpt-5.1-pro": 1800,
    "gpt-5-mini": 300,
    "gpt-5-pro": 1800,
}

# Sidebar / chat history selectors
CHATGPT_SIDEBAR_SELECTORS = [
    'nav ol li a[href*="/c/"]',       # Primary: chat links in sidebar nav
    'nav a[href*="/c/"]',             # Broader: any nav chat link
    '[class*="conversation-list"] a',  # Fallback: conversation list container
]

# Chat message turn selectors (for extracting conversation history)
CHATGPT_CHAT_MESSAGE_SELECTORS = [
    'div[data-message-author-role]',                # Primary: role-tagged messages
    'div[data-message-author-role="assistant"]',     # Assistant-only
    'div[data-message-author-role="user"]',          # User-only
    'article[data-testid*="conversation-turn"]',     # Article-based turns
    '.agent-turn',                                    # Agent turn class
]

# Chat URL pattern
CHATGPT_CHAT_URL = "https://chatgpt.com/c/{chat_id}"

# Response polling settings
POLL_INTERVAL = 1.0  # seconds between checks
STABILITY_THRESHOLD = 3  # consecutive stable polls before considering response complete
