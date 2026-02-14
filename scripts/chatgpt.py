#!/usr/bin/env python3
"""
ChatGPT CLI - Send prompts to ChatGPT and get responses.
Includes chat history browsing (list + retrieve).
Uses stealth browser with Chrome auth for authentication.
Supports reasoning models (GPT-5.2 Pro, o3) with extended thinking times.
"""

import asyncio
import argparse
import json
import re
import sys
import time
from pathlib import Path

import nodriver as uc
from nodriver import cdp


def _log(msg: str, verbose: bool) -> None:
    """Print debug message to stderr if verbose mode is enabled."""
    if verbose:
        print(f"[chatgpt] {msg}", file=sys.stderr)


def estimate_tokens(text: str) -> int:
    """
    Estimate token count for Claude/GPT models.
    Uses ~4 chars per token heuristic (accurate within 10-20% for English).
    """
    if not text:
        return 0
    return max(1, len(text) // 4)


from config import (
    HEADLESS, USER_DATA_DIR, BROWSER_ARGS, DEFAULT_TIMEOUT,
    CHATGPT_URL, CHATGPT_COOKIE_DOMAINS,
    CHATGPT_INPUT_SELECTORS, CHATGPT_SEND_SELECTORS, CHATGPT_RESPONSE_SELECTORS,
    CHATGPT_THINKING_INDICATORS, CHATGPT_STOP_SELECTORS, CHATGPT_MODEL_SELECTOR,
    CHATGPT_MODELS, CHATGPT_MODEL_TESTIDS, CHATGPT_LEGACY_MODELS,
    CHATGPT_LEGACY_SUBMENU_TESTID,
    DEFAULT_MODEL, MODEL_TIMEOUTS,
    CHATGPT_SIDEBAR_SELECTORS, CHATGPT_CHAT_MESSAGE_SELECTORS, CHATGPT_CHAT_URL,
    POLL_INTERVAL, STABILITY_THRESHOLD,
    clean_browser_locks,
)
from chrome_cookies import extract_cookies as extract_chrome_cookies


async def _cdp_eval(page, expression: str):
    """Run JavaScript on page via CDP Runtime.evaluate.

    nodriver's page.evaluate() silently returns None on chatgpt.com
    due to execution context issues. This uses the CDP protocol directly
    which works reliably. The expression is sent to the browser's existing
    JS context - not Python eval().
    """
    try:
        result, _exceptions = await page.send(cdp.runtime.evaluate(expression))
        if result and result.value is not None:
            return result.value
        # For complex objects (arrays, objects), serialize via JSON
        if result and result.object_id:
            props, _ = await page.send(
                cdp.runtime.call_function_on(
                    'function() { return JSON.stringify(this); }',
                    object_id=result.object_id,
                    return_by_value=True,
                )
            )
            if props and props.value:
                return json.loads(props.value)
        return None
    except Exception:
        return None


# ── Shared browser setup ──────────────────────────────────────────────

async def _setup_authenticated_browser(
    headless: bool | None = None,
    show_browser: bool = False,
    session_id: str | None = None,
    screenshot: str | None = None,
    verbose: bool = False,
) -> dict:
    """
    Shared browser setup: cookie extraction, browser launch, cookie injection,
    navigation to ChatGPT, auth check, and modal dismissal.

    On success, returns a dict with browser/page/injected.
    The caller is responsible for calling browser.stop() when done.

    On failure, the browser is stopped internally before returning.
    """
    if headless is None:
        headless = HEADLESS
    if show_browser:
        headless = False

    _log(f"setup: headless={headless}", verbose)

    # Extract cookies from Chrome
    result = extract_chrome_cookies(CHATGPT_COOKIE_DOMAINS, decrypt=True)
    if not result.get("success"):
        return {
            "success": False,
            "error": f"Cookie extraction failed: {result.get('error')}"
        }
    cookies = result.get("cookies", [])
    _log(f"setup: {len(cookies)} cookies extracted", verbose)

    if not cookies:
        return {
            "success": False,
            "error": "No ChatGPT cookies found. Make sure you're logged into ChatGPT in Chrome."
        }

    # Determine browser profile directory
    if session_id:
        browser_profile = USER_DATA_DIR.parent / f"browser_profile_{session_id}"
        browser_profile.mkdir(exist_ok=True)
    else:
        browser_profile = USER_DATA_DIR

    # Clean stale browser locks from crashed sessions
    clean_browser_locks()

    # Start stealth browser
    browser = await uc.start(
        headless=headless,
        user_data_dir=str(browser_profile),
        browser_args=BROWSER_ARGS
    )

    # Navigate to ChatGPT first to set domain for cookies
    page = await browser.get(CHATGPT_URL)
    await page.sleep(1)

    # Inject cookies via CDP
    injected = 0
    for c in cookies:
        if not c.get("value") or not c.get("name"):
            continue
        try:
            same_site = None
            if c.get("same_site") in ["Strict", "Lax", "None"]:
                same_site = cdp.network.CookieSameSite(c["same_site"])

            name = c["name"]
            domain = c.get("domain", "")
            cookie_domain = domain.lstrip(".")

            # __Host- cookies must NOT have a domain attribute set
            if name.startswith("__Host-"):
                protocol = "https" if c.get("secure", False) else "http"
                cookie_url = f"{protocol}://{cookie_domain}{c.get('path', '/')}"
                param = cdp.network.CookieParam(
                    name=name, value=c["value"], url=cookie_url,
                    path="/", secure=True,
                    http_only=c.get("http_only", False),
                    same_site=same_site,
                )
            else:
                param = cdp.network.CookieParam(
                    name=name, value=c["value"], domain=domain,
                    path=c.get("path", "/"),
                    secure=c.get("secure", False),
                    http_only=c.get("http_only", False),
                    same_site=same_site,
                )
            await browser.connection.send(cdp.storage.set_cookies([param]))
            injected += 1
        except Exception:
            pass

    _log(f"setup: {injected}/{len(cookies)} cookies injected", verbose)

    # Reload with cookies
    page = await browser.get(CHATGPT_URL)
    await page.sleep(3)

    # Check authentication
    is_auth, auth_error = await check_auth_status(page)
    if not is_auth:
        if screenshot:
            await page.save_screenshot(screenshot)
        browser.stop()
        return {
            "success": False,
            "error": f"{auth_error} (injected {injected}/{len(cookies)} cookies)",
            "screenshot": screenshot
        }

    # Dismiss any modal dialogs
    await _cdp_eval(page, '''(() => {
        document.dispatchEvent(new KeyboardEvent('keydown', {
            key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true
        }));
    })()''')
    await page.sleep(0.5)

    return {
        "success": True,
        "browser": browser,
        "page": page,
        "injected": injected,
    }


# ── Auth check ────────────────────────────────────────────────────────

async def check_auth_status(page) -> tuple[bool, str]:
    """
    Check if user is authenticated on ChatGPT.

    Returns:
        tuple: (is_authenticated, error_message)
    """
    current_url = page.url
    page_text = await _cdp_eval(page, 'document.body.innerText') or ""

    if "/auth/login" in current_url or "login" in current_url.lower():
        return False, "Redirected to login page. Please log into ChatGPT in Chrome first."

    if "verify you are human" in page_text.lower() or "cloudflare" in page_text.lower():
        return False, "Cloudflare challenge detected. Use --show-browser flag to bypass."

    if "welcome back" in page_text.lower():
        return False, "Login modal detected. Cookie injection may have failed."

    has_login_button = await _cdp_eval(page, '''(() => {
        const buttons = document.querySelectorAll('button, a');
        for (const btn of buttons) {
            const text = (btn.innerText || btn.textContent || '').trim().toLowerCase();
            if (text === 'log in' || text === 'sign up' || text === 'login'
                || text.includes('continue with google')
                || text.includes('continue with apple')
                || text.includes('continue with microsoft')) {
                const rect = btn.getBoundingClientRect();
                if (rect.width > 50 && rect.height > 30) {
                    return true;
                }
            }
        }
        return false;
    })()''')

    if has_login_button:
        return False, "Not logged in. Please log into ChatGPT in Chrome first."

    return True, ""


# ── Prompt helpers ────────────────────────────────────────────────────

async def _cdp_click(page, x: float, y: float) -> None:
    """Dispatch a real CDP mouse click at coordinates (x, y).

    Sends mouseMoved → mousePressed → mouseReleased, which is the full
    sequence React's synthetic event system needs to register a click.
    """
    await page.send(cdp.input_.dispatch_mouse_event(type_="mouseMoved", x=x, y=y))
    await page.sleep(0.1)
    await page.send(cdp.input_.dispatch_mouse_event(
        type_="mousePressed", x=x, y=y,
        button=cdp.input_.MouseButton.LEFT, click_count=1,
    ))
    await page.sleep(0.05)
    await page.send(cdp.input_.dispatch_mouse_event(
        type_="mouseReleased", x=x, y=y,
        button=cdp.input_.MouseButton.LEFT, click_count=1,
    ))


async def _get_element_center(page, testid: str) -> dict | None:
    """Get the center coordinates of an element by data-testid."""
    return await _cdp_eval(page, f'''(() => {{
        const el = document.querySelector('[data-testid="{testid}"]');
        if (!el) return null;
        const r = el.getBoundingClientRect();
        if (r.width < 5 || r.height < 5) return null;
        return {{x: r.x + r.width / 2, y: r.y + r.height / 2, text: el.innerText.trim()}};
    }})()''')


async def select_model(page, model: str, verbose: bool = False) -> bool:
    """Select the specified model in ChatGPT's model dropdown.

    Uses data-testid attributes for reliable element targeting, and raw
    CDP mouse events (mouseMoved + mousePressed + mouseReleased) for clicks
    that React's synthetic event system correctly handles.

    Handles both primary GPT-5.2 modes and legacy models (behind submenu).
    """
    if model not in CHATGPT_MODEL_TESTIDS:
        _log(f"select_model: unknown model '{model}'", verbose)
        return False

    target_testid = CHATGPT_MODEL_TESTIDS[model]
    target_name = CHATGPT_MODELS.get(model, model)
    is_legacy = model in CHATGPT_LEGACY_MODELS

    _log(f"select_model: target='{target_name}' testid={target_testid} legacy={is_legacy}", verbose)

    try:
        # Step 1: Open model dropdown via CDP mouse click on the button
        btn_coords = await _get_element_center(page, "model-switcher-dropdown-button")
        if not btn_coords:
            _log("select_model: could not find model selector button", verbose)
            return False

        _log(f"select_model: clicking dropdown button at ({btn_coords['x']:.0f},{btn_coords['y']:.0f})", verbose)
        await _cdp_click(page, btn_coords['x'], btn_coords['y'])
        await page.sleep(1.5)

        # Verify dropdown opened
        is_open = await _cdp_eval(page, '''(() => {
            const btn = document.querySelector('[data-testid="model-switcher-dropdown-button"]');
            return btn && btn.getAttribute('aria-expanded') === 'true';
        })()''')
        if not is_open:
            _log("select_model: dropdown did not open", verbose)
            return False

        # Step 2: If legacy model, open the Legacy submenu first
        if is_legacy:
            legacy_coords = await _get_element_center(page, CHATGPT_LEGACY_SUBMENU_TESTID)
            if not legacy_coords:
                _log("select_model: could not find Legacy models submenu", verbose)
                return False
            _log(f"select_model: opening Legacy submenu at ({legacy_coords['x']:.0f},{legacy_coords['y']:.0f})", verbose)
            await _cdp_click(page, legacy_coords['x'], legacy_coords['y'])
            await page.sleep(1)

        # Step 3: Click the target model option by testid
        item_coords = await _get_element_center(page, target_testid)
        if not item_coords:
            _log(f"select_model: could not find testid '{target_testid}' in dropdown", verbose)
            # Close dropdown
            try:
                await page.send(cdp.input_.dispatch_key_event(
                    type_="keyDown", key="Escape", code="Escape",
                    windows_virtual_key_code=27, native_virtual_key_code=27,
                ))
            except Exception:
                pass
            return False

        _log(f"select_model: clicking '{item_coords.get('text', '?')}' at ({item_coords['x']:.0f},{item_coords['y']:.0f})", verbose)
        await _cdp_click(page, item_coords['x'], item_coords['y'])
        await page.sleep(1)

        # Step 4: Verify model switched by checking button text
        new_text = await _cdp_eval(page, '''(() => {
            const btn = document.querySelector('[data-testid="model-switcher-dropdown-button"]');
            return btn ? btn.innerText.trim() : '';
        })()''')

        _log(f"select_model: button now shows '{new_text}'", verbose)
        return True

    except Exception as e:
        _log(f"select_model: exception {e}", verbose)

    return False


async def ensure_new_chat(page, verbose: bool = False) -> bool:
    """Force navigation to a fresh/new chat.

    Tries clicking the 'New chat' button in the sidebar first,
    then falls back to navigating to the base ChatGPT URL.
    """
    # Strategy 1: Click the new chat button
    clicked = await _cdp_eval(page, '''(() => {
        // Look for "New chat" link/button in sidebar
        const links = document.querySelectorAll('a, button');
        for (const el of links) {
            const text = (el.innerText || '').trim().toLowerCase();
            const ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
            const testId = el.getAttribute('data-testid') || '';
            if (text === 'new chat' || ariaLabel.includes('new chat') ||
                testId.includes('new-chat') || testId.includes('create-chat')) {
                el.click();
                return true;
            }
        }
        return false;
    })()''')

    if clicked:
        _log("ensure_new_chat: clicked New Chat button", verbose)
        await page.sleep(2)
        return True

    # Strategy 2: Navigate to base URL
    _log("ensure_new_chat: no button found, navigating to base URL", verbose)
    await page.send(cdp.page.navigate(url=CHATGPT_URL))
    await page.sleep(3)
    return True


async def input_prompt(page, prompt: str) -> bool:
    """
    Input the prompt into ChatGPT's text field.
    ChatGPT uses ProseMirror - a contenteditable div, not a standard textarea.
    """
    input_element = None
    for selector in CHATGPT_INPUT_SELECTORS:
        try:
            input_element = await page.select(selector, timeout=3)
            if input_element:
                break
        except Exception:
            continue

    if not input_element:
        try:
            input_element = await page.select('div[contenteditable="true"]', timeout=3)
        except Exception:
            pass

    if not input_element:
        try:
            found = await _cdp_eval(page, '''(() => {
                let el = document.getElementById('prompt-textarea');
                if (el) { el.focus(); return true; }
                el = document.querySelector('.ProseMirror');
                if (el) { el.focus(); return true; }
                el = document.querySelector('[contenteditable="true"]');
                if (el) { el.focus(); return true; }
                return false;
            })()''')
            if found:
                input_element = await page.select(':focus', timeout=2)
        except Exception:
            pass

    if not input_element:
        return False

    await input_element.click()
    await page.sleep(0.3)

    escaped_prompt = (prompt
        .replace('\\', '\\\\')
        .replace('`', '\\`')
        .replace('${', '\\${')
        .replace('\n', '\\n')
        .replace('\r', '\\r')
        .replace('\t', '\\t'))

    success = await _cdp_eval(page, f'''(() => {{
        const prompt = `{escaped_prompt}`;
        const el = document.activeElement;
        if (!el) return false;

        if (el.contentEditable === 'true' || el.isContentEditable) {{
            while (el.firstChild) {{ el.removeChild(el.firstChild); }}
            const p = document.createElement('p');
            p.textContent = prompt;
            el.appendChild(p);
            el.dispatchEvent(new InputEvent('input', {{
                bubbles: true, cancelable: true,
                inputType: 'insertText', data: prompt
            }}));
            return true;
        }}

        if (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT') {{
            el.value = prompt;
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            return true;
        }}

        return false;
    }})()''')

    if not success:
        await input_element.send_keys(prompt)

    await page.sleep(0.5)
    return True


async def send_prompt(page) -> bool:
    """Click the send button to submit the prompt."""
    for selector in CHATGPT_SEND_SELECTORS:
        try:
            btn = await page.select(selector, timeout=2)
            if btn:
                await btn.click()
                return True
        except Exception:
            continue

    sent = await _cdp_eval(page, '''(() => {
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            const label = btn.getAttribute('aria-label') || '';
            const testId = btn.getAttribute('data-testid') || '';
            if (label.toLowerCase().includes('send') ||
                testId.includes('send') ||
                btn.querySelector('svg[data-icon="send"]')) {
                btn.click();
                return true;
            }
        }
        return false;
    })()''')

    if sent:
        return True

    try:
        focused = await page.select(':focus', timeout=1)
        if focused:
            await focused.send_keys('\n')
            return True
    except Exception:
        pass

    return False


async def _upload_attachments(
    page,
    file_paths: list[str],
    verbose: bool = False,
) -> dict:
    """Upload files to ChatGPT's composer via CDP file chooser interception.

    Strategy:
    1. Register a handler for Page.fileChooserOpened CDP event
    2. Enable Page.setInterceptFileChooserDialog — suppresses native picker
    3. Press ⌘U (the keyboard shortcut for "Add photos & files")
    4. When fileChooserOpened fires, disable interception and use
       DOM.setFileInputFiles with backend_node_id from the event
    5. React sees native file input change and processes the files
    """
    if not file_paths:
        return {"success": True, "attached": 0}

    missing = [p for p in file_paths if not Path(p).exists()]
    if missing:
        return {
            "success": False,
            "error": f"File(s) not found: {', '.join(missing)}",
        }

    abs_paths = [str(Path(p).resolve()) for p in file_paths]
    _log(f"upload: attaching {len(abs_paths)} file(s): {abs_paths}", verbose)

    # Future to track when the file chooser has been handled
    loop = asyncio.get_event_loop()
    chooser_future: asyncio.Future[bool] = loop.create_future()

    async def _on_file_chooser(event: cdp.page.FileChooserOpened):
        """CDP event handler: fires when file chooser opens.

        Uses DOM.setFileInputFiles with the backend_node_id from the event
        to set files on the exact input element React opened the chooser for.
        Page.handleFileChooser was removed from Chrome, so we use this approach.
        """
        _log(
            f"upload: fileChooserOpened — mode={event.mode} "
            f"backend_node_id={event.backend_node_id}",
            verbose,
        )
        try:
            # Disable interception first so the pending chooser is dismissed
            await page.send(
                cdp.page.set_intercept_file_chooser_dialog(enabled=False)
            )
            _log("upload: interception disabled, setting files via DOM", verbose)

            # Set files directly on the input using its backend_node_id.
            # DOM.setFileInputFiles dispatches native browser events which
            # React's capture-phase listeners will pick up.
            await page.send(cdp.dom.set_file_input_files(
                files=abs_paths,
                backend_node_id=event.backend_node_id,
            ))
            _log("upload: DOM.setFileInputFiles succeeded", verbose)
            if not chooser_future.done():
                chooser_future.set_result(True)
        except Exception as e:
            _log(f"upload: setFileInputFiles error — {e}", verbose)
            if not chooser_future.done():
                chooser_future.set_result(False)

    try:
        # Register event handler BEFORE enabling interception
        page.add_handler(cdp.page.FileChooserOpened, _on_file_chooser)
        _log("upload: registered FileChooserOpened handler", verbose)

        # Enable file chooser interception
        await page.send(cdp.page.set_intercept_file_chooser_dialog(enabled=True))
        _log("upload: file chooser interception enabled", verbose)

        # ── Trigger file chooser via ⌘U shortcut ─────────────────────
        # ⌘U is the keyboard shortcut for "Add photos & files" in ChatGPT.
        # Using the shortcut is more reliable than navigating the '+' menu,
        # which has container elements that make click targeting fragile.
        _log("upload: sending ⌘U to trigger file picker", verbose)
        await page.send(cdp.input_.dispatch_key_event(
            type_="keyDown", key="u", code="KeyU",
            windows_virtual_key_code=85, native_virtual_key_code=85,
            modifiers=4,  # 4 = Meta (Cmd on Mac)
        ))
        await page.sleep(0.1)
        await page.send(cdp.input_.dispatch_key_event(
            type_="keyUp", key="u", code="KeyU",
            windows_virtual_key_code=85, native_virtual_key_code=85,
            modifiers=4,
        ))

        # ── Step 3: Wait for file chooser event handler to fire ───────
        try:
            handled = await asyncio.wait_for(chooser_future, timeout=10.0)
        except asyncio.TimeoutError:
            _log("upload: file chooser event timed out after 10s", verbose)
            handled = False

        if not handled:
            return {
                "success": False,
                "error": "File chooser was not triggered or could not be handled",
            }

        # ── Step 4: Wait for ChatGPT to process attachments ──────────
        _log("upload: waiting for file processing...", verbose)
        await page.sleep(3)

        # Verify attachment indicators in composer
        attached = await _cdp_eval(page, '''(() => {
            const indicators = document.querySelectorAll(
                '[data-testid*="attachment"], [class*="attachment"], ' +
                '[class*="file-chip"], [class*="uploaded"], ' +
                'img[alt*="Uploaded"], form [class*="thumbnail"], ' +
                'form [class*="preview"]'
            );
            return {count: indicators.length};
        })()''')

        _log(f"upload: attachment indicators: {attached}", verbose)

        return {
            "success": True,
            "attached": len(abs_paths),
            "files": abs_paths,
            "indicators": attached,
        }

    except Exception as e:
        _log(f"upload: error — {e}", verbose)
        return {
            "success": False,
            "error": f"File upload failed: {e}",
        }
    finally:
        # Always clean up: disable interception and remove handler
        try:
            await page.send(
                cdp.page.set_intercept_file_chooser_dialog(enabled=False)
            )
        except Exception:
            pass
        # Remove the handler to avoid leaking
        try:
            handlers = page.handlers.get(cdp.page.FileChooserOpened, [])
            if _on_file_chooser in handlers:
                handlers.remove(_on_file_chooser)
        except Exception:
            pass


async def wait_for_response(page, timeout: int, poll_interval: float = POLL_INTERVAL) -> tuple[str, int]:
    """
    Wait for ChatGPT to complete its response.
    Handles reasoning models that can think for extended periods.
    """
    start_time = time.time()
    last_text = ""
    stable_count = 0
    thinking_time = 0
    response_started = False

    while time.time() - start_time < timeout:
        try:
            page_text = await _cdp_eval(page, 'document.body.innerText') or ""

            if "rate limit" in page_text.lower() or "too many requests" in page_text.lower():
                return "", -1

            if "something went wrong" in page_text.lower():
                return "", -2

            is_generating = await _cdp_eval(page, '''(() => {
                const stopBtn = document.querySelector('[data-testid="stop-button"]') ||
                               document.querySelector('[aria-label="Stop generating"]') ||
                               document.querySelector('button.stop-button');
                return stopBtn !== null;
            })()''')

            thinking_match = await _cdp_eval(page, '''(() => {
                const text = document.body.innerText;
                const match = text.match(/(?:Thought|Thinking|Reasoned?)\\s+(?:for\\s+)?(\\d+)\\s*(?:second|sec|s)/i);
                if (match) return parseInt(match[1], 10);
                if (text.includes('Thinking') || text.includes('Reasoning')) return 0;
                return -1;
            })()''')

            if thinking_match is not None and thinking_match >= 0:
                thinking_time = thinking_match
                response_started = True

            full_page_text = await _cdp_eval(page, 'document.body.innerText') or ""
            response_text = ""

            # UI chrome lines to filter out (compiled once outside loop would be
            # ideal, but re.compile is cheap and this keeps the pattern local)
            _ui_chrome_re = re.compile(
                r'^(Copy|Share|Like|Dislike|Read aloud|ChatGPT|Ask anything|'
                r'Extended|Memory|\d+\s*/\s*\d+|Pro thinking|Done|DEVELOPER|'
                r'Thought for)',
                re.IGNORECASE
            )

            # Method 1: Look for text after "Thought for X seconds"
            thought_match = re.search(r'Thought for \d+ seconds?\s*>?\s*', full_page_text, re.IGNORECASE)
            if thought_match:
                after_thought = full_page_text[thought_match.end():].strip()
                lines = [l.strip() for l in after_thought.split('\n') if l.strip()]
                filtered = [l for l in lines if not _ui_chrome_re.match(l)]
                if filtered:
                    response_text = '\n'.join(filtered)

            # Method 2: Markdown / prose areas (capture full text, not just first line)
            if not response_text:
                prose_text = await _cdp_eval(page, '''(() => {
                    const els = document.querySelectorAll('.markdown, .prose, [class*="markdown"]');
                    if (els.length > 0) return els[els.length - 1].innerText.trim();
                    return '';
                })()''') or ""

                if prose_text:
                    lines = [l.strip() for l in prose_text.split('\n') if l.strip()]
                    filtered = [l for l in lines if not _ui_chrome_re.match(l)]
                    if filtered:
                        response_text = '\n'.join(filtered)

            if response_text:
                response_started = True

                if not is_generating:
                    if response_text == last_text:
                        stable_count += 1
                        if stable_count >= STABILITY_THRESHOLD:
                            return response_text.strip(), thinking_time
                    else:
                        stable_count = 0
                        last_text = response_text
                else:
                    stable_count = 0
                    last_text = response_text

            if response_text and not is_generating:
                await page.sleep(1)
                final_text = await _cdp_eval(page, '''(() => {
                    const selectors = [
                        '[data-message-author-role="assistant"]',
                        '.agent-turn',
                        'article[data-testid*="conversation-turn"]',
                        'div[class*="markdown"]'
                    ];
                    let messages = [];
                    for (const sel of selectors) {
                        const found = document.querySelectorAll(sel);
                        if (found.length > 0) { messages = Array.from(found); break; }
                    }
                    if (messages.length === 0) return '';
                    const lastMsg = messages[messages.length - 1];
                    const md = lastMsg.querySelector('.markdown, [class*="markdown"], .prose');
                    const container = md || lastMsg;
                    const parts = [];
                    for (const el of container.children) {
                        if (el.tagName === 'PRE') {
                            const code = el.querySelector('code');
                            if (code) {
                                let lang = '';
                                const m = (code.className || '').match(/language-(\\w+)/);
                                if (m) lang = m[1];
                                parts.push('```' + lang + '\\n' + code.innerText.trimEnd() + '\\n```');
                            }
                        } else {
                            const t = el.innerText ? el.innerText.trim() : '';
                            if (t) parts.push(t);
                        }
                    }
                    return parts.length > 0 ? parts.join('\\n\\n') : container.innerText;
                })()''')
                if final_text:
                    return final_text.strip(), thinking_time

        except Exception:
            pass

        await page.sleep(poll_interval)

    return last_text.strip() if last_text else "", thinking_time


# ── Core operations ───────────────────────────────────────────────────

async def prompt_chatgpt(
    prompt: str,
    headless: bool = None,
    timeout: int = None,
    screenshot: str = None,
    show_browser: bool = False,
    model: str = None,
    session_id: str = None,
    verbose: bool = False,
    new_chat: bool = False,
    continue_chat_id: str | None = None,
    project: str | None = None,
    temp_chat: bool = False,
    web_search: bool | None = None,
    files: list[str] | None = None,
) -> dict:
    """Send a prompt to ChatGPT and get the response.

    Args:
        new_chat: Force a fresh conversation before sending.
        continue_chat_id: Navigate to this chat first (continue existing conversation).
        project: Navigate to a ChatGPT Project by name or ID before sending.
        temp_chat: Enable temporary chat mode (not saved to history).
        web_search: True to enable, False to disable, None for default.
        files: List of file paths to upload as attachments before sending.
    """
    selected_model = model or DEFAULT_MODEL
    if timeout is None:
        timeout = MODEL_TIMEOUTS.get(selected_model, DEFAULT_TIMEOUT)

    setup = await _setup_authenticated_browser(
        headless=headless,
        show_browser=show_browser,
        session_id=session_id,
        screenshot=screenshot,
        verbose=verbose,
    )
    if not setup["success"]:
        return setup

    browser = setup["browser"]
    page = setup["page"]
    injected = setup["injected"]

    try:
        # Handle --continue-chat: navigate to existing conversation
        if continue_chat_id:
            _log(f"continue_chat: navigating to chat {continue_chat_id}", verbose)

            # Resolve index or title to a real chat ID
            resolved_id = continue_chat_id
            idx_match = re.match(r'^idx-(\d+)$', continue_chat_id)
            if idx_match or not re.match(r'^[a-zA-Z0-9-]{20,}$', continue_chat_id):
                # Need to look up from sidebar
                await page.sleep(2)
                chat_links = await _cdp_eval(page, '''(() => {
                    const results = [];
                    const links = document.querySelectorAll('a[href*="/c/"]');
                    for (const a of links) {
                        const href = a.getAttribute('href') || '';
                        const text = (a.innerText || '').trim().substring(0, 200);
                        if (!text || text.length < 2) continue;
                        const match = href.match(/\\/c\\/([a-zA-Z0-9-]+)/);
                        const chatId = match ? match[1] : '';
                        results.push({id: chatId, title: text, url: href});
                    }
                    return results;
                })()''')

                if idx_match:
                    chat_index = int(idx_match.group(1))
                    if not chat_links or chat_index >= len(chat_links):
                        return {
                            "success": False,
                            "error": f"Chat index {chat_index} out of range (found {len(chat_links or [])} chats)"
                        }
                    resolved_id = chat_links[chat_index]['id']
                    _log(f"continue_chat: resolved idx-{chat_index} -> {resolved_id}", verbose)
                else:
                    # Title substring search
                    found = None
                    for link in (chat_links or []):
                        if continue_chat_id.lower() in link['title'].lower():
                            found = link
                            break
                    if not found:
                        return {
                            "success": False,
                            "error": f"Chat '{continue_chat_id}' not found in sidebar"
                        }
                    resolved_id = found['id']
                    _log(f"continue_chat: resolved '{continue_chat_id}' -> {resolved_id}", verbose)

            # Navigate to the existing chat
            chat_url = CHATGPT_CHAT_URL.format(chat_id=resolved_id)
            page = await browser.get(chat_url)
            await page.sleep(4)

        # Handle --project: navigate to project context
        elif project:
            _log(f"project: resolving project '{project}'", verbose)
            await page.sleep(2)

            # Find the Projects button and expand if needed
            projects_btn = await _cdp_eval(page, '''(() => {
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    const text = (btn.innerText || '').trim();
                    if (text === 'Projects') {
                        const r = btn.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            return {x: r.x + r.width / 2, y: r.y + r.height / 2};
                        }
                    }
                }
                return null;
            })()''')

            # Expand Projects section if no project links visible
            project_links_count = await _cdp_eval(page, '''(() => {
                return document.querySelectorAll('a[href*="/g/g-p-"]').length;
            })()''')

            if projects_btn and not project_links_count:
                await _cdp_click(page, projects_btn['x'], projects_btn['y'])
                await page.sleep(1.5)

            # Find all project links
            project_links = await _cdp_eval(page, '''(() => {
                const results = [];
                const links = document.querySelectorAll('a[href*="/g/g-p-"]');
                for (const a of links) {
                    const href = a.getAttribute('href') || '';
                    const text = (a.innerText || '').trim().substring(0, 200);
                    if (!text || text.length < 2) continue;
                    const match = href.match(/\\/g\\/(g-p-[a-zA-Z0-9-]+)\\/project/);
                    const projectId = match ? match[1] : '';
                    results.push({id: projectId, name: text, url: href});
                }
                return results;
            })()''')

            if not project_links:
                return {"success": False, "error": "No projects found in sidebar"}

            # Match by name (case-insensitive substring) or by ID
            matched = None
            for pl in project_links:
                if project.lower() in pl['name'].lower() or project == pl['id']:
                    matched = pl
                    break

            if not matched:
                available = ", ".join(pl['name'] for pl in project_links)
                return {
                    "success": False,
                    "error": f"Project '{project}' not found. Available: {available}"
                }

            _log(f"project: navigating to '{matched['name']}' ({matched['id']})", verbose)
            project_url = f"https://chatgpt.com{matched['url']}"
            page = await browser.get(project_url)
            await page.sleep(4)

        # Handle --new-chat: force fresh conversation
        elif new_chat:
            await ensure_new_chat(page, verbose=verbose)

        # Select model if needed (only for new chats, not continued/project ones)
        if selected_model != "auto" and not continue_chat_id and not project:
            model_selected = await select_model(page, selected_model, verbose=verbose)
            if not model_selected:
                _log("model selection failed, continuing with default", verbose)

        # Handle --temp-chat: toggle temporary chat mode
        if temp_chat:
            _log("temp_chat: enabling temporary chat mode", verbose)
            # ChatGPT has a "Temporary chat" toggle accessible via the model selector area
            # or via a switch/toggle in the interface. Try multiple strategies.
            temp_toggled = await _cdp_eval(page, '''(() => {
                // Strategy 1: Look for a toggle/switch with temp-related attributes
                const toggles = document.querySelectorAll(
                    '[data-testid*="temp"], [data-testid*="temporary"], ' +
                    'button[aria-label*="emporary"], label[for*="temp"]'
                );
                for (const t of toggles) {
                    const r = t.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        return {x: r.x + r.width / 2, y: r.y + r.height / 2, strategy: 'testid'};
                    }
                }
                // Strategy 2: Look for text "Temporary" in buttons/labels
                const elems = document.querySelectorAll('button, label, span, div[role="switch"]');
                for (const el of elems) {
                    const text = (el.innerText || '').trim().toLowerCase();
                    if (text.includes('temporary') || text.includes('temp chat')) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            return {x: r.x + r.width / 2, y: r.y + r.height / 2, strategy: 'text'};
                        }
                    }
                }
                return null;
            })()''')

            if temp_toggled:
                _log(f"temp_chat: found toggle via {temp_toggled['strategy']}, clicking", verbose)
                await _cdp_click(page, temp_toggled['x'], temp_toggled['y'])
                await page.sleep(0.5)
            else:
                _log("temp_chat: toggle not found, trying URL parameter", verbose)
                # Fallback: navigate with temporary=true parameter
                current_url = await _cdp_eval(page, 'window.location.href')
                if current_url and '?' in current_url:
                    page = await browser.get(f"{current_url}&temporary-chat=true")
                else:
                    page = await browser.get(f"{CHATGPT_URL}?temporary-chat=true")
                await page.sleep(3)

        # Handle --search/--no-search: toggle web search
        if web_search is not None:
            action_label = "enabling" if web_search else "disabling"
            _log(f"web_search: {action_label} web search", verbose)

            search_toggle = await _cdp_eval(page, '''(() => {
                // Look for search toggle near the input area
                const toggles = document.querySelectorAll(
                    '[data-testid*="search"], [data-testid*="web-search"], ' +
                    'button[aria-label*="earch"], [role="switch"][aria-label*="earch"]'
                );
                for (const t of toggles) {
                    const r = t.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        const isChecked = t.getAttribute('aria-checked') === 'true' ||
                                         t.classList.contains('active') ||
                                         t.getAttribute('data-state') === 'checked';
                        return {
                            x: r.x + r.width / 2, y: r.y + r.height / 2,
                            isEnabled: isChecked, strategy: 'testid'
                        };
                    }
                }
                // Strategy 2: Look for "Search" text in toolbar buttons
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    const text = (btn.innerText || '').trim().toLowerCase();
                    if (text === 'search' || text === 'search the web') {
                        const r = btn.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            const isActive = btn.classList.contains('active') ||
                                           btn.getAttribute('aria-pressed') === 'true';
                            return {
                                x: r.x + r.width / 2, y: r.y + r.height / 2,
                                isEnabled: isActive, strategy: 'text'
                            };
                        }
                    }
                }
                return null;
            })()''')

            if search_toggle:
                needs_click = (web_search and not search_toggle['isEnabled']) or \
                              (not web_search and search_toggle['isEnabled'])
                if needs_click:
                    _log(f"web_search: toggling search (currently {'on' if search_toggle['isEnabled'] else 'off'})", verbose)
                    await _cdp_click(page, search_toggle['x'], search_toggle['y'])
                    await page.sleep(0.5)
                else:
                    _log(f"web_search: already in desired state", verbose)
            else:
                _log("web_search: toggle not found in UI, skipping", verbose)

        # Handle --file / --image: upload attachments before sending prompt
        if files:
            upload_result = await _upload_attachments(page, files, verbose=verbose)
            if not upload_result["success"]:
                if screenshot:
                    await page.save_screenshot(screenshot)
                return {
                    "success": False,
                    "error": upload_result.get("error", "File upload failed"),
                    "screenshot": screenshot,
                }
            _log(f"upload: {upload_result['attached']} file(s) attached", verbose)

        # Input the prompt
        if not await input_prompt(page, prompt):
            if screenshot:
                await page.save_screenshot(screenshot)
            return {
                "success": False,
                "error": "Could not find ChatGPT input field",
                "screenshot": screenshot
            }

        await page.sleep(0.5)

        # Send the prompt
        if not await send_prompt(page):
            if screenshot:
                await page.save_screenshot(screenshot)
            return {
                "success": False,
                "error": "Could not find send button",
                "screenshot": screenshot
            }

        # Wait for response
        start_time = time.time()
        response_text, thinking_time = await wait_for_response(page, timeout)
        total_time = int(time.time() - start_time)

        if screenshot:
            await page.save_screenshot(screenshot)

        if thinking_time == -1:
            return {
                "success": False,
                "error": "Rate limit reached. Wait before trying again.",
                "rate_limited": True,
                "screenshot": screenshot
            }

        if thinking_time == -2:
            return {
                "success": False,
                "error": "ChatGPT returned an error. Try again.",
                "screenshot": screenshot
            }

        if not response_text:
            return {
                "success": False,
                "error": "Timeout waiting for ChatGPT response",
                "screenshot": screenshot
            }

        response_tokens = estimate_tokens(response_text)
        prompt_tokens = estimate_tokens(prompt)

        return {
            "success": True,
            "response": response_text,
            "prompt": prompt,
            "model": CHATGPT_MODELS.get(selected_model, selected_model),
            "thinking_time_seconds": thinking_time if thinking_time > 0 else None,
            "total_time_seconds": total_time,
            "cookies_used": injected,
            "tokens": {
                "response": response_tokens,
                "prompt": prompt_tokens,
                "total": response_tokens + prompt_tokens
            },
            "screenshot": screenshot
        }

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }

    finally:
        if browser:
            browser.stop()


