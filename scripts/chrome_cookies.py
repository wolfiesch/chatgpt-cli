#!/usr/bin/env python3
"""
Direct Chrome Cookie Extractor for ChatGPT CLI Skill
Extracts cookies directly from Chrome's SQLite database, including HttpOnly cookies.

This bypasses the FGP limitation and can access ALL cookies.
Chrome does NOT need to be closed — uses sqlite3.backup() to read through WAL journals.
"""

import argparse
import base64
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# Chrome paths on macOS
CHROME_COOKIE_PATH = Path.home() / "Library/Application Support/Google/Chrome/Default/Cookies"
CHROME_LOCAL_STATE = Path.home() / "Library/Application Support/Google/Chrome/Local State"

# Cache for encryption key (avoids repeated Keychain prompts)
KEY_CACHE_FILE = Path(__file__).parent.parent / "data" / ".chrome_key_cache"


def get_chrome_encryption_key() -> Optional[bytes]:
    """
    Get Chrome's encryption key from macOS Keychain.
    Chrome stores cookie values encrypted with this key.
    Caches the derived key to avoid repeated Keychain password prompts.
    """
    import hashlib

    # Try to load cached key first
    if KEY_CACHE_FILE.exists():
        try:
            cached_key = KEY_CACHE_FILE.read_bytes()
            if len(cached_key) == 16:  # Valid AES-128 key
                return cached_key
        except Exception:
            pass

    try:
        # Get the key from Keychain using security command
        result = subprocess.run(
            ['security', 'find-generic-password', '-w', '-s', 'Chrome Safe Storage'],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            return None

        password = result.stdout.strip()

        # Derive the key using PBKDF2 (Chrome's method)
        key = hashlib.pbkdf2_hmac(
            'sha1',
            password.encode('utf-8'),
            b'saltysalt',
            1003,
            dklen=16
        )

        # Cache the derived key for future use
        try:
            KEY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            KEY_CACHE_FILE.write_bytes(key)
            # Secure the file permissions
            KEY_CACHE_FILE.chmod(0o600)
        except Exception:
            pass  # Non-fatal if caching fails

        return key

    except Exception as e:
        print(f"Warning: Could not get encryption key: {e}", file=sys.stderr)
        return None


def decrypt_cookie_value(encrypted_value: bytes, key: bytes) -> str:
    """Decrypt a Chrome cookie value.

    Chrome on macOS uses AES-128-CBC with iv=b' '*16. The actual per-cookie IV
    differs, so the first 2 AES blocks (32 bytes) of plaintext are garbage.
    The real cookie value starts at byte 32.
    """
    try:
        from Crypto.Cipher import AES

        # Chrome prepends 'v10' or 'v11' to encrypted values
        if encrypted_value[:3] == b'v10' or encrypted_value[:3] == b'v11':
            encrypted_value = encrypted_value[3:]

        # Use AES-CBC with a fixed IV (Chrome's method on macOS)
        iv = b' ' * 16
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted_value)

        # Remove PKCS7 padding
        padding_len = decrypted[-1]
        if isinstance(padding_len, int) and 1 <= padding_len <= 16:
            # Verify padding is consistent
            if all(b == padding_len for b in decrypted[-padding_len:]):
                decrypted = decrypted[:-padding_len]

        # First 32 bytes are garbage (2 AES blocks corrupted by wrong IV).
        # The real cookie value starts at byte 32.
        # For very short cookies (<=32 bytes), fall back to scanning for
        # the first printable ASCII run.
        if len(decrypted) > 32:
            text = decrypted[32:].decode('utf-8', errors='ignore')
        else:
            text = decrypted.decode('utf-8', errors='ignore')
            # Find first printable segment for short values
            for i in range(len(text)):
                if text[i].isprintable() and not text[i].isspace():
                    return text[i:].rstrip('\x00').strip()
            return text.strip('\x00').strip()

        return text.rstrip('\x00').strip()

    except ImportError:
        print("Warning: pycryptodome not installed, cannot decrypt cookies", file=sys.stderr)
        return ""
    except Exception as e:
        return ""


def chrome_timestamp_to_unix(chrome_ts: int) -> float:
    """Convert Chrome timestamp (microseconds since 1601) to Unix timestamp"""
    if chrome_ts == 0:
        return 0
    # Chrome epoch is Jan 1, 1601
    # Unix epoch is Jan 1, 1970
    # Difference is 11644473600 seconds
    return (chrome_ts / 1000000) - 11644473600


