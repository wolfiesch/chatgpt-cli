#!/usr/bin/env python3
"""
ChatGPT API Client — Direct HTTP calls, no browser needed.

Uses Chrome cookies for authentication, hitting the same backend-api
endpoints that the ChatGPT web app uses internally. This is 10-100x
faster than browser mode since it skips browser startup, Cloudflare,
DOM interaction, and response polling.

Auth flow:
  1. Extract cookies from Chrome (chrome_cookies.py)
  2. GET /api/auth/session → access token (JWT)
  3. POST /backend-api/conversation → SSE stream of response chunks
"""

import base64
import hashlib
import json
import random
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from config import CHATGPT_URL, MODEL_TIMEOUTS, DEFAULT_TIMEOUT


# ── Endpoints ────────────────────────────────────────────────────────

AUTH_SESSION_URL = f"{CHATGPT_URL}/api/auth/session"
CONVERSATION_URL = f"{CHATGPT_URL}/backend-api/conversation"
MODELS_URL = f"{CHATGPT_URL}/backend-api/models"
REQUIREMENTS_URL = f"{CHATGPT_URL}/backend-api/sentinel/chat-requirements"

# ── Model slug mapping ───────────────────────────────────────────────
# The backend API uses model "slugs" that differ from the UI names.
# These are discovered by inspecting real network requests.
# The mapping may need updating as OpenAI changes model availability.

API_MODEL_SLUGS = {
    # GPT-5.2 thinking modes
    "auto": "auto",
    "instant": "gpt-5.2-instant",
    "thinking": "gpt-5.2",
    "pro": "gpt-5.2-pro",
    # Legacy models
    "o3": "o3",
    "gpt-4.5": "gpt-4.5",
    "gpt-5.1-instant": "gpt-5.1-instant",
    "gpt-5.1-thinking": "gpt-5.1",
    "gpt-5.1-pro": "gpt-5.1-pro",
    "gpt-5-mini": "gpt-5-t-mini",
    "gpt-5-pro": "gpt-5-pro",
}

# ── User-Agent ───────────────────────────────────────────────────────
# Match a real Chrome browser to avoid fingerprint-based blocking.

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _log(msg: str, verbose: bool) -> None:
    if verbose:
        print(f"[chatgpt-api] {msg}", file=sys.stderr)


# ── Cookie helpers ───────────────────────────────────────────────────

def build_cookie_header(cookies: list[dict]) -> str:
    """Build Cookie header string from extracted cookie dicts."""
    return "; ".join(
        f"{c['name']}={c['value']}"
        for c in cookies
        if c.get("value") and c.get("name")
    )


def _find_cookie(cookies: list[dict], name: str) -> Optional[str]:
    """Find a specific cookie value by name."""
    for c in cookies:
        if c.get("name") == name:
            return c.get("value")
    return None


def _base_headers(cookie_header: str) -> dict:
    """Common headers for all ChatGPT API requests."""
    return {
        "Cookie": cookie_header,
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": CHATGPT_URL,
        "Referer": f"{CHATGPT_URL}/",
    }


# ── Auth ─────────────────────────────────────────────────────────────

async def get_access_token(
    cookies: list[dict],
    verbose: bool = False,
) -> dict:
    """
    Get access token from ChatGPT session endpoint.

    Hits GET /api/auth/session with cookies. Returns a dict with
    'accessToken' (JWT), 'user' info, and 'expires'.

    Returns:
        dict with 'success' and either 'access_token' or 'error'.
    """
    cookie_header = build_cookie_header(cookies)
    headers = _base_headers(cookie_header)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            _log(f"auth: GET {AUTH_SESSION_URL}", verbose)
            resp = await client.get(AUTH_SESSION_URL, headers=headers)

            if resp.status_code != 200:
                _log(f"auth: HTTP {resp.status_code}", verbose)
                return {
                    "success": False,
                    "error": f"Auth session returned {resp.status_code}",
                    "status_code": resp.status_code,
                }

            data = resp.json()
            access_token = data.get("accessToken")

            if not access_token:
                _log(f"auth: no accessToken in response. Keys: {list(data.keys())}", verbose)
                return {
                    "success": False,
                    "error": "No accessToken in session response. Cookies may be expired.",
                }

            _log(f"auth: got access token ({len(access_token)} chars)", verbose)
            return {
                "success": True,
                "access_token": access_token,
                "user": data.get("user", {}),
                "expires": data.get("expires"),
            }

    except httpx.TimeoutException:
        return {"success": False, "error": "Auth session request timed out"}
    except Exception as e:
        return {"success": False, "error": f"Auth error: {e}"}


