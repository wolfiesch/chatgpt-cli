#!/usr/bin/env python3
"""
Probe: Click the composer '+' button and inspect the resulting menu.
Checks if the web search toggle is hidden behind it.

Usage:
    python3 scripts/run.py probe_plus_button.py
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
    except Exception as e:
        print(f"  JS error: {e}", file=sys.stderr)
        return None


async def _cdp_click(page, x, y):
    """Full CDP mouse click sequence (mouseMoved + mousePressed + mouseReleased)."""
    await page.send(cdp.input_.dispatch_mouse_event(
        type_="mouseMoved", x=x, y=y
    ))
    await asyncio.sleep(0.05)
    await page.send(cdp.input_.dispatch_mouse_event(
        type_="mousePressed", x=x, y=y,
        button=cdp.input_.MouseButton("left"), click_count=1
    ))
    await asyncio.sleep(0.05)
    await page.send(cdp.input_.dispatch_mouse_event(
        type_="mouseReleased", x=x, y=y,
        button=cdp.input_.MouseButton("left"), click_count=1
    ))


async def main():
    print("=" * 60)
    print("PROBE: Composer '+' Button Menu Inspection")
    print("=" * 60)

    # Setup browser
    clean_browser_locks()
    cookies = extract_chrome_cookies(CHATGPT_COOKIE_DOMAINS)
    print(f"Extracted {len(cookies)} cookies")

    browser = await uc.start(
        headless=False,
        user_data_dir=USER_DATA_DIR,
        browser_args=BROWSER_ARGS,
    )
    page = await browser.get("about:blank")

    # Inject cookies
    for c in cookies:
        try:
            params = {
                "name": c["name"], "value": c["value"],
                "domain": c["domain"], "path": c.get("path", "/"),
            }
            if c.get("secure"): params["secure"] = True
            if c.get("httpOnly"): params["httpOnly"] = True
            if c.get("sameSite"): params["sameSite"] = c["sameSite"]
            if c.get("expirationDate"):
                params["expires"] = c["expirationDate"]
            await page.send(cdp.network.set_cookie(**params))
        except Exception:
            pass

    # Navigate to ChatGPT
    page = await browser.get(CHATGPT_URL)
    await asyncio.sleep(5)

    ready = await _cdp_run_js(page, "document.readyState")
    print(f"Page readyState: {ready}")

    # Step 1: Find the '+' button
    print("\n--- Step 1: Locate composer '+' button ---")
    plus_btn = await _cdp_run_js(page, '''(() => {
        const btn = document.querySelector('[data-testid="composer-plus-btn"]');
        if (!btn) return null;
        const rect = btn.getBoundingClientRect();
        return {
            label: btn.getAttribute("aria-label") || btn.textContent.trim(),
            x: Math.round(rect.x + rect.width/2),
            y: Math.round(rect.y + rect.height/2),
            tagName: btn.tagName
        };
    })()''')

    if not plus_btn:
        print("  FAILED: composer-plus-btn not found!")
        await browser.stop()
        return

    print(f"  Found: '{plus_btn['label']}' at ({plus_btn['x']}, {plus_btn['y']})")

    # Step 2: Click the '+' button
    print("\n--- Step 2: Click '+' button ---")
    await _cdp_click(page, plus_btn['x'], plus_btn['y'])
    await asyncio.sleep(1.5)

    # Step 3: Inspect what appeared
    print("\n--- Step 3: Inspect resulting menu/popover ---")
    
    # Check for popover/menu/dialog elements
    menu_items = await _cdp_run_js(page, '''(() => {
        const results = [];
        
        // Check popovers, menus, dialogs
        const containers = document.querySelectorAll(
            '[role="menu"], [role="dialog"], [role="listbox"], ' +
            '[data-radix-popper-content-wrapper], [data-state="open"], ' +
            '.popover, [class*="popover"], [class*="dropdown"], [class*="menu"]'
        );
        
        for (const c of containers) {
            const rect = c.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            
            // Get all clickable items inside
            const items = c.querySelectorAll('button, a, [role="menuitem"], [role="option"], li');
            const itemTexts = [];
            for (const item of items) {
                const text = item.textContent.trim().substring(0, 80);
                const testid = item.getAttribute("data-testid") || "";
                const ariaLabel = item.getAttribute("aria-label") || "";
                if (text || testid) {
                    itemTexts.push({
                        text: text,
                        testid: testid,
                        ariaLabel: ariaLabel,
                        tagName: item.tagName,
                    });
                }
            }
            
            results.push({
                role: c.getAttribute("role") || "",
                class: (c.className || "").toString().substring(0, 100),
                testid: c.getAttribute("data-testid") || "",
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                itemCount: itemTexts.length,
                items: itemTexts.slice(0, 20),
            });
        }
        
        return results;
    })()''')

    if menu_items:
        for i, menu in enumerate(menu_items):
            print(f"\n  Container {i}: role={menu['role']}, testid={menu['testid']}, "
                  f"size={menu['width']}x{menu['height']}, items={menu['itemCount']}")
            for j, item in enumerate(menu.get('items', [])):
                print(f"    [{j}] <{item['tagName']}> testid='{item['testid']}' "
                      f"aria='{item['ariaLabel']}' text='{item['text'][:60]}'")
    else:
        print("  No menu/popover containers found via standard selectors")

    # Step 4: Broader search - any new visible elements with search-related text
    print("\n--- Step 4: Search for any 'search' related elements ---")
    search_elements = await _cdp_run_js(page, '''(() => {
        const results = [];
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const text = el.textContent.trim().toLowerCase();
            const testid = (el.getAttribute("data-testid") || "").toLowerCase();
            const ariaLabel = (el.getAttribute("aria-label") || "").toLowerCase();
            const isSearchRelated = (
                testid.includes("search") || 
                ariaLabel.includes("search") ||
                (text.includes("search") && text.length < 50 && el.children.length === 0)
            );
            if (!isSearchRelated) continue;
            const rect = el.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            results.push({
                tag: el.tagName,
                text: el.textContent.trim().substring(0, 60),
                testid: el.getAttribute("data-testid") || "",
                ariaLabel: el.getAttribute("aria-label") || "",
                x: Math.round(rect.x + rect.width/2),
                y: Math.round(rect.y + rect.height/2),
            });
        }
        return results;
    })()''')

    if search_elements:
        for el in search_elements:
            print(f"  <{el['tag']}> testid='{el['testid']}' aria='{el['ariaLabel']}' "
                  f"text='{el['text'][:50]}' at ({el['x']},{el['y']})")
    else:
        print("  No search-related elements found anywhere!")

    # Step 5: Check for any toggle/switch elements anywhere on page
    print("\n--- Step 5: All toggle/switch elements on page ---")
    toggles = await _cdp_run_js(page, '''(() => {
        const results = [];
        const switches = document.querySelectorAll(
            '[role="switch"], input[type="checkbox"], [aria-checked], ' +
            '[data-state="checked"], [data-state="unchecked"]'
        );
        for (const sw of switches) {
            const rect = sw.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) continue;
            // Get parent/label text for context
            let labelText = "";
            const parent = sw.closest("label, [class*='toggle'], [class*='switch']");
            if (parent) labelText = parent.textContent.trim().substring(0, 80);
            results.push({
                tag: sw.tagName,
                role: sw.getAttribute("role") || "",
                ariaChecked: sw.getAttribute("aria-checked") || "",
                dataState: sw.getAttribute("data-state") || "",
                testid: sw.getAttribute("data-testid") || "",
                ariaLabel: sw.getAttribute("aria-label") || "",
                label: labelText,
                x: Math.round(rect.x + rect.width/2),
                y: Math.round(rect.y + rect.height/2),
            });
        }
        return results;
    })()''')

    if toggles:
        for t in toggles:
            print(f"  <{t['tag']}> role={t['role']} checked={t['ariaChecked']} "
                  f"state={t['dataState']} testid='{t['testid']}' "
                  f"aria='{t['ariaLabel']}' label='{t['label'][:50]}' "
                  f"at ({t['x']},{t['y']})")
    else:
        print("  No toggle/switch elements found!")

    # Screenshot
    print("\n--- Taking screenshot ---")
    try:
        await page.save_screenshot("/tmp/chatgpt-plus-button-probe.png")
        print("  Saved: /tmp/chatgpt-plus-button-probe.png")
    except Exception as e:
        print(f"  Screenshot error: {e}")

    # Step 6: Close the menu (press Escape) and check if search appears elsewhere
    print("\n--- Step 6: Close menu, check toolbar area ---")
    await page.send(cdp.input_.dispatch_key_event(
        type_="keyDown", key="Escape", code="Escape",
        windows_virtual_key_code=27, native_virtual_key_code=27,
    ))
    await asyncio.sleep(0.5)
    
    # Check the area near the input for any toolbar buttons
    toolbar = await _cdp_run_js(page, '''(() => {
        const results = [];
        const buttons = document.querySelectorAll('button');
        for (const btn of buttons) {
            const rect = btn.getBoundingClientRect();
            // Focus on buttons near bottom of page (input area, y > 300)
            if (rect.y < 300 || rect.width === 0) continue;
            results.push({
                text: btn.textContent.trim().substring(0, 50),
                testid: btn.getAttribute("data-testid") || "",
                ariaLabel: btn.getAttribute("aria-label") || "",
                x: Math.round(rect.x + rect.width/2),
                y: Math.round(rect.y + rect.height/2),
            });
        }
        return results;
    })()''')

    if toolbar:
        print(f"  Buttons near input area ({len(toolbar)}):")
        for b in toolbar:
            print(f"    testid='{b['testid']}' aria='{b['ariaLabel']}' "
                  f"text='{b['text'][:40]}' at ({b['x']},{b['y']})")

    await asyncio.sleep(1)
    await browser.stop()
    print("\n" + "=" * 60)
    print("PROBE COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
