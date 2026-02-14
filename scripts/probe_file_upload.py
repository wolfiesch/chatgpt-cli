#!/usr/bin/env python3
"""
Probe: Discover file/image upload mechanism in ChatGPT UI.
Finds hidden <input type="file"> elements, the '+' button menu,
and determines the best CDP approach for file upload.

Usage:
    python3 scripts/run.py probe_file_upload.py
"""
import asyncio
import json
import sys

import nodriver as uc
from nodriver import cdp

from config import (
    USER_DATA_DIR, BROWSER_ARGS,
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
    """Full CDP mouse click sequence."""
    await page.send(cdp.input_.dispatch_mouse_event(type_="mouseMoved", x=x, y=y))
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
    print("PROBE: ChatGPT File/Image Upload Mechanism")
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
            if c.get("secure"):
                params["secure"] = True
            if c.get("httpOnly"):
                params["httpOnly"] = True
            if c.get("sameSite"):
                params["sameSite"] = c["sameSite"]
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

    # ── Step 1: Find ALL <input type="file"> elements ──────────────────
    print("\n--- Step 1: All <input type='file'> elements ---")
    file_inputs = await _cdp_run_js(page, '''(() => {
        const results = [];
        const inputs = document.querySelectorAll('input[type="file"]');
        for (const inp of inputs) {
            const rect = inp.getBoundingClientRect();
            const parent = inp.parentElement;
            const parentRect = parent ? parent.getBoundingClientRect() : {};
            results.push({
                id: inp.id || "",
                name: inp.name || "",
                accept: inp.accept || "",
                multiple: inp.multiple,
                hidden: inp.hidden || rect.width === 0 || rect.height === 0,
                style_display: inp.style.display,
                style_visibility: inp.style.visibility,
                className: (inp.className || "").substring(0, 100),
                testid: inp.getAttribute("data-testid") || "",
                ariaLabel: inp.getAttribute("aria-label") || "",
                rect: {
                    x: Math.round(rect.x), y: Math.round(rect.y),
                    w: Math.round(rect.width), h: Math.round(rect.height),
                },
                parentTag: parent ? parent.tagName : "",
                parentTestid: parent ? (parent.getAttribute("data-testid") || "") : "",
                parentClass: parent ? (parent.className || "").toString().substring(0, 80) : "",
                parentRect: parent ? {
                    x: Math.round(parentRect.x || 0),
                    y: Math.round(parentRect.y || 0),
                    w: Math.round(parentRect.width || 0),
                    h: Math.round(parentRect.height || 0),
                } : {},
            });
        }
        return results;
    })()''')

    if file_inputs:
        for i, inp in enumerate(file_inputs):
            print(f"\n  Input #{i}:")
            print(f"    id='{inp['id']}' name='{inp['name']}'")
            print(f"    accept='{inp['accept']}' multiple={inp['multiple']}")
            print(f"    hidden={inp['hidden']} display='{inp['style_display']}' visibility='{inp['style_visibility']}'")
            print(f"    testid='{inp['testid']}' ariaLabel='{inp['ariaLabel']}'")
            print(f"    class='{inp['className']}'")
            print(f"    rect: {inp['rect']}")
            print(f"    parent: <{inp['parentTag']}> testid='{inp['parentTestid']}' class='{inp['parentClass']}'")
            print(f"    parentRect: {inp['parentRect']}")
    else:
        print("  No <input type='file'> elements found on initial page load!")

    # ── Step 2: Find the '+' / attach button ──────────────────────────
    print("\n--- Step 2: Composer attachment buttons ---")
    attach_btns = await _cdp_run_js(page, '''(() => {
        const results = [];
        // Look for known attachment-related buttons
        const selectors = [
            '[data-testid="composer-plus-btn"]',
            '[data-testid*="attach"]',
            '[data-testid*="upload"]',
            '[data-testid*="file"]',
            '[aria-label*="Attach"]',
            '[aria-label*="Upload"]',
            '[aria-label*="file"]',
        ];
        const seen = new Set();
        for (const sel of selectors) {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
                if (seen.has(el)) continue;
                seen.add(el);
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                results.push({
                    selector: sel,
                    tag: el.tagName,
                    testid: el.getAttribute("data-testid") || "",
                    ariaLabel: el.getAttribute("aria-label") || "",
                    text: el.textContent.trim().substring(0, 60),
                    x: Math.round(rect.x + rect.width / 2),
                    y: Math.round(rect.y + rect.height / 2),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                });
            }
        }
        return results;
    })()''')

    if attach_btns:
        for btn in attach_btns:
            print(f"  <{btn['tag']}> testid='{btn['testid']}' "
                  f"aria='{btn['ariaLabel']}' text='{btn['text']}' "
                  f"at ({btn['x']},{btn['y']}) size={btn['w']}x{btn['h']}")
    else:
        print("  No attachment buttons found!")

    # ── Step 3: Click the '+' / attach button and inspect menu ────────
    print("\n--- Step 3: Click attach button → inspect menu ---")
    # Find the best attach button
    plus_btn = await _cdp_run_js(page, '''(() => {
        // Try known selectors in priority order
        const selectors = [
            '[data-testid="composer-plus-btn"]',
            '[data-testid*="attach"]',
            '[aria-label*="Attach"]',
        ];
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (!el) continue;
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {
                return {
                    testid: el.getAttribute("data-testid") || sel,
                    x: Math.round(r.x + r.width / 2),
                    y: Math.round(r.y + r.height / 2),
                };
            }
        }
        return null;
    })()''')

    if plus_btn:
        print(f"  Clicking: {plus_btn['testid']} at ({plus_btn['x']}, {plus_btn['y']})")
        await _cdp_click(page, plus_btn['x'], plus_btn['y'])
        await asyncio.sleep(1.5)

        # Check what menu appeared
        menu_items = await _cdp_run_js(page, '''(() => {
            const results = [];
            // Check for popover/menu/dropdown
            const containers = document.querySelectorAll(
                '[role="menu"], [role="dialog"], [role="listbox"], ' +
                '[data-radix-popper-content-wrapper], [data-state="open"], ' +
                '[class*="popover"], [class*="dropdown"], [class*="menu"]'
            );
            for (const c of containers) {
                const rect = c.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                const items = c.querySelectorAll(
                    'button, a, [role="menuitem"], [role="option"], li, div[tabindex]'
                );
                const itemData = [];
                for (const item of items) {
                    const text = item.textContent.trim().substring(0, 80);
                    const testid = item.getAttribute("data-testid") || "";
                    const ariaLabel = item.getAttribute("aria-label") || "";
                    const r = item.getBoundingClientRect();
                    if ((text || testid) && r.width > 0) {
                        itemData.push({
                            text, testid, ariaLabel,
                            tag: item.tagName,
                            x: Math.round(r.x + r.width / 2),
                            y: Math.round(r.y + r.height / 2),
                        });
                    }
                }
                results.push({
                    role: c.getAttribute("role") || "",
                    testid: c.getAttribute("data-testid") || "",
                    class: (c.className || "").toString().substring(0, 100),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                    items: itemData.slice(0, 15),
                });
            }
            return results;
        })()''')

        if menu_items:
            for mi, menu in enumerate(menu_items):
                print(f"\n  Container {mi}: role={menu['role']} testid={menu['testid']} "
                      f"size={menu['w']}x{menu['h']}")
                for j, item in enumerate(menu.get('items', [])):
                    print(f"    [{j}] <{item['tag']}> testid='{item['testid']}' "
                          f"aria='{item['ariaLabel']}' text='{item['text'][:60]}' "
                          f"at ({item['x']},{item['y']})")
        else:
            print("  No menu/popover appeared!")

        # Check if new file inputs appeared after clicking
        new_file_inputs = await _cdp_run_js(page, '''(() => {
            const inputs = document.querySelectorAll('input[type="file"]');
            const results = [];
            for (const inp of inputs) {
                results.push({
                    id: inp.id || "",
                    accept: inp.accept || "",
                    multiple: inp.multiple,
                    testid: inp.getAttribute("data-testid") || "",
                });
            }
            return results;
        })()''')
        print(f"\n  File inputs after click: {len(new_file_inputs or [])}")
        for inp in (new_file_inputs or []):
            print(f"    id='{inp['id']}' accept='{inp['accept']}' "
                  f"multiple={inp['multiple']} testid='{inp['testid']}'")
    else:
        print("  No attach button found to click!")

    # ── Step 4: Check drag-and-drop zone ──────────────────────────────
    print("\n--- Step 4: Drag-and-drop zones ---")
    dnd_zones = await _cdp_run_js(page, '''(() => {
        const results = [];
        // Look for elements with dragover/drop event listeners or dropzone attribute
        const candidates = document.querySelectorAll(
            '[class*="drop"], [class*="drag"], [class*="upload"], ' +
            '[data-testid*="drop"], [data-testid*="drag"], ' +
            'form, [role="form"]'
        );
        for (const el of candidates) {
            const rect = el.getBoundingClientRect();
            if (rect.width < 50 || rect.height < 50) continue;
            results.push({
                tag: el.tagName,
                testid: el.getAttribute("data-testid") || "",
                class: (el.className || "").toString().substring(0, 100),
                dropzone: el.getAttribute("dropzone") || "",
                w: Math.round(rect.width),
                h: Math.round(rect.height),
            });
        }
        return results;
    })()''')

    if dnd_zones:
        for z in dnd_zones:
            print(f"  <{z['tag']}> testid='{z['testid']}' "
                  f"class='{z['class'][:60]}' dropzone='{z['dropzone']}' "
                  f"size={z['w']}x{z['h']}")
    else:
        print("  No obvious drag-and-drop zones found")

    # Screenshot
    print("\n--- Taking screenshot ---")
    try:
        await page.save_screenshot("/tmp/chatgpt-file-upload-probe.png")
        print("  Saved: /tmp/chatgpt-file-upload-probe.png")
    except Exception as e:
        print(f"  Screenshot error: {e}")

    # Close menu
    await page.send(cdp.input_.dispatch_key_event(
        type_="keyDown", key="Escape", code="Escape",
        windows_virtual_key_code=27, native_virtual_key_code=27,
    ))
    await asyncio.sleep(0.5)

    # ── Step 5: Try CDP DOM approach to find file input nodes ─────────
    print("\n--- Step 5: CDP DOM.getDocument + querySelector for input[type=file] ---")
    try:
        doc, _ = await page.send(cdp.dom.get_document(depth=-1))
        root_node_id = doc.node_id
        # Query for file inputs
        node_ids, _ = await page.send(
            cdp.dom.query_selector_all(root_node_id, 'input[type="file"]')
        )
        print(f"  Found {len(node_ids)} file input node(s) via CDP DOM")
        for nid in node_ids:
            # Get attributes
            attrs, _ = await page.send(cdp.dom.get_attributes(nid))
            print(f"    nodeId={nid} attrs={attrs}")
    except Exception as e:
        print(f"  CDP DOM query error: {e}")

    await asyncio.sleep(1)
    await browser.stop()
    print("\n" + "=" * 60)
    print("PROBE COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