def extract_cookies(domains: list[str], decrypt: bool = True) -> dict:
    """
    Extract cookies from Chrome's cookie database.

    Args:
        domains: List of domains to extract cookies for
        decrypt: Whether to decrypt cookie values

    Returns:
        dict with cookies list
    """
    if not CHROME_COOKIE_PATH.exists():
        return {
            "success": False,
            "error": f"Chrome cookie database not found at {CHROME_COOKIE_PATH}"
        }

    # Get encryption key if decrypting
    key = None
    if decrypt:
        key = get_chrome_encryption_key()

    # Copy database to temp file — Chrome keeps it open with WAL mode.
    # We use sqlite3.backup() which correctly reads through WAL journals,
    # so Chrome does NOT need to be closed.
    temp_dir = tempfile.mkdtemp()
    temp_db = Path(temp_dir) / "Cookies"

    try:
        # backup() handles WAL mode correctly — reads all committed data
        # even while Chrome has the DB open (WAL allows concurrent readers).
        src_conn = sqlite3.connect(str(CHROME_COOKIE_PATH), timeout=5)
        dst_conn = sqlite3.connect(str(temp_db))
        src_conn.backup(dst_conn)
        src_conn.close()
        dst_conn.close()

        conn = sqlite3.connect(str(temp_db))
        cursor = conn.cursor()

        # Build domain filter - exact matches and subdomains
        domain_conditions = []
        for domain in domains:
            # Remove leading dot if present
            clean_domain = domain.lstrip(".")
            # Match: exact domain, wildcard domain, and subdomains
            domain_conditions.append(f"host_key = '{clean_domain}'")
            domain_conditions.append(f"host_key = '.{clean_domain}'")
            domain_conditions.append(f"host_key LIKE '%.{clean_domain}'")

        where_clause = " OR ".join(domain_conditions)

        cursor.execute(f"""
            SELECT host_key, name, value, encrypted_value, path,
                   expires_utc, is_secure, is_httponly, samesite
            FROM cookies
            WHERE {where_clause}
        """)

        cookies = []
        for row in cursor.fetchall():
            host_key, name, value, encrypted_value, path, expires_utc, is_secure, is_httponly, samesite = row

            # Decrypt value if needed
            cookie_value = value
            if encrypted_value and key:
                decrypted = decrypt_cookie_value(encrypted_value, key)
                if decrypted:
                    cookie_value = decrypted

            # Convert samesite
            samesite_map = {-1: None, 0: "None", 1: "Lax", 2: "Strict"}
            same_site = samesite_map.get(samesite)

            cookies.append({
                "name": name,
                "value": cookie_value,
                "domain": host_key,
                "path": path,
                "expires": chrome_timestamp_to_unix(expires_utc) if expires_utc else None,
                "secure": bool(is_secure),
                "http_only": bool(is_httponly),
                "same_site": same_site
            })

        conn.close()

        return {
            "success": True,
            "cookies": cookies,
            "count": len(cookies),
            "domains": domains,
            "decrypted": decrypt and key is not None
        }

    except sqlite3.OperationalError as e:
        return {
            "success": False,
            "error": f"Database error: {e}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
    finally:
        # Cleanup temp files
        shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Extract cookies from Chrome")
    parser.add_argument("--domains", "-d",
                       help="Comma-separated domains to extract")
    parser.add_argument("--no-decrypt", action="store_true",
                       help="Don't decrypt cookie values")
    parser.add_argument("--save", "-s",
                       help="Save to file for stealth browser use")
    parser.add_argument("--clear-cache", action="store_true",
                       help="Clear cached Chrome encryption key (requires re-auth)")

    args = parser.parse_args()

    # Handle clear-cache
    if args.clear_cache:
        if KEY_CACHE_FILE.exists():
            KEY_CACHE_FILE.unlink()
            print(json.dumps({"success": True, "message": "Key cache cleared. Next run will prompt for Keychain password."}))
        else:
            print(json.dumps({"success": True, "message": "No cached key found."}))
        sys.exit(0)

    # Require domains for extraction
    if not args.domains:
        parser.error("--domains is required unless using --clear-cache")

    domains = [d.strip() for d in args.domains.split(",")]
    result = extract_cookies(domains, decrypt=not args.no_decrypt)

    if args.save and result.get("success"):
        save_path = Path(args.save)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, 'w') as f:
            json.dump(result, f, indent=2)
        result["saved_to"] = str(save_path)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