# ── Proof-of-Work solver ──────────────────────────────────────────────

# Browser environment values for the PoW config array.
# These mimic what ChatGPT's JS collects from navigator/window/document.
# The server validates the hash, not individual config values.

_POW_CORES = [8, 12, 16, 24, 32]
_POW_SCREENS = [1920 + 1080, 2560 + 1440, 1920 + 1200, 2560 + 1600]
_POW_MAX_ITERATIONS = 500_000


def _pow_parse_time() -> str:
    """Format current time like JS Date.toString() in EST."""
    now = datetime.now(timezone(timedelta(hours=-5)))
    return now.strftime("%a %b %d %Y %H:%M:%S") + " GMT-0500 (Eastern Standard Time)"


def _pow_config(user_agent: str) -> list:
    """Build a config array mimicking browser environment fingerprint."""
    return [
        random.choice(_POW_SCREENS),       # screen width+height
        _pow_parse_time(),                  # JS-style timestamp
        4294705152,                         # performance constant
        0,                                  # counter slot (replaced per iteration)
        user_agent,                         # navigator.userAgent
        "",                                 # cached script hash (optional)
        "",                                 # deployment ID (optional)
        "en-US",                            # navigator.language
        "en-US,en;q=0.9",                   # navigator.languages
        0,                                  # counter slot 2 (replaced per iteration)
        random.choice(_POW_CORES),          # hardwareConcurrency
        time.perf_counter() * 1000,         # performance.now()
        str(uuid.uuid4()),                  # random UUID
        "",                                 # additional fingerprint (optional)
        time.time() * 1000 - (time.perf_counter() * 1000),  # Date.now() - performance.now()
    ]


def solve_proof_of_work(
    seed: str,
    difficulty: str,
    user_agent: str | None = None,
    verbose: bool = False,
) -> str | None:
    """
    Solve ChatGPT's SHA3-512 proof-of-work challenge.

    The algorithm:
      1. Build a config array mimicking browser environment
      2. For each iteration i: inject i into config, base64-encode, hash
      3. SHA3-512(seed + base64(config)), check if prefix ≤ difficulty
      4. Return "gAAAAAB" + base64(winning config)

    Args:
        seed: Challenge seed from sentinel endpoint.
        difficulty: Hex difficulty threshold (e.g. "073bcd").
        user_agent: Browser user agent string.
        verbose: Debug logging.

    Returns:
        PoW token string, or None if unsolved after max iterations.
    """
    if not user_agent:
        user_agent = USER_AGENT

    config = _pow_config(user_agent)
    target = bytes.fromhex(difficulty)
    target_len = len(target)
    seed_bytes = seed.encode()

    # Pre-build static parts of the JSON config for speed.
    # config has 15 elements: slots 3 and 9 are dynamic counters.
    part1 = (json.dumps(config[:3], separators=(',', ':'), ensure_ascii=False)[:-1] + ',').encode()
    part2 = (',' + json.dumps(config[4:9], separators=(',', ':'), ensure_ascii=False)[1:-1] + ',').encode()
    part3 = (',' + json.dumps(config[10:], separators=(',', ':'), ensure_ascii=False)[1:]).encode()

    for i in range(_POW_MAX_ITERATIONS):
        # Inject iteration counter into config slots 3 and 9
        i_bytes = str(i).encode()
        j_bytes = str(i >> 1).encode()

        config_json = part1 + i_bytes + part2 + j_bytes + part3
        config_b64 = base64.b64encode(config_json)

        digest = hashlib.sha3_512(seed_bytes + config_b64).digest()
        if digest[:target_len] <= target:
            _log(f"pow: solved in {i + 1} iterations", verbose)
            return "gAAAAAB" + config_b64.decode()

    _log(f"pow: FAILED after {_POW_MAX_ITERATIONS} iterations", verbose)
    return None


# ── Chat requirements (anti-bot sentinel) ────────────────────────────

async def get_chat_requirements(
    access_token: str,
    cookies: list[dict],
    verbose: bool = False,
) -> dict:
    """
    Get chat requirements token from sentinel endpoint.

    Some accounts (especially free) require a proof-of-work token.
    Paid accounts may get a simple passthrough token.

    Returns:
        dict with 'token' and optionally 'proofofwork' params.
    """
    cookie_header = build_cookie_header(cookies)
    headers = _base_headers(cookie_header)
    headers["Authorization"] = f"Bearer {access_token}"
    headers["Content-Type"] = "application/json"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            _log(f"sentinel: POST {REQUIREMENTS_URL}", verbose)
            resp = await client.post(
                REQUIREMENTS_URL,
                headers=headers,
                json={},
            )

            if resp.status_code != 200:
                _log(f"sentinel: HTTP {resp.status_code}", verbose)
                return {"success": False, "status_code": resp.status_code}

            data = resp.json()
            _log(f"sentinel: persona={data.get('persona')}, pow_required={data.get('proofofwork', {}).get('required')}", verbose)
            return {
                "success": True,
                "token": data.get("token"),
                "persona": data.get("persona"),
                "proofofwork": data.get("proofofwork"),
            }

    except Exception as e:
        _log(f"sentinel: error {e}", verbose)
        return {"success": False, "error": str(e)}