async def list_chatgpt_chats(
    headless: bool | None = None,
    show_browser: bool = False,
    limit: int = 50,
    verbose: bool = False,
) -> dict:
    """
    List recent ChatGPT conversations from the sidebar.

    Scrapes the sidebar nav for chat titles, conversation IDs (from /c/{id} URLs),
    and date groupings.

    Returns:
        dict with success status and list of chats.
    """
    setup = await _setup_authenticated_browser(
        headless=headless,
        show_browser=show_browser,
        verbose=verbose,
    )
    if not setup["success"]:
        return setup

    browser = setup["browser"]
    page = setup["page"]

    try:
        # Wait for sidebar to render
        await page.sleep(3)

        # Strategy 1: Extract chat links directly from DOM (most reliable)
        # ChatGPT sidebar uses <a href="/c/{conversation_id}"> elements
        chat_links = await _cdp_eval(page, '''(() => {
            const results = [];
            const links = document.querySelectorAll('a[href*="/c/"]');
            for (const a of links) {
                const href = a.getAttribute('href') || '';
                const text = (a.innerText || '').trim().substring(0, 200);
                if (!text || text.length < 2) continue;

                // Extract conversation ID from href
                const match = href.match(/\\/c\\/([a-zA-Z0-9-]+)/);
                const chatId = match ? match[1] : '';

                // Find date group: walk up DOM to find a date header sibling
                let dateGroup = '';
                let parent = a.parentElement;
                while (parent && !dateGroup) {
                    // Check previous siblings for date headers
                    let sibling = parent.previousElementSibling;
                    while (sibling) {
                        const sibText = (sibling.innerText || '').trim();
                        if (['Today', 'Yesterday', 'Previous 7 Days',
                             'Previous 30 Days', 'Last week', 'Last month',
                             'January', 'February', 'March', 'April', 'May',
                             'June', 'July', 'August', 'September', 'October',
                             'November', 'December'].some(d => sibText.startsWith(d))) {
                            dateGroup = sibText;
                            break;
                        }
                        sibling = sibling.previousElementSibling;
                    }
                    parent = parent.parentElement;
                }

                results.push({
                    id: chatId,
                    title: text,
                    url: href,
                    date: dateGroup,
                });
            }
            return results;
        })()''')

        _log(f"list_chats: DOM extraction found {len(chat_links or [])} chat links", verbose)

        chats = []
        if chat_links:
            for link in chat_links[:limit]:
                chats.append({
                    'id': link.get('id', ''),
                    'title': link.get('title', 'Untitled'),
                    'url': link.get('url', ''),
                    'date': link.get('date', ''),
                })

        # Strategy 2: Fallback to innerText parsing if DOM extraction failed
        if not chats:
            _log("list_chats: DOM extraction failed, trying innerText parsing", verbose)
            page_text = await _cdp_eval(page, 'document.body.innerText') or ""

            date_headers = {
                'Today', 'Yesterday', 'Previous 7 Days', 'Previous 30 Days',
                'Last week', 'Last month', 'Older',
                'January', 'February', 'March', 'April', 'May', 'June',
                'July', 'August', 'September', 'October', 'November', 'December',
            }
            skip_texts = {
                'ChatGPT', 'Explore GPTs', 'New chat', 'Search',
                'Upgrade plan', 'Settings', 'Help', 'Profile',
                'Ask anything', 'Message ChatGPT',
            }
            _date_line_re = re.compile(
                r'^(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},?\s+\d{4}$'
            )

            current_date = ''
            for line in page_text.split('\n'):
                line = line.strip()
                if not line or len(line) < 3:
                    continue

                if line in date_headers:
                    current_date = line
                    continue

                if _date_line_re.match(line):
                    current_date = line
                    continue

                if line in skip_texts:
                    continue

                if len(line) < 5:
                    continue

                if len(chats) < limit:
                    chats.append({
                        'id': f'idx-{len(chats)}',
                        'title': line[:200],
                        'url': '',
                        'date': current_date,
                    })

        _log(f"list_chats: {len(chats)} chats found", verbose)

        return {
            "success": True,
            "chats": chats[:limit],
            "count": len(chats[:limit]),
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

    finally:
        if browser:
            browser.stop()


async def get_chatgpt_chat(
    chat_id: str,
    headless: bool | None = None,
    show_browser: bool = False,
    timeout: int = 60,
    verbose: bool = False,
) -> dict:
    """
    Retrieve the full conversation text from a specific ChatGPT chat.

    Supports three identifier formats:
    - idx-N: Numeric index from --list-chats output (opens sidebar, clicks Nth chat)
    - Conversation ID: Direct navigation to chatgpt.com/c/{id}
    - Title substring: Matches against sidebar titles

    Args:
        chat_id: The chat index, conversation ID, or title substring.
        timeout: Seconds to wait for conversation to render.

    Returns:
        dict with success status, chat metadata, and list of messages.
    """
    idx_match = re.match(r'^idx-(\d+)$', chat_id)
    is_index = idx_match is not None
    chat_index: int = int(idx_match.group(1)) if idx_match else 0

    setup = await _setup_authenticated_browser(
        headless=headless,
        show_browser=show_browser,
        verbose=verbose,
    )
    if not setup["success"]:
        return setup

    browser = setup["browser"]
    page = setup["page"]

    try:
        _log(f"get_chat: id={chat_id} is_index={is_index}", verbose)

        target_title = ""

        if is_index:
            # Need to find the chat by index from the sidebar
            await page.sleep(3)

            # Get ordered list of chat links
            chat_links = await _cdp_eval(page, '''(() => {
                const results = [];
                const links = document.querySelectorAll('a[href*="/c/"]');
                for (const a of links) {
                    const href = a.getAttribute('href') || '';
                    const text = (a.innerText || '').trim().substring(0, 200);
                    if (!text || text.length < 2) continue;
                    const match = href.match(/\\/c\\/([a-zA-Z0-9-]+)/);
                    const chatId = match ? match[1] : '';
                    results.push({id: chatId, title: text, url: href});
                }
                return results;
            })()''')

            if not chat_links or chat_index >= len(chat_links):
                return {
                    "success": False,
                    "error": f"Chat index {chat_index} out of range (found {len(chat_links or [])} chats)"
                }

            target = chat_links[chat_index]
            chat_id = target['id']
            target_title = target['title']
            _log(f"get_chat: index {chat_index} → id={chat_id} title=\"{target_title}\"", verbose)

        elif not re.match(r'^[a-zA-Z0-9-]{20,}$', chat_id):
            # Looks like a title substring, not a conversation ID
            await page.sleep(3)

            chat_links = await _cdp_eval(page, '''(() => {
                const results = [];
                const links = document.querySelectorAll('a[href*="/c/"]');
                for (const a of links) {
                    const href = a.getAttribute('href') || '';
                    const text = (a.innerText || '').trim().substring(0, 200);
                    if (!text || text.length < 2) continue;
                    const match = href.match(/\\/c\\/([a-zA-Z0-9-]+)/);
                    const chatId = match ? match[1] : '';
                    results.push({id: chatId, title: text, url: href});
                }
                return results;
            })()''')

            # Find by title substring
            found = None
            for link in (chat_links or []):
                if chat_id.lower() in link['title'].lower():
                    found = link
                    break

            if not found:
                titles = [l['title'] for l in (chat_links or [])[:5]]
                return {
                    "success": False,
                    "error": f"Chat '{chat_id}' not found in sidebar. Available: {titles}"
                }

            chat_id = found['id']
            target_title = found['title']
            _log(f"get_chat: title match → id={chat_id} title=\"{target_title}\"", verbose)

        # Navigate to the chat
        chat_url = CHATGPT_CHAT_URL.format(chat_id=chat_id)
        _log(f"get_chat: navigating to {chat_url}", verbose)
        page = await browser.get(chat_url)
        await page.sleep(5)

        # Extract conversation turns using data-message-author-role attributes
        start_time = time.time()
        last_messages = None
        stable_count = 0
        final_messages = None

        while time.time() - start_time < timeout:
            messages = await _cdp_eval(page, '''(() => {
                const results = [];

                // Strategy 1: Use data-message-author-role (most reliable)
                const turns = document.querySelectorAll('[data-message-author-role]');
                if (turns.length > 0) {
                    for (const turn of turns) {
                        const role = turn.getAttribute('data-message-author-role') || 'unknown';
                        // Get markdown content if available, otherwise innerText
                        const markdown = turn.querySelector('.markdown, [class*="markdown"], .prose');
                        const text = markdown ? markdown.innerText.trim() : turn.innerText.trim();
                        if (text && text.length > 0) {
                            results.push({role: role, text: text});
                        }
                    }
                    if (results.length > 0) return results;
                }

                // Strategy 2: Article-based conversation turns
                const articles = document.querySelectorAll('article[data-testid*="conversation-turn"]');
                if (articles.length > 0) {
                    for (let i = 0; i < articles.length; i++) {
                        const article = articles[i];
                        const role = i % 2 === 0 ? 'user' : 'assistant';
                        const markdown = article.querySelector('.markdown, [class*="markdown"], .prose');
                        const text = markdown ? markdown.innerText.trim() : article.innerText.trim();
                        if (text && text.length > 0) {
                            results.push({role: role, text: text});
                        }
                    }
                    if (results.length > 0) return results;
                }

                // Strategy 3: Look for .agent-turn / user message patterns
                const agentTurns = document.querySelectorAll('.agent-turn, .user-turn');
                for (const turn of agentTurns) {
                    const isAgent = turn.classList.contains('agent-turn');
                    const role = isAgent ? 'assistant' : 'user';
                    const text = turn.innerText.trim();
                    if (text && text.length > 0) {
                        results.push({role: role, text: text});
                    }
                }

                return results;
            })()''')

            _log(f"get_chat poll: {len(messages or [])} messages found", verbose)

            if messages and len(messages) > 0:
                # Serialize for comparison
                messages_key = json.dumps(messages)
                if messages_key == json.dumps(last_messages):
                    stable_count += 1
                    if stable_count >= 3:
                        final_messages = messages
                        break
                else:
                    stable_count = 0
                    last_messages = messages
            else:
                stable_count = 0

            await page.sleep(1)

        if not final_messages:
            final_messages = last_messages or []

        if not final_messages:
            return {"success": False, "error": "Could not extract conversation messages"}

        # Clean up messages: strip UI boilerplate from each turn
        cleaned_messages = []
        for i, msg in enumerate(final_messages):
            text = msg.get('text', '')
            role = msg.get('role', 'unknown')

            # Strip trailing UI elements from assistant messages
            if role == 'assistant':
                # Remove trailing "Copy\nShare\nLike\nDislike" etc.
                for suffix in ['\nCopy', '\nShare', '\nLike', '\nDislike',
                               '\nRead aloud', '\nSearch']:
                    while text.endswith(suffix):
                        text = text[:-len(suffix)]

            cleaned_messages.append({
                'role': role,
                'text': text.strip(),
                'index': i,
            })

        # Get title if we don't have one
        if not target_title and cleaned_messages:
            # Use first user message as title (truncated)
            for msg in cleaned_messages:
                if msg['role'] == 'user':
                    target_title = msg['text'][:100]
                    break

        return {
            "success": True,
            "chat_id": chat_id,
            "title": target_title or chat_id,
            "messages": cleaned_messages,
            "message_count": len(cleaned_messages),
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

    finally:
        if browser:
            browser.stop()


async def search_chatgpt_chats(
    query: str,
    headless: bool | None = None,
    show_browser: bool = False,
    limit: int = 20,
    verbose: bool = False,
) -> dict:
    """
    Search ChatGPT conversations using the Cmd+K search dialog.

    Opens the search overlay, types the query, and extracts matching results.

    Args:
        query: Search query string.
        limit: Maximum results to return.

    Returns:
        dict with success status and list of matching chats.
    """
    setup = await _setup_authenticated_browser(
        headless=headless,
        show_browser=show_browser,
        verbose=verbose,
    )
    if not setup["success"]:
        return setup

    browser = setup["browser"]
    page = setup["page"]

    try:
        await page.sleep(2)

        # Open search dialog via Cmd+K (Meta key on Mac)
        _log("search: sending Cmd+K to open search dialog", verbose)
        await page.send(cdp.input_.dispatch_key_event(
            type_="keyDown", key="k", code="KeyK",
            windows_virtual_key_code=75, native_virtual_key_code=75,
            modifiers=4,  # 4 = Meta (Cmd on Mac)
        ))
        await page.sleep(0.1)
        await page.send(cdp.input_.dispatch_key_event(
            type_="keyUp", key="k", code="KeyK",
            windows_virtual_key_code=75, native_virtual_key_code=75,
            modifiers=4,
        ))
        await page.sleep(2)

        # Find the search input
        search_input = await _cdp_eval(page, '''(() => {
            const inputs = document.querySelectorAll('input');
            for (const inp of inputs) {
                const ph = (inp.getAttribute('placeholder') || '').toLowerCase();
                if (ph.includes('search')) {
                    const r = inp.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        return {x: r.x + r.width / 2, y: r.y + r.height / 2,
                                placeholder: inp.getAttribute('placeholder')};
                    }
                }
            }
            return null;
        })()''')

        if not search_input:
            _log("search: could not find search input", verbose)
            return {"success": False, "error": "Could not find search input. Cmd+K may not have opened."}

        _log(f"search: found input with placeholder={search_input['placeholder']!r}", verbose)

        # Click the input to focus it
        await _cdp_click(page, search_input['x'], search_input['y'])
        await page.sleep(0.5)

        # Type the query via CDP key events
        for char in query:
            await page.send(cdp.input_.dispatch_key_event(
                type_="keyDown", key=char, text=char,
            ))
            await page.sleep(0.03)
            await page.send(cdp.input_.dispatch_key_event(
                type_="keyUp", key=char,
            ))

        _log(f"search: typed query '{query}', waiting for results", verbose)
        await page.sleep(3)  # Wait for search results to load

        # Extract search results from the dialog
        results = await _cdp_eval(page, '''(() => {
            const results = [];

            // Look for chat links inside the search dialog
            const dialogs = document.querySelectorAll('[role="dialog"]');
            for (const dialog of dialogs) {
                const links = dialog.querySelectorAll('a[href*="/c/"]');
                for (const a of links) {
                    const href = a.getAttribute('href') || '';
                    const text = (a.innerText || '').trim().substring(0, 200);
                    if (!text || text.length < 2) continue;
                    const match = href.match(/\\/c\\/([a-zA-Z0-9-]+)/);
                    const chatId = match ? match[1] : '';
                    results.push({id: chatId, title: text, url: href});
                }
            }

            // If no links found in dialog, check any visible search results
            if (results.length === 0) {
                const allLinks = document.querySelectorAll('a[href*="/c/"]');
                for (const a of allLinks) {
                    const href = a.getAttribute('href') || '';
                    const text = (a.innerText || '').trim().substring(0, 200);
                    if (!text || text.length < 2) continue;
                    const r = a.getBoundingClientRect();
                    // Only include visible links (in viewport)
                    if (r.width > 0 && r.height > 0 && r.y > 0 && r.y < window.innerHeight) {
                        const match = href.match(/\\/c\\/([a-zA-Z0-9-]+)/);
                        const chatId = match ? match[1] : '';
                        results.push({id: chatId, title: text, url: href});
                    }
                }
            }

            return results;
        })()''')

        _log(f"search: found {len(results or [])} results", verbose)

        # Close the search dialog
        await page.send(cdp.input_.dispatch_key_event(
            type_="keyDown", key="Escape", code="Escape",
            windows_virtual_key_code=27, native_virtual_key_code=27,
        ))

        chats = []
        for r in (results or [])[:limit]:
            chats.append({
                'id': r.get('id', ''),
                'title': r.get('title', 'Untitled'),
                'url': r.get('url', ''),
            })

        return {
            "success": True,
            "query": query,
            "chats": chats,
            "count": len(chats),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}

    finally:
        if browser:
            browser.stop()


async def list_chatgpt_projects(
    headless: bool | None = None,
    show_browser: bool = False,
    verbose: bool = False,
) -> dict:
    """
    List ChatGPT Projects from the sidebar.

    Projects appear under a collapsible "Projects" section and have
    URLs matching /g/g-p-{uuid}-{slug}/project.

    Returns:
        dict with success status and list of projects.
    """
    setup = await _setup_authenticated_browser(
        headless=headless,
        show_browser=show_browser,
        verbose=verbose,
    )
    if not setup["success"]:
        return setup

    browser = setup["browser"]
    page = setup["page"]

    try:
        await page.sleep(3)

        # Ensure the Projects section is expanded by clicking the button
        projects_btn = await _cdp_eval(page, '''(() => {
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                const text = (btn.innerText || '').trim();
                if (text === 'Projects') {
                    const r = btn.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        return {x: r.x + r.width / 2, y: r.y + r.height / 2};
                    }
                }
            }
            return null;
        })()''')

        if projects_btn:
            _log(f"list_projects: clicking Projects button at ({projects_btn['x']:.0f},{projects_btn['y']:.0f})", verbose)
            # Click to expand (if collapsed) — clicking when already expanded
            # may collapse it, so check first
            project_links_before = await _cdp_eval(page, '''(() => {
                return document.querySelectorAll('a[href*="/g/g-p-"]').length;
            })()''')

            if not project_links_before:
                await _cdp_click(page, projects_btn['x'], projects_btn['y'])
                await page.sleep(1.5)
        else:
            _log("list_projects: Projects button not found", verbose)

        # Extract project links
        projects = await _cdp_eval(page, '''(() => {
            const results = [];
            const links = document.querySelectorAll('a[href*="/g/g-p-"]');
            for (const a of links) {
                const href = a.getAttribute('href') || '';
                const text = (a.innerText || '').trim().substring(0, 200);
                if (!text || text.length < 2) continue;

                // Extract project ID and slug from URL
                // Pattern: /g/g-p-{uuid}-{slug}/project
                const match = href.match(/\\/g\\/(g-p-[a-zA-Z0-9-]+)\\/project/);
                const projectId = match ? match[1] : '';

                results.push({
                    id: projectId,
                    name: text,
                    url: href,
                });
            }
            return results;
        })()''')

        _log(f"list_projects: found {len(projects or [])} projects", verbose)

        return {
            "success": True,
            "projects": projects or [],
            "count": len(projects or []),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}

    finally:
        if browser:
            browser.stop()


def extract_code_blocks(text: str) -> list[str]:
    """Extract fenced code blocks from markdown text.

    Returns a list of code strings (without the fence markers).
    Handles ```lang and ``` fences.
    """
    blocks = []
    pattern = re.compile(r'```(?:\w*)\n(.*?)```', re.DOTALL)
    for match in pattern.finditer(text):
        code = match.group(1).rstrip('\n')
        if code:
            blocks.append(code)
    return blocks


def format_chat_export(result: dict, fmt: str) -> str:
    """Format a chat result for export.

    Args:
        result: The result dict from get_chatgpt_chat().
        fmt: One of 'md', 'json', 'txt'.

    Returns:
        Formatted string.
    """
    if fmt == "json":
        return json.dumps(result, indent=2)

    title = result.get("title", "Untitled")
    chat_id = result.get("chat_id", "")
    messages = result.get("messages", [])

    if fmt == "txt":
        lines = [f"Chat: {title}", f"ID: {chat_id}", f"Messages: {len(messages)}", ""]
        for msg in messages:
            role = msg.get("role", "unknown").upper()
            text = msg.get("text", "")
            lines.append(f"[{role}]")
            lines.append(text)
            lines.append("")
        return "\n".join(lines)

    # Default: markdown
    lines = [f"# {title}", "", f"> Chat ID: `{chat_id}`", f"> Messages: {len(messages)}", ""]
    for msg in messages:
        role = msg.get("role", "unknown")
        text = msg.get("text", "")
        if role == "user":
            lines.append(f"## User")
        else:
            lines.append(f"## Assistant")
        lines.append("")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


async def delete_or_archive_chat(
    chat_id: str,
    action: str,
    headless: bool | None = None,
    show_browser: bool = False,
    verbose: bool = False,
) -> dict:
    """Delete or archive a ChatGPT conversation via the sidebar hover menu.

    Args:
        chat_id: Chat identifier (idx-N, title substring, or UUID).
        action: Either 'delete' or 'archive'.

    Returns:
        dict with success status.
    """
    setup = await _setup_authenticated_browser(
        headless=headless,
        show_browser=show_browser,
        verbose=verbose,
    )
    if not setup["success"]:
        return setup

    browser = setup["browser"]
    page = setup["page"]

    try:
        await page.sleep(3)

        # Resolve the chat ID to find the sidebar link
        resolved_id = chat_id
        idx_match = re.match(r'^idx-(\d+)$', chat_id)
        if idx_match or not re.match(r'^[a-zA-Z0-9-]{20,}$', chat_id):
            chat_links = await _cdp_eval(page, '''(() => {
                const results = [];
                const links = document.querySelectorAll('a[href*="/c/"]');
                for (const a of links) {
                    const href = a.getAttribute('href') || '';
                    const text = (a.innerText || '').trim().substring(0, 200);
                    if (!text || text.length < 2) continue;
                    const match = href.match(/\\/c\\/([a-zA-Z0-9-]+)/);
                    const chatId = match ? match[1] : '';
                    const r = a.getBoundingClientRect();
                    results.push({id: chatId, title: text, x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height});
                }
                return results;
            })()''')

            if idx_match:
                chat_index = int(idx_match.group(1))
                if not chat_links or chat_index >= len(chat_links):
                    return {"success": False, "error": f"Chat index {chat_index} out of range"}
                target = chat_links[chat_index]
            else:
                target = None
                for link in (chat_links or []):
                    if chat_id.lower() in link['title'].lower():
                        target = link
                        break
                if not target:
                    return {"success": False, "error": f"Chat '{chat_id}' not found in sidebar"}
            resolved_id = target['id']
        else:
            # Have a UUID — find it in the sidebar
            target_info = await _cdp_eval(page, f'''(() => {{
                const links = document.querySelectorAll('a[href*="/c/{resolved_id}"]');
                for (const a of links) {{
                    const r = a.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {{
                        return {{x: r.x + r.width / 2, y: r.y + r.height / 2, title: (a.innerText || '').trim()}};
                    }}
                }}
                return null;
            }})()''')
            if not target_info:
                return {"success": False, "error": f"Chat '{resolved_id}' not visible in sidebar"}
            target = {'id': resolved_id, 'title': target_info['title'], 'x': target_info['x'], 'y': target_info['y']}

        _log(f"{action}: targeting chat '{target['title']}' ({resolved_id})", verbose)

        # Hover over the chat link to reveal the options button
        await page.send(cdp.input_.dispatch_mouse_event(
            type_="mouseMoved", x=target['x'], y=target['y'],
        ))
        await page.sleep(0.5)

        # Look for the options button (three dots) that appears on hover
        options_btn = await _cdp_eval(page, f'''(() => {{
            // Look for options button near the hovered chat
            const btns = document.querySelectorAll('button[data-testid*="history-item"][data-testid*="options"]');
            for (const btn of btns) {{
                const r = btn.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {{
                    return {{x: r.x + r.width / 2, y: r.y + r.height / 2, testId: btn.getAttribute('data-testid')}};
                }}
            }}
            // Fallback: any visible button near the chat that looks like options
            const allBtns = document.querySelectorAll('button[aria-label*="Options"], button[aria-haspopup="menu"]');
            for (const btn of allBtns) {{
                const r = btn.getBoundingClientRect();
                if (r.width > 0 && r.height > 0 && Math.abs(r.y - {target['y']}) < 30) {{
                    return {{x: r.x + r.width / 2, y: r.y + r.height / 2, testId: btn.getAttribute('data-testid') || ''}};
                }}
            }}
            return null;
        }})()''')

        if not options_btn:
            return {"success": False, "error": f"Could not find options button for chat '{target['title']}'"}

        _log(f"{action}: clicking options button at ({options_btn['x']:.0f},{options_btn['y']:.0f})", verbose)
        await _cdp_click(page, options_btn['x'], options_btn['y'])
        await page.sleep(1)

        # Find the delete/archive menu item
        action_label = "Delete" if action == "delete" else "Archive"
        menu_item = await _cdp_eval(page, f'''(() => {{
            const items = document.querySelectorAll('[role="menuitem"], [role="option"], button');
            for (const item of items) {{
                const text = (item.innerText || '').trim();
                if (text.toLowerCase().includes('{action_label.lower()}')) {{
                    const r = item.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {{
                        return {{x: r.x + r.width / 2, y: r.y + r.height / 2, text: text}};
                    }}
                }}
            }}
            return null;
        }})()''')

        if not menu_item:
            return {"success": False, "error": f"Could not find '{action_label}' in menu"}

        _log(f"{action}: clicking '{menu_item['text']}' menu item", verbose)
        await _cdp_click(page, menu_item['x'], menu_item['y'])
        await page.sleep(1)

        # Handle confirmation dialog (delete has one, archive may not)
        if action == "delete":
            confirm_btn = await _cdp_eval(page, '''(() => {
                const btns = document.querySelectorAll('button');
                for (const btn of btns) {
                    const text = (btn.innerText || '').trim().toLowerCase();
                    if (text === 'delete' || text === 'confirm') {
                        const r = btn.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            return {x: r.x + r.width / 2, y: r.y + r.height / 2};
                        }
                    }
                }
                return null;
            })()''')

            if confirm_btn:
                _log(f"{action}: confirming deletion", verbose)
                await _cdp_click(page, confirm_btn['x'], confirm_btn['y'])
                await page.sleep(1)

        return {
            "success": True,
            "action": action,
            "chat_id": resolved_id,
            "title": target['title'],
        }

    except Exception as e:
        return {"success": False, "error": str(e)}

    finally:
        if browser:
            browser.stop()


# ── CLI ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Send prompts to ChatGPT via CLI, or browse chat history",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Send a prompt (new chat)
  python chatgpt.py --prompt "What is the capital of France?"
  python chatgpt.py --prompt "Complex problem" --model gpt-5.2-pro --timeout 1800

  # Force fresh conversation
  python chatgpt.py --prompt "Hello" --new-chat --show-browser

  # Continue an existing conversation
  python chatgpt.py --continue-chat idx-0 --prompt "Follow-up question"
  python chatgpt.py --continue-chat "quantum" --prompt "Tell me more"

  # Search and browse chats
  python chatgpt.py --search-chats "quantum" --json
  python chatgpt.py --list-chats --show-browser --json
  python chatgpt.py --get-chat CHAT_ID --show-browser --raw

  # Projects
  python chatgpt.py --list-projects
  python chatgpt.py --project "OmniModel" --prompt "Summarize this project"

  # Export, delete, archive
  python chatgpt.py --export idx-0 --format md
  python chatgpt.py --export "quantum" --format json > chat.json
  python chatgpt.py --delete-chat idx-5
  python chatgpt.py --archive-chat "old project"

  # File and image upload
  python chatgpt.py --prompt "Summarize this file" --file report.pdf
  python chatgpt.py --prompt "Review this code" --file main.py --file utils.py
  python chatgpt.py --prompt "What's in this image?" --image photo.jpg
  python chatgpt.py --prompt "Compare these" --image a.png --image b.png

  # Code extraction and toggles
  python chatgpt.py --prompt "Write a Python sort" --code-only
  python chatgpt.py --prompt "One-off question" --temp-chat
  python chatgpt.py --prompt "Latest news on AI" --search
  python chatgpt.py --prompt "What is 2+2" --no-search

Models (GPT-5.2 thinking modes):
  auto         Decides how long to think (default)
  instant      Answers right away
  thinking     Thinks longer for better answers
  pro          Research-grade intelligence (up to 30min)

Legacy models (behind submenu):
  o3           Reasoning model
  gpt-4.5      GPT-4.5
  gpt-5.1-pro  GPT-5.1 Pro reasoning

Output:
  By default, prints only the response text.
  Use --json for full JSON output with metadata.
"""
    )

    # Prompt (can be used standalone or with --continue-chat)
    parser.add_argument("--prompt", "-p",
                        help="The prompt to send to ChatGPT")

    # Browse modes (mutually exclusive with each other)
    browse_group = parser.add_mutually_exclusive_group()
    browse_group.add_argument("--list-chats", action="store_true",
                              help="List recent ChatGPT conversations from sidebar")
    browse_group.add_argument("--get-chat",
                              metavar="CHAT_ID",
                              help="Retrieve conversation by index (idx-N), title, or conversation ID")
    browse_group.add_argument("--search-chats",
                              metavar="QUERY",
                              help="Search ChatGPT conversations by keyword")
    browse_group.add_argument("--list-projects", action="store_true",
                              help="List ChatGPT Projects from sidebar")
    browse_group.add_argument("--export",
                              metavar="CHAT_ID",
                              help="Export conversation as markdown, JSON, or text (use --format)")
    browse_group.add_argument("--delete-chat",
                              metavar="CHAT_ID",
                              help="Delete a conversation (by index, title, or ID)")
    browse_group.add_argument("--archive-chat",
                              metavar="CHAT_ID",
                              help="Archive a conversation (by index, title, or ID)")

    # Chat navigation
    parser.add_argument("--continue-chat",
                        metavar="CHAT_ID",
                        help="Continue existing conversation (by index, title, or ID). Requires --prompt.")
    parser.add_argument("--new-chat", action="store_true",
                        help="Force a fresh conversation (useful with --prompt)")
    parser.add_argument("--project",
                        metavar="NAME",
                        help="Send prompt within a ChatGPT Project context (by name or ID). Requires --prompt.")

    # Shared options
    parser.add_argument("--timeout", "-t", type=int,
                        help="Response timeout in seconds (default: model-dependent)")
    parser.add_argument("--screenshot", "-s",
                        help="Save screenshot to this path")
    parser.add_argument("--show-browser", action="store_true",
                        help="Show browser window (recommended for first use)")
    parser.add_argument("--headless", action="store_true",
                        help="Run headless (may be blocked by Cloudflare)")
    parser.add_argument("--json", action="store_true",
                        help="Output full JSON response")
    parser.add_argument("--raw", action="store_true",
                        help="Output raw response text only (no formatting)")
    parser.add_argument("--code-only", action="store_true",
                        help="Extract only fenced code blocks from response")
    parser.add_argument("--model", "-m",
                        choices=list(CHATGPT_MODELS.keys()),
                        default=DEFAULT_MODEL,
                        help=f"ChatGPT model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--session-id",
                        help="Unique session ID for concurrent queries")
    parser.add_argument("--limit", type=int, default=50,
                        help="Max number of chats to list (default: 50, used with --list-chats)")
    parser.add_argument("--format", "-f",
                        choices=["md", "json", "txt"],
                        default="md",
                        help="Export format (default: md, used with --export)")
    parser.add_argument("--temp-chat", action="store_true",
                        help="Enable temporary chat mode (conversation not saved to history)")
    parser.add_argument("--file", action="append", metavar="PATH",
                        help="Upload file(s) with the prompt (can be used multiple times)")
    parser.add_argument("--image", action="append", metavar="PATH",
                        help="Upload image(s) for vision analysis (can be used multiple times)")
    search_group = parser.add_mutually_exclusive_group()
    search_group.add_argument("--search", action="store_true",
                              help="Enable web search for this prompt")
    search_group.add_argument("--no-search", action="store_true",
                              help="Disable web search for this prompt")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Enable debug logging to stderr")
    parser.add_argument("--mode",
                        choices=["api", "browser", "auto"],
                        default="auto",
                        help="Execution mode: 'api' (fast HTTP, no browser), "
                             "'browser' (stealth browser), 'auto' (try API, "
                             "fall back to browser). Default: auto")

    args = parser.parse_args()

    # Validate argument combinations
    if args.continue_chat and not args.prompt:
        parser.error("--continue-chat requires --prompt")
    if args.new_chat and not args.prompt:
        parser.error("--new-chat requires --prompt")
    if args.new_chat and args.continue_chat:
        parser.error("--new-chat and --continue-chat are mutually exclusive")
    if args.project and not args.prompt:
        parser.error("--project requires --prompt")
    if args.project and args.continue_chat:
        parser.error("--project and --continue-chat are mutually exclusive")
    if args.temp_chat and not args.prompt:
        parser.error("--temp-chat requires --prompt")
    if (args.search or args.no_search) and not args.prompt:
        parser.error("--search/--no-search requires --prompt")
    if (args.file or args.image) and not args.prompt:
        parser.error("--file/--image requires --prompt")
    # Validate file paths exist
    for fpath in (args.file or []) + (args.image or []):
        if not Path(fpath).exists():
            parser.error(f"File not found: {fpath}")
    has_mode = args.prompt or args.list_chats or args.get_chat or args.search_chats or args.list_projects or args.export or args.delete_chat or args.archive_chat
    if not has_mode:
        parser.error("one of --prompt, --list-chats, --get-chat, --search-chats, --list-projects, --export, --delete-chat, or --archive-chat is required")

    # ── List chats mode ───────────────────────────────────────────
    if args.list_chats:
        result = asyncio.run(list_chatgpt_chats(
            show_browser=args.show_browser,
            limit=args.limit,
            verbose=args.verbose,
        ))

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("success"):
                chats = result.get("chats", [])
                if not chats:
                    print("No chats found in sidebar.")
                else:
                    print(f"\nFound {len(chats)} chat(s):\n")
                    for i, chat in enumerate(chats, 1):
                        title = chat.get("title", "Untitled")
                        chat_id = chat.get("id", "?")
                        date = chat.get("date", "")
                        date_str = f"  ({date})" if date else ""
                        # Show short ID for display
                        display_id = chat_id[:12] + "..." if len(chat_id) > 15 else chat_id
                        print(f"  {i:3d}. [{display_id}] {title}{date_str}")
                    print(f"\nUse --get-chat <CHAT_ID> to retrieve a conversation.")
            else:
                print(f"Error: {result.get('error')}", file=sys.stderr)
                sys.exit(1)
        return

    # ── Search chats mode ────────────────────────────────────────────
    if args.search_chats:
        result = asyncio.run(search_chatgpt_chats(
            query=args.search_chats,
            show_browser=args.show_browser,
            limit=args.limit,
            verbose=args.verbose,
        ))

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("success"):
                chats = result.get("chats", [])
                if not chats:
                    print(f"No chats matching '{args.search_chats}'.")
                else:
                    print(f"\nFound {len(chats)} chat(s) matching '{args.search_chats}':\n")
                    for i, chat in enumerate(chats, 1):
                        title = chat.get("title", "Untitled")
                        chat_id = chat.get("id", "?")
                        display_id = chat_id[:12] + "..." if len(chat_id) > 15 else chat_id
                        print(f"  {i:3d}. [{display_id}] {title}")
                    print(f"\nUse --get-chat <CHAT_ID> to retrieve a conversation.")
            else:
                print(f"Error: {result.get('error')}", file=sys.stderr)
                sys.exit(1)
        return

    # ── List projects mode ─────────────────────────────────────────
    if args.list_projects:
        result = asyncio.run(list_chatgpt_projects(
            show_browser=args.show_browser,
            verbose=args.verbose,
        ))

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("success"):
                projects = result.get("projects", [])
                if not projects:
                    print("No projects found.")
                else:
                    print(f"\nFound {len(projects)} project(s):\n")
                    for i, proj in enumerate(projects, 1):
                        name = proj.get("name", "Untitled")
                        pid = proj.get("id", "?")
                        print(f"  {i:3d}. [{pid}] {name}")
                    print(f"\nUse --project <NAME> --prompt <TEXT> to send a prompt within a project.")
            else:
                print(f"Error: {result.get('error')}", file=sys.stderr)
                sys.exit(1)
        return

    # ── Export chat mode ───────────────────────────────────────────
    if args.export:
        timeout = args.timeout or 60
        result = asyncio.run(get_chatgpt_chat(
            chat_id=args.export,
            show_browser=args.show_browser,
            timeout=timeout,
            verbose=args.verbose,
        ))

        if not result.get("success"):
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)

        output = format_chat_export(result, args.format)
        print(output)
        return

    # ── Delete chat mode ──────────────────────────────────────────
    if args.delete_chat:
        result = asyncio.run(delete_or_archive_chat(
            chat_id=args.delete_chat,
            action="delete",
            show_browser=args.show_browser,
            verbose=args.verbose,
        ))

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("success"):
                print(f"Deleted chat '{result.get('title', '')}' ({result.get('chat_id', '')})")
            else:
                print(f"Error: {result.get('error')}", file=sys.stderr)
                sys.exit(1)
        return

    # ── Archive chat mode ─────────────────────────────────────────
    if args.archive_chat:
        result = asyncio.run(delete_or_archive_chat(
            chat_id=args.archive_chat,
            action="archive",
            show_browser=args.show_browser,
            verbose=args.verbose,
        ))

        if args.json:
            print(json.dumps(result, indent=2))
        else:
            if result.get("success"):
                print(f"Archived chat '{result.get('title', '')}' ({result.get('chat_id', '')})")
            else:
                print(f"Error: {result.get('error')}", file=sys.stderr)
                sys.exit(1)
        return

    # ── Get chat mode ─────────────────────────────────────────────
    if args.get_chat:
        timeout = args.timeout or 60
        result = asyncio.run(get_chatgpt_chat(
            chat_id=args.get_chat,
            show_browser=args.show_browser,
            timeout=timeout,
            verbose=args.verbose,
        ))

        if args.json:
            print(json.dumps(result, indent=2))
        elif args.raw:
            if result.get("success"):
                for msg in result.get("messages", []):
                    role = msg.get("role", "unknown").upper()
                    text = msg.get("text", "")
                    print(f"[{role}]\n{text}\n")
            else:
                print(f"Error: {result.get('error')}", file=sys.stderr)
                sys.exit(1)
        else:
            if result.get("success"):
                title = result.get("title", "Untitled")
                messages = result.get("messages", [])
                print(f"\n{'=' * 60}")
                print(f"Chat: {title}")
                print(f"ID:   {result.get('chat_id')}")
                print(f"Messages: {len(messages)}")
                print(f"{'=' * 60}\n")
                for msg in messages:
                    role = msg.get("role", "unknown").upper()
                    text = msg.get("text", "")
                    print(f"── {role} ──")
                    print(text)
                    print()
                print(f"{'=' * 60}")
            else:
                print(f"Error: {result.get('error')}", file=sys.stderr)
                sys.exit(1)
        return

    # ── Prompt mode (default or continue) ──────────────────────────
    # Merge --file and --image into a single list for upload
    all_files = (args.file or []) + (args.image or [])

    # Determine if API mode is usable for this request.
    # Browser-only features: file upload, continue-chat, project,
    # temp-chat, web search toggle, show-browser, screenshot.
    browser_only = bool(
        all_files or args.continue_chat or args.project or
        args.temp_chat or args.search or args.no_search or
        args.show_browser or args.screenshot
    )

    use_api = (
        args.mode in ("api", "auto")
        and not browser_only
        and args.prompt
    )

    if use_api:
        from api_client import chatgpt_api_prompt
        _log("Using API mode (fast HTTP, no browser)", args.verbose)

        result = asyncio.run(chatgpt_api_prompt(
            prompt=args.prompt,
            model=args.model,
            timeout=args.timeout,
            verbose=args.verbose,
        ))

        # Auto mode: fall back to browser if API fails
        if not result.get("success") and args.mode == "auto":
            _log(f"API mode failed: {result.get('error')}. Falling back to browser.", args.verbose)
            result = asyncio.run(prompt_chatgpt(
                prompt=args.prompt,
                headless=args.headless,
                timeout=args.timeout,
                screenshot=args.screenshot,
                show_browser=args.show_browser,
                model=args.model,
                session_id=args.session_id,
                verbose=args.verbose,
                new_chat=args.new_chat,
            ))
    else:
        if args.mode == "api" and browser_only:
            _log("WARNING: API mode requested but browser-only features used. Using browser.", args.verbose)

        result = asyncio.run(prompt_chatgpt(
            prompt=args.prompt,
            headless=args.headless,
            timeout=args.timeout,
            screenshot=args.screenshot,
            show_browser=args.show_browser,
            model=args.model,
            session_id=args.session_id,
            verbose=args.verbose,
            new_chat=args.new_chat,
            continue_chat_id=args.continue_chat,
            project=args.project,
            temp_chat=args.temp_chat,
            web_search=True if args.search else (False if args.no_search else None),
            files=all_files if all_files else None,
        ))

    if args.json:
        if args.code_only and result.get("success"):
            blocks = extract_code_blocks(result.get("response", ""))
            result["code_blocks"] = blocks
            result["response"] = "\n\n".join(blocks) if blocks else result.get("response", "")
        print(json.dumps(result, indent=2))
    elif args.code_only:
        if result.get("success"):
            blocks = extract_code_blocks(result.get("response", ""))
            if blocks:
                print("\n\n".join(blocks))
            else:
                print("(no code blocks found in response)", file=sys.stderr)
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)
    else:
        if result.get("success"):
            if args.raw:
                print(result["response"])
            else:
                print("\n" + "=" * 60)
                print(f"Prompt: {args.prompt[:50]}{'...' if len(args.prompt) > 50 else ''}")
                print(f"Model: {result.get('model', 'unknown')}")
                mode_label = result.get('mode', 'browser')
                print(f"Mode: {mode_label}")
                if result.get("thinking_time_seconds"):
                    print(f"Thinking time: {result['thinking_time_seconds']}s")
                print(f"Total time: {result.get('total_time_seconds', 0)}s")
                tokens = result.get("tokens", {})
                print(f"Tokens: ~{tokens.get('total', 0)} (response: {tokens.get('response', 0)})")
                print("=" * 60)
                print()
                print(result["response"])
                print()
                print("=" * 60)
        else:
            print(f"Error: {result.get('error')}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
