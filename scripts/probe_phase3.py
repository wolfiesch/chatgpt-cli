#!/usr/bin/env python3
"""
DOM Probe: Phase 3 selector verification for ChatGPT CLI.

Probes the live ChatGPT DOM for:
1. Temp chat toggle - selectors for temporary chat mode
2. Search toggle - selectors for web search toggle
3. Hover menu - sidebar chat options button (for delete/archive)
4. Toolbar buttons - any buttons near the input area

Usage:
    python3 scripts/run.py probe_phase3.py [--timeout 20]
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
    clean_browser_locks,
)
from chrome_cookies import extract_cookies as extract_chrome_cookies


async def _cdp_run_js(page, expression: str):
    """Run JavaScript on page via CDP Runtime.evaluate."""
    try:
        result, _exceptions = await page.send(cdp.runtime.evaluate(expression))
        if result and result.value is not None:
            return result.value
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


def section(title):
    print(f"\n{'=' * 60}")
    print(title)
    print('=' * 60)


async def probe_selectors(page, title, selectors):
    """Probe a list of CSS selectors and report findings."""
    print(f"\n--- {title} ---")
    found_any = False
    for sel in selectors:
        try:
            results = await _cdp_run_js(page, f'''(() => {{
                const els = document.querySelectorAll('{sel}');
                if (els.length === 0) return null;
                return Array.from(els).slice(0, 5).map(el => {{
                    const r = el.getBoundingClientRect();
                    return {{
                        tag: el.tagName,
                        text: (el.innerText || '').trim().substring(0, 80),
                        testId: el.getAttribute('data-testid') || '',
                        ariaLabel: el.getAttribute('aria-label') || '',
                        ariaChecked: el.getAttribute('aria-checked') || '',
                        ariaPressed: el.getAttribute('aria-pressed') || '',
                        role: el.getAttribute('role') || '',
                        dataState: el.getAttribute('data-state') || '',
                        classes: (el.className || '').toString().substring(0, 100),
                        visible: r.width > 0 && r.height > 0,
                        rect: `${{Math.round(r.x)}},${{Math.round(r.y)}} ${{Math.round(r.width)}}x${{Math.round(r.height)}}`,
                    }};
                }});
            }})()''')
            if results:
                found_any = True
                print(f"  + {sel}: {len(results)} match(es)")
                for i, r in enumerate(results):
                    vis = "VISIBLE" if r['visible'] else "hidden"
                    attrs = []
                    if r['testId']:
                        attrs.append(f"testid={r['testId']}")
                    if r['ariaLabel']:
                        attrs.append(f"label={r['ariaLabel']}")
                    if r['ariaChecked']:
                        attrs.append(f"checked={r['ariaChecked']}")
                    if r['ariaPressed']:
                        attrs.append(f"pressed={r['ariaPressed']}")
                    if r['role']:
                        attrs.append(f"role={r['role']}")
                    if r['dataState']:
                        attrs.append(f"state={r['dataState']}")
                    attr_str = " ".join(attrs) if attrs else ""
                    print(f"    [{i}] <{r['tag']}> {vis} @ {r['rect']} {attr_str}")
                    if r['text']:
                        print(f"        text=\"{r['text'][:60]}\"")
            else:
                print(f"  - {sel}: 0 matches")
        except Exception as e:
            print(f"  - {sel}: ERROR ({e})")
    return found_any


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

    clean_browser_locks()

    print("Launching browser (visible)...")
    browser = await uc.start(
        headless=False,
        user_data_dir=str(USER_DATA_DIR),
        browser_args=BROWSER_ARGS,
    )

    page = await browser.get(CHATGPT_URL)
    await page.sleep(1)

    # Inject cookies
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

    page = await browser.get(CHATGPT_URL)
    await page.sleep(5)

    current_url = page.url or "unknown"
    print(f"Current URL: {current_url}")

    ready_state = await _cdp_run_js(page, 'document.readyState') or "unknown"
    print(f"document.readyState: {ready_state}")

    # Check for Cloudflare / login redirect
    page_text = await _cdp_run_js(page, "document.body ? document.body.innerText : ''") or ""
    if "verify you are human" in page_text.lower():
        print("CLOUDFLARE CHALLENGE DETECTED — waiting for user to solve...")
        await page.sleep(15)
        page_text = await _cdp_run_js(page, "document.body ? document.body.innerText : ''") or ""
    if "/auth/login" in current_url:
        print("REDIRECTED TO LOGIN — cookies stale!")
        browser.stop()
        return

    # Dismiss modals
    await _cdp_run_js(page, '''(() => {
        document.dispatchEvent(new KeyboardEvent('keydown', {
            key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true
        }));
    })()''')
    await page.sleep(0.5)

    # ══════════════════════════════════════════════════════════
    # PROBE 1: TEMP CHAT TOGGLE
    # ══════════════════════════════════════════════════════════
    section("PROBE 1: TEMPORARY CHAT TOGGLE")

    await probe_selectors(page, "Speculative selectors (from chatgpt.py)", [
        '[data-testid*="temp"]',
        '[data-testid*="temporary"]',
        'button[aria-label*="emporary"]',
        'label[for*="temp"]',
        'div[role="switch"]',
    ])

    # Broader search for anything "temporary" related
    temp_scan = await _cdp_run_js(page, '''(() => {
        const results = [];
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const text = (el.innerText || '').trim().toLowerCase();
            const testId = el.getAttribute('data-testid') || '';
            const ariaLabel = el.getAttribute('aria-label') || '';
            if (testId.includes('temp') || ariaLabel.includes('emporary') ||
                (text.includes('temporary') && text.length < 50)) {
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    results.push({
                        tag: el.tagName, text: text.substring(0, 60),
                        testId: testId, ariaLabel: ariaLabel,
                        rect: `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}`,
                    });
                }
            }
        }
        return results;
    })()''')
    print(f"\n  Broad scan for 'temporary' anywhere: {len(temp_scan or [])} elements")
    for item in (temp_scan or []):
        print(f"    <{item['tag']}> testid={item['testId']} label={item['ariaLabel']} @ {item['rect']}")
        if item['text']:
            print(f"        text=\"{item['text']}\"")

    # ══════════════════════════════════════════════════════════
    # PROBE 2: SEARCH TOGGLE
    # ══════════════════════════════════════════════════════════
    section("PROBE 2: WEB SEARCH TOGGLE")

    await probe_selectors(page, "Speculative selectors (from chatgpt.py)", [
        '[data-testid*="search"]',
        '[data-testid*="web-search"]',
        'button[aria-label*="earch"]',
        '[role="switch"][aria-label*="earch"]',
    ])

    # Look for toolbar buttons near input area
    toolbar_scan = await _cdp_run_js(page, '''(() => {
        const results = [];
        const btns = document.querySelectorAll('button');
        for (const btn of btns) {
            const text = (btn.innerText || '').trim().toLowerCase();
            const testId = btn.getAttribute('data-testid') || '';
            const ariaLabel = btn.getAttribute('aria-label') || '';
            if (text.includes('search') || testId.includes('search') ||
                ariaLabel.includes('earch') || ariaLabel.includes('web')) {
                const r = btn.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    results.push({
                        tag: 'BUTTON', text: text.substring(0, 60),
                        testId: testId, ariaLabel: ariaLabel,
                        ariaPressed: btn.getAttribute('aria-pressed') || '',
                        ariaChecked: btn.getAttribute('aria-checked') || '',
                        rect: `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}`,
                    });
                }
            }
        }
        return results;
    })()''')
    print(f"\n  Search-related buttons: {len(toolbar_scan or [])} found")
    for item in (toolbar_scan or []):
        print(f"    <BUTTON> testid={item['testId']} label=\"{item['ariaLabel']}\" pressed={item['ariaPressed']} @ {item['rect']}")
        if item['text']:
            print(f"        text=\"{item['text']}\"")

    # ══════════════════════════════════════════════════════════
    # PROBE 3: ALL TOOLBAR/ACTION BUTTONS NEAR INPUT
    # ══════════════════════════════════════════════════════════
    section("PROBE 3: ALL BUTTONS NEAR INPUT AREA")

    input_area_buttons = await _cdp_run_js(page, '''(() => {
        // Find the input area (ProseMirror editor)
        const input = document.querySelector('#prompt-textarea, [contenteditable="true"]');
        if (!input) return {error: "no input found"};
        const inputRect = input.getBoundingClientRect();
        const results = [];
        // Look for buttons within 200px vertically of the input
        const btns = document.querySelectorAll('button');
        for (const btn of btns) {
            const r = btn.getBoundingClientRect();
            if (r.width > 0 && r.height > 0 && Math.abs(r.y - inputRect.y) < 200) {
                results.push({
                    text: (btn.innerText || '').trim().substring(0, 40),
                    testId: btn.getAttribute('data-testid') || '',
                    ariaLabel: btn.getAttribute('aria-label') || '',
                    ariaPressed: btn.getAttribute('aria-pressed') || '',
                    ariaChecked: btn.getAttribute('aria-checked') || '',
                    role: btn.getAttribute('role') || '',
                    rect: `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}`,
                });
            }
        }
        return {inputRect: `${Math.round(inputRect.x)},${Math.round(inputRect.y)} ${Math.round(inputRect.width)}x${Math.round(inputRect.height)}`, buttons: results};
    })()''')
    if isinstance(input_area_buttons, dict) and 'error' in input_area_buttons:
        print(f"  ERROR: {input_area_buttons['error']}")
    elif isinstance(input_area_buttons, dict):
        print(f"  Input area at: {input_area_buttons.get('inputRect', 'unknown')}")
        btns = input_area_buttons.get('buttons', [])
        print(f"  Buttons within 200px: {len(btns)}")
        for b in btns:
            attrs = []
            if b['testId']:
                attrs.append(f"testid={b['testId']}")
            if b['ariaLabel']:
                attrs.append(f"label=\"{b['ariaLabel']}\"")
            if b['ariaPressed']:
                attrs.append(f"pressed={b['ariaPressed']}")
            print(f"    [{b['rect']}] {' '.join(attrs)} text=\"{b['text']}\"")

    # ══════════════════════════════════════════════════════════
    # PROBE 4: SIDEBAR HOVER MENU (for delete/archive)
    # ══════════════════════════════════════════════════════════
    section("PROBE 4: SIDEBAR HOVER MENU")

    # First get the first chat link position
    first_chat = await _cdp_run_js(page, '''(() => {
        const links = document.querySelectorAll('a[href*="/c/"]');
        for (const a of links) {
            const text = (a.innerText || '').trim();
            if (text.length < 2) continue;
            const r = a.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {
                return {
                    x: r.x + r.width / 2, y: r.y + r.height / 2,
                    text: text.substring(0, 60), w: r.width, h: r.height,
                    href: a.getAttribute('href'),
                };
            }
        }
        return null;
    })()''')

    if not first_chat:
        print("  No sidebar chat links found! Cannot probe hover menu.")
    else:
        print(f"  First chat: \"{first_chat['text']}\" at ({first_chat['x']:.0f},{first_chat['y']:.0f})")

        # Hover over it
        await page.send(cdp.input_.dispatch_mouse_event(
            type_="mouseMoved", x=first_chat['x'], y=first_chat['y'],
        ))
        await page.sleep(1)

        # Check for options button
        await probe_selectors(page, "Options button selectors", [
            'button[data-testid*="history-item"][data-testid*="options"]',
            'button[aria-label*="Options"]',
            'button[aria-haspopup="menu"]',
            'button[data-testid*="options"]',
            'button[data-testid*="more"]',
        ])

        # Broad scan for any newly visible buttons near the hovered chat
        hover_buttons = await _cdp_run_js(page, f'''(() => {{
            const results = [];
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {{
                const r = btn.getBoundingClientRect();
                if (r.width > 0 && r.height > 0 && Math.abs(r.y - {first_chat['y']}) < 30) {{
                    results.push({{
                        text: (btn.innerText || '').trim().substring(0, 40),
                        testId: btn.getAttribute('data-testid') || '',
                        ariaLabel: btn.getAttribute('aria-label') || '',
                        ariaHaspopup: btn.getAttribute('aria-haspopup') || '',
                        rect: `${{Math.round(r.x)}},${{Math.round(r.y)}} ${{Math.round(r.width)}}x${{Math.round(r.height)}}`,
                    }});
                }}
            }}
            return results;
        }})()''')
        print(f"\n  Buttons near hovered chat (within 30px): {len(hover_buttons or [])} found")
        for b in (hover_buttons or []):
            attrs = []
            if b['testId']:
                attrs.append(f"testid={b['testId']}")
            if b['ariaLabel']:
                attrs.append(f"label=\"{b['ariaLabel']}\"")
            if b['ariaHaspopup']:
                attrs.append(f"haspopup={b['ariaHaspopup']}")
            print(f"    [{b['rect']}] {' '.join(attrs)} text=\"{b['text']}\"")

        # If we found any button, click it and inspect the menu
        if hover_buttons:
            # Click the last button (usually the options/three-dots)
            target_btn = hover_buttons[-1]
            print(f"\n  Clicking button: testid={target_btn['testId']} label=\"{target_btn['ariaLabel']}\"")
            coords = target_btn['rect'].split(' ')[0].split(',')
            bx, by = int(coords[0]) + 10, int(coords[1]) + 10
            # Use CDP click
            await page.send(cdp.input_.dispatch_mouse_event(type_="mousePressed", x=bx, y=by, button=cdp.input_.MouseButton("left"), click_count=1))
            await page.send(cdp.input_.dispatch_mouse_event(type_="mouseReleased", x=bx, y=by, button=cdp.input_.MouseButton("left"), click_count=1))
            await page.sleep(1)

            # Check for menu items
            menu_items = await _cdp_run_js(page, '''(() => {
                const results = [];
                const items = document.querySelectorAll('[role="menuitem"], [role="option"]');
                for (const item of items) {
                    const r = item.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        results.push({
                            text: (item.innerText || '').trim().substring(0, 60),
                            role: item.getAttribute('role') || '',
                            testId: item.getAttribute('data-testid') || '',
                            rect: `${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}`,
                        });
                    }
                }
                return results;
            })()''')
            print(f"\n  Menu items found: {len(menu_items or [])}")
            for item in (menu_items or []):
                print(f"    [{item['rect']}] role={item['role']} testid={item['testId']} text=\"{item['text']}\"")

            if not menu_items:
                # Fallback: check for any popup/dialog
                popup = await _cdp_run_js(page, '''(() => {
                    const popups = document.querySelectorAll('[role="menu"], [role="dialog"], [role="listbox"], [data-radix-popper-content-wrapper]');
                    return Array.from(popups).map(p => ({
                        tag: p.tagName,
                        role: p.getAttribute('role') || '',
                        text: (p.innerText || '').trim().substring(0, 200),
                        rect: `${Math.round(p.getBoundingClientRect().x)},${Math.round(p.getBoundingClientRect().y)}`,
                    }));
                })()''')
                print(f"  Popup/dialog/menu elements: {len(popup or [])}")
                for p in (popup or []):
                    print(f"    <{p['tag']}> role={p['role']} text=\"{p['text'][:80]}\"")

    # ══════════════════════════════════════════════════════════
    # PROBE 5: ALL data-testid ATTRIBUTES (discovery)
    # ══════════════════════════════════════════════════════════
    section("PROBE 5: ALL UNIQUE data-testid VALUES")

    testids = await _cdp_run_js(page, '''(() => {
        const els = document.querySelectorAll('[data-testid]');
        const ids = new Set();
        for (const el of els) {
            ids.add(el.getAttribute('data-testid'));
        }
        return Array.from(ids).sort();
    })()''')
    print(f"  Total unique data-testid values: {len(testids or [])}")
    for tid in (testids or []):
        print(f"    {tid}")

    # Save screenshot
    screenshot_path = "/tmp/chatgpt-probe-phase3.png"
    try:
        await page.save_screenshot(screenshot_path)
        print(f"\nScreenshot: {screenshot_path}")
    except Exception as e:
        print(f"Screenshot failed: {e}")

    print("\n" + "=" * 60)
    print("PROBE COMPLETE")
    print("=" * 60)

    browser.stop()


if __name__ == "__main__":
    asyncio.run(main())
