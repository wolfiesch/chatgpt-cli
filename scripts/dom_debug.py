#!/usr/bin/env python3
"""
Diagnostic: Dump DOM structure around ChatGPT response on chatgpt.com.
Sends "Hello", waits for response, then inspects what elements contain the text.

Usage:
    python3 scripts/run.py dom_debug.py [--timeout 20]
"""
import asyncio
import json
import sys
import time

import nodriver as uc
from nodriver import cdp

from config import (
    HEADLESS, USER_DATA_DIR, BROWSER_ARGS,
    CHATGPT_URL, CHATGPT_COOKIE_DOMAINS,
    CHATGPT_INPUT_SELECTORS, CHATGPT_SEND_SELECTORS,
    CHATGPT_RESPONSE_SELECTORS, CHATGPT_SIDEBAR_SELECTORS,
    CHATGPT_CHAT_MESSAGE_SELECTORS,
    clean_browser_locks,
)
from chrome_cookies import extract_cookies as extract_chrome_cookies


async def _cdp_run_js(page, expression: str):
    """Run JavaScript on page via CDP Runtime.evaluate.

    nodriver's page.evaluate() silently returns None on chatgpt.com
    due to execution context issues. This uses the CDP protocol directly
    which works reliably. The expression is sent to the browser's existing
    JS context - not Python's eval().
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


async def main():
    timeout = 20
    if "--timeout" in sys.argv:
        idx = sys.argv.index("--timeout")
        if idx + 1 < len(sys.argv):
            timeout = int(sys.argv[idx + 1])

    # Extract cookies
    print("Extracting cookies...")
    result = extract_chrome_cookies(CHATGPT_COOKIE_DOMAINS)
    if not result.get("success"):
        print(f"Cookie extraction failed: {result.get('error')}")
        return
    cookies = result.get("cookies", [])
    print(f"Got {len(cookies)} cookies")

    # Clean locks from crashed sessions
    clean_browser_locks()

    # Launch browser (always visible for diagnostics)
    print("Launching browser...")
    browser = await uc.start(
        headless=False,
        user_data_dir=str(USER_DATA_DIR),
        browser_args=BROWSER_ARGS,
    )

    # Navigate to ChatGPT to set domain
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
    print(f"Injected {injected} cookies")

    # Reload with cookies
    page = await browser.get(CHATGPT_URL)
    await page.sleep(5)

    # Check current URL and page state before proceeding
    current_url = page.url or "unknown"
    print(f"Current URL: {current_url}")

    # Take an early screenshot to see page state
    early_screenshot = "/tmp/chatgpt-dom-debug-early.png"
    try:
        await page.save_screenshot(early_screenshot)
        print(f"Early screenshot: {early_screenshot}")
    except Exception as e:
        print(f"Early screenshot failed: {e}")

    # Debug: check document readiness
    ready_state = await _cdp_run_js(page, 'document.readyState') or "unknown"
    print(f"document.readyState: {ready_state}")

    body_children = await _cdp_run_js(page, 'document.body ? document.body.children.length : -1')
    print(f"document.body.children.length: {body_children}")

    # Try multiple approaches to get page text
    page_text_check = await _cdp_run_js(page, "document.body ? document.body.innerText : ''") or ""
    if not page_text_check:
        # Fallback: try textContent (includes hidden elements)
        page_text_check = await _cdp_run_js(page, "document.body ? document.body.textContent : ''") or ""
        if page_text_check:
            print(f"innerText empty but textContent has {len(page_text_check)} chars")
    if not page_text_check:
        # Fallback: try getting text from the React root
        page_text_check = await _cdp_run_js(page, """(() => {
            const root = document.getElementById('__next') || document.getElementById('root') || document.getElementById('app');
            return root ? root.innerText : '';
        })()""") or ""
        if page_text_check:
            print(f"React root has {len(page_text_check)} chars")

    print(f"Page text length: {len(page_text_check)} chars")

    if "verify you are human" in page_text_check.lower():
        print("\n  CLOUDFLARE CHALLENGE DETECTED - page not loaded")
    elif "/auth/login" in current_url or "login" in current_url.lower():
        print("\n  REDIRECTED TO LOGIN - cookies may be stale")
    elif len(page_text_check) < 50:
        print(f"\n  PAGE TEXT VERY SHORT ({len(page_text_check)} chars)")
        print("  Waiting 5 more seconds for SPA hydration...")
        await page.sleep(5)
        # Try once more after extra wait
        page_text_check = await _cdp_run_js(page, "document.body ? document.body.innerText : ''") or ""
        print(f"  After extra wait: {len(page_text_check)} chars")

    # Dismiss modals
    await _cdp_run_js(page, '''(() => {
        document.dispatchEvent(new KeyboardEvent('keydown', {
            key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true
        }));
    })()''')
    await page.sleep(0.5)

    # -- SIDEBAR INSPECTION --
    print("\n" + "=" * 60)
    print("SIDEBAR / CHAT HISTORY INSPECTION")
    print("=" * 60)

    sidebar_selectors = CHATGPT_SIDEBAR_SELECTORS + [
        'nav', 'nav ol', 'nav ol li', 'nav ol li a',
        'nav a[href*="/c/"]',
        '[class*="sidebar"]', '[class*="Sidebar"]',
        '[class*="conversation"]', '[class*="Conversation"]',
        '[class*="history"]', '[class*="History"]',
    ]

    for sel in sidebar_selectors:
        try:
            count = await _cdp_run_js(page, f'''(() => {{
                return document.querySelectorAll('{sel}').length;
            }})()''')
            if count and count > 0:
                text = await _cdp_run_js(page, f'''(() => {{
                    const els = document.querySelectorAll('{sel}');
                    const results = [];
                    for (let i = 0; i < Math.min(els.length, 3); i++) {{
                        const el = els[i];
                        results.push({{
                            tag: el.tagName,
                            href: el.getAttribute('href') || '',
                            text: (el.innerText || '').substring(0, 80),
                            classes: (el.className || '').toString().substring(0, 80),
                        }});
                    }}
                    return results;
                }})()''')
                print(f"  + {sel}: {count} matches")
                for item in (text or []):
                    href = f" href={item['href']}" if item.get('href') else ''
                    print(f"    <{item['tag']}{href}> \"{item['text'][:60]}\"")
            else:
                print(f"  - {sel}: 0 matches")
        except Exception as e:
            print(f"  - {sel}: error ({e})")

    # Extract chat links specifically
    print("\n" + "-" * 60)
    print("CHAT LINKS (a[href*='/c/']):")
    print("-" * 60)
    chat_links = await _cdp_run_js(page, '''(() => {
        const links = document.querySelectorAll('a[href*="/c/"]');
        return Array.from(links).slice(0, 20).map(a => ({
            href: a.getAttribute('href'),
            text: (a.innerText || '').trim().substring(0, 100),
            parent: a.parentElement ? a.parentElement.tagName : '',
        }));
    })()''')
    for link in (chat_links or []):
        print(f"  {link['href']}  ->  \"{link['text']}\"  (parent: {link['parent']})")

    if not chat_links:
        print("  (no chat links found - sidebar may need scrolling or different selectors)")

    # -- INPUT FIELD INSPECTION --
    print("\n" + "=" * 60)
    print("INPUT FIELD INSPECTION")
    print("=" * 60)

    # Find input and send "Hello"
    input_found = False
    for sel in CHATGPT_INPUT_SELECTORS:
        try:
            el_info = await _cdp_run_js(page, f'''(() => {{
                const el = document.querySelector('{sel}');
                if (!el) return null;
                return {{
                    tag: el.tagName,
                    id: el.id,
                    classes: (el.className || '').toString().substring(0, 100),
                    contentEditable: el.contentEditable,
                    placeholder: el.getAttribute('placeholder') || el.getAttribute('data-placeholder') || '',
                }};
            }})()''')
            if el_info:
                print(f"  + {sel}")
                print(f"    tag={el_info['tag']} id={el_info['id']} editable={el_info['contentEditable']}")
                print(f"    placeholder=\"{el_info['placeholder']}\"")

                # Type "Hello" into it
                input_element = await page.select(sel, timeout=3)
                if input_element:
                    await input_element.click()
                    await page.sleep(0.3)
                    await _cdp_run_js(page, '''(() => {
                        const el = document.activeElement;
                        if (el && el.isContentEditable) {
                            while (el.firstChild) el.removeChild(el.firstChild);
                            const p = document.createElement('p');
                            p.textContent = 'Hello';
                            el.appendChild(p);
                            el.dispatchEvent(new InputEvent('input', {
                                bubbles: true, cancelable: true,
                                inputType: 'insertText', data: 'Hello'
                            }));
                        } else if (el) {
                            el.value = 'Hello';
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                        }
                    })()''')
                    input_found = True
                    break
            else:
                print(f"  - {sel}: not found")
        except Exception as e:
            print(f"  - {sel}: error ({e})")

    if not input_found:
        print("\n  ERROR: Could not find input field!")
        # Dump all potential input elements
        inputs = await _cdp_run_js(page, '''(() => {
            const result = [];
            document.querySelectorAll('textarea, [contenteditable="true"], [role="textbox"], input[type="text"]').forEach(el => {
                result.push({
                    tag: el.tagName, id: el.id,
                    classes: (el.className || '').toString().substring(0, 100),
                    placeholder: el.getAttribute('placeholder') || el.getAttribute('data-placeholder') || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    testId: el.getAttribute('data-testid') || '',
                });
            });
            return result;
        })()''')
        print("  Input-like elements found:", json.dumps(inputs, indent=2))

        # Save screenshot before exiting
        screenshot_path = "/tmp/chatgpt-dom-debug.png"
        try:
            await page.save_screenshot(screenshot_path)
            print(f"\nScreenshot saved to {screenshot_path}")
        except Exception:
            pass

        # Still dump full page text for debugging
        print("\n" + "=" * 60)
        print("FULL PAGE TEXT (for debug):")
        print("=" * 60)
        page_text = await _cdp_run_js(page, "document.body ? document.body.innerText : ''") or ""
        lines = page_text.split('\n')
        for i, line in enumerate(lines):
            if line.strip():
                print(f"  L{i:3d}: {line[:120]}")
        print(f"\nTotal chars: {len(page_text)}")

        browser.stop()
        return

    await page.sleep(1)

    # -- SEND BUTTON INSPECTION --
    print("\n" + "=" * 60)
    print("SEND BUTTON INSPECTION")
    print("=" * 60)

    sent = False
    for sel in CHATGPT_SEND_SELECTORS:
        try:
            btn_info = await _cdp_run_js(page, f'''(() => {{
                const btn = document.querySelector('{sel}');
                if (!btn) return null;
                return {{
                    tag: btn.tagName,
                    text: (btn.innerText || '').trim().substring(0, 50),
                    ariaLabel: btn.getAttribute('aria-label') || '',
                    testId: btn.getAttribute('data-testid') || '',
                    disabled: btn.disabled || false,
                }};
            }})()''')
            if btn_info:
                status = "DISABLED" if btn_info['disabled'] else "enabled"
                print(f"  + {sel} ({status})")
                print(f"    label=\"{btn_info['ariaLabel']}\" testId=\"{btn_info['testId']}\"")
                if not btn_info['disabled']:
                    btn = await page.select(sel, timeout=2)
                    if btn:
                        await btn.click()
                        sent = True
                        print(f"    -> Clicked!")
                        break
            else:
                print(f"  - {sel}: not found")
        except Exception as e:
            print(f"  - {sel}: error ({e})")

    if not sent:
        print("  Trying Enter key as fallback...")
        await _cdp_run_js(page, '''(() => {
            const el = document.activeElement;
            if (el) el.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
        })()''')

    # Wait for response
    print(f"\nWaiting {timeout} seconds for response...")
    await page.sleep(timeout)

    # Save screenshot
    screenshot_path = "/tmp/chatgpt-dom-debug.png"
    await page.save_screenshot(screenshot_path)
    print(f"Screenshot saved to {screenshot_path}")

    # -- RESPONSE CONTAINER INSPECTION --
    print("\n" + "=" * 60)
    print("RESPONSE CONTAINER INSPECTION")
    print("=" * 60)

    response_selectors = CHATGPT_RESPONSE_SELECTORS + CHATGPT_CHAT_MESSAGE_SELECTORS + [
        'div[data-message-author-role]',
        'div[data-message-author-role="assistant"]',
        'div[data-message-author-role="user"]',
        'article[data-testid*="conversation"]',
        '.agent-turn',
        '.markdown', '[class*="markdown"]',
        '.prose', '[class*="prose"]',
        '[class*="message"]', '[class*="Message"]',
        '[class*="response"]', '[class*="Response"]',
        '[class*="turn"]', '[class*="Turn"]',
        '[role="presentation"]',
    ]

    for sel in response_selectors:
        try:
            count = await _cdp_run_js(page, f'''(() => {{
                return document.querySelectorAll('{sel}').length;
            }})()''')
            if count and count > 0:
                text = await _cdp_run_js(page, f'''(() => {{
                    const els = document.querySelectorAll('{sel}');
                    return els[els.length - 1].innerText.substring(0, 120);
                }})()''')
                print(f"  + {sel}: {count} matches -> \"{text[:80]}\"")
            else:
                print(f"  - {sel}: 0 matches")
        except Exception as e:
            print(f"  - {sel}: error ({e})")

    # -- MODEL SELECTOR INSPECTION --
    print("\n" + "=" * 60)
    print("MODEL SELECTOR INSPECTION")
    print("=" * 60)

    model_selectors = [
        'button[data-testid="model-selector"]',
        'button[aria-haspopup="menu"]',
        '[class*="model"]', '[class*="Model"]',
    ]
    for sel in model_selectors:
        try:
            count = await _cdp_run_js(page, f'''(() => {{
                return document.querySelectorAll('{sel}').length;
            }})()''')
            if count and count > 0:
                text = await _cdp_run_js(page, f'''(() => {{
                    const els = document.querySelectorAll('{sel}');
                    return Array.from(els).slice(0, 3).map(e => (e.innerText || '').trim().substring(0, 60));
                }})()''')
                print(f"  + {sel}: {count} matches -> {text}")
            else:
                print(f"  - {sel}: 0 matches")
        except Exception as e:
            print(f"  - {sel}: error ({e})")

    # -- FULL PAGE TEXT --
    print("\n" + "=" * 60)
    print("FULL PAGE TEXT (for line-scanning debug):")
    print("=" * 60)
    page_text = await _cdp_run_js(page, 'document.body.innerText') or ""
    lines = page_text.split('\n')
    for i, line in enumerate(lines):
        if line.strip():
            print(f"  L{i:3d}: {line[:120]}")

    print(f"\nTotal lines: {len(lines)}")
    print(f"Total chars: {len(page_text)}")
    print(f"'Hello' present: {'Hello' in page_text}")
    print(f"'Thought for' present: {'Thought for' in page_text}")

    browser.stop()
    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
