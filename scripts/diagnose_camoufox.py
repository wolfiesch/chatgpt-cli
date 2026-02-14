#!/usr/bin/env python3
"""
Diagnostic script: Open ChatGPT in camoufox and dump what DOM elements exist.
This helps identify why selectors that work in nodriver fail in camoufox.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".claude/skills/shared"))
from browser_engine import create_engine

sys.path.insert(0, str(Path(__file__).parent))
from config import (
    CHATGPT_URL,
    CHATGPT_COOKIE_DOMAINS,
    CHATGPT_INPUT_SELECTORS,
    CHATGPT_SEND_SELECTORS,
)
from chrome_cookies import extract_cookies as extract_chrome_cookies

SCREENSHOT_PATH = str(
    Path(__file__).parent.parent / "data" / "screenshots" / "camoufox_diag.png"
)


async def main():
    print("=== ChatGPT Camoufox Diagnostics ===\n")

    # Extract cookies
    result = extract_chrome_cookies(CHATGPT_COOKIE_DOMAINS, decrypt=True)
    if not result.get("success"):
        print(f"Cookie extraction failed: {result.get('error')}")
        return
    cookies = result["cookies"]
    print(f"Cookies extracted: {len(cookies)}")

    # Start camoufox
    engine = create_engine("camoufox")
    try:
        await engine.start(headless=False, user_data_dir=None, browser_args=None)
        print("Camoufox started")

        # Probe the engine internals (updated for ThreadPoolExecutor fix)
        print("\n=== Engine internals ===")
        print(f"  _browser type: {type(engine._browser)}")
        print(f"  _context type: {type(engine._context)}")
        print(f"  _page type:    {type(engine._page)}")
        print(f"  _cm type:      {type(engine._cm)}")

        # Check if _context has add_cookies (this was the original bug — Browser didn't have it)
        has_add_cookies = hasattr(engine._context, "add_cookies")
        print(f"  _context has add_cookies: {has_add_cookies}")

        # Inject cookies
        injected = await engine.inject_cookies(cookies)
        print(f"\nCookies injected: {injected}/{len(cookies)}")

        # Workaround: use route intercept to fetch+decompress Brotli responses
        # This is a known Camoufox bug: https://github.com/daijro/camoufox/discussions/332
        print("\n=== Setting up Brotli decompression route ===")

        def _setup_route():
            import brotli

            def handle_route(route):
                try:
                    response = route.fetch()
                    headers = response.headers
                    body = response.body()
                    encoding = headers.get("content-encoding", "")

                    if encoding == "br" and body:
                        try:
                            body = brotli.decompress(body)
                            # Remove content-encoding since we've decompressed
                            headers = {
                                k: v
                                for k, v in headers.items()
                                if k.lower() != "content-encoding"
                            }
                        except Exception:
                            pass  # Not actually brotli, pass through

                    route.fulfill(
                        status=response.status,
                        headers=headers,
                        body=body,
                    )
                except Exception:
                    # Fallback: just continue normally
                    try:
                        route.continue_()
                    except Exception:
                        pass

            engine._page.route("**/*", handle_route)

        await engine._run(_setup_route)

        await engine.goto(CHATGPT_URL)
        print(
            "Navigated to ChatGPT (with Brotli decompress proxy), waiting 8s for load..."
        )
        await engine.sleep(8)

        # Check for Cloudflare challenge
        print(f"\nCurrent URL: {engine.page_url}")
        title = await engine.run_js("document.title") or "(empty)"
        print(f"Title: {title}")
        htmlLen = await engine.run_js("document.documentElement.outerHTML.length") or 0
        print(f"HTML length: {htmlLen}")

        # Take screenshot
        await engine.screenshot(SCREENSHOT_PATH)
        print(f"Screenshot saved: {SCREENSHOT_PATH}")

        # Probe page content
        page_text = (
            await engine.run_js("document.body.innerText.substring(0, 500)")
            or "(empty)"
        )
        print(f"\nPage text (first 500 chars):\n{page_text}\n")

        # Probe for known selectors
        print("=== Selector Probe ===")
        for sel in CHATGPT_INPUT_SELECTORS:
            found = await engine.run_js(f"document.querySelector('{sel}') !== null")
            print(f"  {'FOUND' if found else 'MISS ':5} {sel}")

        for sel in CHATGPT_SEND_SELECTORS:
            found = await engine.run_js(f"document.querySelector('{sel}') !== null")
            print(f"  {'FOUND' if found else 'MISS ':5} {sel}")

        # Probe common alternatives
        print("\n=== Alternative Probes ===")
        probes = [
            'document.getElementById("prompt-textarea")',
            'document.querySelector(".ProseMirror")',
            'document.querySelector("[contenteditable=\\"true\\"]")',
            'document.querySelector("textarea")',
            'document.querySelector("input[type=\\"text\\"]")',
            'document.querySelector("[role=\\"textbox\\"]")',
            'document.querySelector("[data-testid]")',
            'document.querySelector("form")',
            'document.querySelector("main")',
        ]
        for probe in probes:
            found = await engine.run_js(f"{probe} !== null")
            tag_info = ""
            if found:
                tag_info = (
                    await engine.run_js(f"""(() => {{
                    const el = {probe};
                    if (!el) return "";
                    const tag = el.tagName;
                    const id = el.id ? "#" + el.id : "";
                    const cls = el.className ? "." + String(el.className).split(" ").join(".") : "";
                    const ce = el.contentEditable;
                    return `${{tag}}${{id}}${{cls}} contentEditable=${{ce}}`;
                }})()""")
                    or ""
                )
            print(f"  {'FOUND' if found else 'MISS ':5} {probe}")
            if tag_info:
                print(f"         → {tag_info}")

        # Dump all contenteditable elements
        print("\n=== All contenteditable elements ===")
        ce_elements = (
            await engine.run_js("""(() => {
            const els = document.querySelectorAll('[contenteditable="true"]');
            return Array.from(els).map(el => {
                const tag = el.tagName;
                const id = el.id ? "#" + el.id : "";
                const cls = el.className ? "." + String(el.className).split(" ").join(".") : "";
                const rect = el.getBoundingClientRect();
                return `${tag}${id}${cls} (${Math.round(rect.width)}x${Math.round(rect.height)})`;
            });
        })()""")
            or []
        )
        if ce_elements:
            for ce in ce_elements:
                print(f"  {ce}")
        else:
            print("  (none found)")

        # Dump all data-testid elements
        print("\n=== data-testid elements (first 20) ===")
        testids = (
            await engine.run_js("""(() => {
            const els = document.querySelectorAll('[data-testid]');
            return Array.from(els).slice(0, 20).map(el =>
                `${el.tagName}[data-testid="${el.getAttribute('data-testid')}"]`
            );
        })()""")
            or []
        )
        for tid in testids:
            print(f"  {tid}")

        # Dump all textareas
        print("\n=== All textarea/input elements ===")
        inputs = (
            await engine.run_js("""(() => {
            const els = [...document.querySelectorAll('textarea, input[type="text"]')];
            return els.map(el => {
                const tag = el.tagName;
                const id = el.id ? "#" + el.id : "";
                const ph = el.placeholder || "";
                const rect = el.getBoundingClientRect();
                return `${tag}${id} placeholder="${ph}" (${Math.round(rect.width)}x${Math.round(rect.height)})`;
            });
        })()""")
            or []
        )
        if inputs:
            for inp in inputs:
                print(f"  {inp}")
        else:
            print("  (none found)")

        print("\n=== Diagnostics complete ===")
        print("Keeping browser open for 10s for visual inspection...")
        await engine.sleep(10)

    finally:
        await engine.stop()
        print("Browser closed.")


if __name__ == "__main__":
    asyncio.run(main())