# ── Conversation ─────────────────────────────────────────────────────

async def prompt_chatgpt_api(
    prompt: str,
    model: str,
    cookies: list[dict],
    access_token: str,
    timeout: int | None = None,
    conversation_id: str | None = None,
    parent_message_id: str | None = None,
    requirements_token: str | None = None,
    proof_token: str | None = None,
    verbose: bool = False,
) -> dict:
    """
    Send a prompt to ChatGPT via the backend API.

    Streams the response via Server-Sent Events (SSE). Each SSE event
    contains a JSON object with the full message so far (not deltas).
    We accumulate the final text from the last event before [DONE].

    Args:
        prompt: The user message.
        model: CLI model key (e.g. "auto", "thinking", "pro").
        cookies: Extracted Chrome cookies.
        access_token: JWT from get_access_token().
        timeout: Response timeout in seconds.
        conversation_id: Continue existing conversation.
        parent_message_id: Parent message for threading.
        requirements_token: Token from sentinel endpoint.
        proof_token: Proof-of-work solution token.
        verbose: Debug logging.

    Returns:
        dict matching browser mode's return format.
    """
    if timeout is None:
        timeout = MODEL_TIMEOUTS.get(model, DEFAULT_TIMEOUT)

    cookie_header = build_cookie_header(cookies)
    message_id = str(uuid.uuid4())
    if not parent_message_id:
        parent_message_id = str(uuid.uuid4())

    # Build payload
    model_slug = API_MODEL_SLUGS.get(model, model)
    payload = {
        "action": "next",
        "messages": [{
            "id": message_id,
            "author": {"role": "user"},
            "content": {
                "content_type": "text",
                "parts": [prompt],
            },
        }],
        "model": model_slug,
        "parent_message_id": parent_message_id,
        "timezone_offset_min": -480,
        "conversation_mode": {"kind": "primary_assistant"},
        "force_paragen": False,
        "force_rate_limit": False,
    }

    if conversation_id:
        payload["conversation_id"] = conversation_id

    # Build headers
    headers = _base_headers(cookie_header)
    headers["Authorization"] = f"Bearer {access_token}"
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "text/event-stream"

    if requirements_token:
        headers["openai-sentinel-chat-requirements-token"] = requirements_token
    if proof_token:
        headers["openai-sentinel-proof-token"] = proof_token

    _log(f"conversation: POST model={model_slug}, prompt={len(prompt)} chars", verbose)

    start_time = time.time()
    response_text = ""
    thinking_time = 0
    result_conversation_id = conversation_id

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=30.0),
        ) as client:
            async with client.stream(
                "POST",
                CONVERSATION_URL,
                json=payload,
                headers=headers,
            ) as resp:
                if resp.status_code == 401:
                    return {
                        "success": False,
                        "error": "Authentication expired. Re-extract cookies.",
                        "status_code": 401,
                    }

                if resp.status_code == 403:
                    error_body = (await resp.aread()).decode(errors="replace")
                    _log(f"conversation: 403 body: {error_body[:500]}", verbose)
                    return {
                        "success": False,
                        "error": f"Access denied (403). May need sentinel token or cookies expired. Body: {error_body[:200]}",
                        "status_code": 403,
                    }

                if resp.status_code == 429:
                    return {
                        "success": False,
                        "error": "Rate limit reached. Wait before trying again.",
                        "rate_limited": True,
                        "status_code": 429,
                    }

                if resp.status_code != 200:
                    error_body = (await resp.aread()).decode(errors="replace")
                    return {
                        "success": False,
                        "error": f"API error {resp.status_code}: {error_body[:500]}",
                        "status_code": resp.status_code,
                    }

                # Parse SSE stream
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue

                    data_str = line[6:]  # Strip "data: " prefix

                    if data_str == "[DONE]":
                        _log("conversation: [DONE]", verbose)
                        break

                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    # Extract message content
                    message = event.get("message", {})
                    content = message.get("content", {})
                    parts = content.get("parts", [])

                    if parts and isinstance(parts[0], str):
                        response_text = parts[0]

                    # Track conversation ID for follow-ups
                    if not result_conversation_id:
                        result_conversation_id = event.get("conversation_id")

                    # Extract thinking/reasoning time from metadata
                    metadata = message.get("metadata", {})
                    if metadata.get("is_reasoning"):
                        # Reasoning models report thinking time
                        thinking_secs = metadata.get("reasoning_duration")
                        if thinking_secs and isinstance(thinking_secs, (int, float)):
                            thinking_time = int(thinking_secs)

                    # Check for error in event
                    if event.get("error"):
                        error_info = event["error"]
                        error_msg = error_info if isinstance(error_info, str) else json.dumps(error_info)
                        return {
                            "success": False,
                            "error": f"ChatGPT error: {error_msg}",
                        }

    except httpx.TimeoutException:
        if response_text:
            _log("conversation: timeout but have partial response", verbose)
        else:
            return {
                "success": False,
                "error": f"Timeout after {timeout}s waiting for response",
            }
    except httpx.ConnectError as e:
        return {
            "success": False,
            "error": f"Connection failed: {e}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"API error: {e}",
        }

    total_time = int(time.time() - start_time)

    if not response_text:
        return {
            "success": False,
            "error": "Empty response from API",
        }

    response_tokens = max(1, len(response_text) // 4)
    prompt_tokens = max(1, len(prompt) // 4)

    return {
        "success": True,
        "response": response_text,
        "prompt": prompt,
        "model": model_slug,
        "mode": "api",
        "thinking_time_seconds": thinking_time if thinking_time > 0 else None,
        "total_time_seconds": total_time,
        "conversation_id": result_conversation_id,
        "tokens": {
            "response": response_tokens,
            "prompt": prompt_tokens,
            "total": response_tokens + prompt_tokens,
        },
    }


# ── High-level orchestrator ──────────────────────────────────────────

async def chatgpt_api_prompt(
    prompt: str,
    model: str = "auto",
    cookies: list[dict] | None = None,
    timeout: int | None = None,
    conversation_id: str | None = None,
    verbose: bool = False,
) -> dict:
    """
    Complete API-mode prompt flow: auth → requirements → conversation.

    This is the API-mode equivalent of prompt_chatgpt() in chatgpt.py.
    Returns the same dict format for drop-in compatibility.

    If cookies are not provided, extracts them from Chrome.
    """
    from chrome_cookies import extract_cookies as extract_chrome_cookies
    from config import CHATGPT_COOKIE_DOMAINS

    # Step 1: Extract cookies if not provided
    if cookies is None:
        _log("extracting cookies from Chrome...", verbose)
        result = extract_chrome_cookies(CHATGPT_COOKIE_DOMAINS, decrypt=True)
        if not result.get("success"):
            return {
                "success": False,
                "error": f"Cookie extraction failed: {result.get('error')}",
            }
        cookies = result.get("cookies", [])
        _log(f"extracted {len(cookies)} cookies", verbose)

    if not cookies:
        return {
            "success": False,
            "error": "No ChatGPT cookies found. Log into ChatGPT in Chrome first.",
        }

    # Step 2: Get access token
    auth = await get_access_token(cookies, verbose=verbose)
    if not auth["success"]:
        return {
            "success": False,
            "error": f"Auth failed: {auth.get('error')}",
        }

    access_token = auth["access_token"]

    # Step 3: Get chat requirements (sentinel token + PoW)
    requirements_token = None
    proof_token = None
    req = await get_chat_requirements(access_token, cookies, verbose=verbose)
    if req.get("success") and req.get("token"):
        requirements_token = req["token"]

        # Step 3b: Solve proof-of-work if required
        pow_info = req.get("proofofwork", {})
        if pow_info and pow_info.get("required"):
            seed = pow_info.get("seed", "")
            difficulty = pow_info.get("difficulty", "")
            _log(f"pow: solving challenge (seed={seed[:16]}..., difficulty={difficulty})", verbose)
            proof_token = solve_proof_of_work(seed, difficulty, verbose=verbose)
            if not proof_token:
                _log("pow: failed to solve, API mode may fail with 403", verbose)

    # Step 4: Send the conversation request
    result = await prompt_chatgpt_api(
        prompt=prompt,
        model=model,
        cookies=cookies,
        access_token=access_token,
        timeout=timeout,
        conversation_id=conversation_id,
        requirements_token=requirements_token,
        proof_token=proof_token,
        verbose=verbose,
    )

    # Add cookie count for diagnostics
    result["cookies_used"] = len(cookies)

    return result
