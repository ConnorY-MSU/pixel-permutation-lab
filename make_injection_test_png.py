# Generates injection_test.png. See README.md for what this image contains
# and why. Run check_injection_canaries.py after exercising this image.

import struct
import zlib
from pathlib import Path

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

OUT_PATH = Path(__file__).resolve().parent / "injection_test.png"

WIDTH, HEIGHT = 64, 64

CANARY_DIR = Path("/tmp/injection_canary")


def marker(name):
    return str(CANARY_DIR / f"{name}.txt")


def touch_cmd(name):  # shell one-liner: mkdir + touch one canary marker file
    return f"mkdir -p {CANARY_DIR} && echo TRIGGERED > {marker(name)}"


# payloads embedded verbatim as PNG text metadata, grouped by category
PAYLOADS = {
    # --- OS command injection ---
    "cmd_unix_subst": f"$({touch_cmd('cmd_unix_subst')})",
    "cmd_unix_backtick": f"`{touch_cmd('cmd_unix_backtick')}`",
    "cmd_unix_chain": f"; {touch_cmd('cmd_unix_chain')} ;",
    "cmd_unix_pipe": f"| sh -c '{touch_cmd('cmd_unix_pipe')}'",
    "cmd_unix_or": f"nonexistent_cmd_xyz || {touch_cmd('cmd_unix_or')}",
    "cmd_windows": f"& echo TRIGGERED > {CANARY_DIR}\\cmd_windows.txt &",
    "cmd_env_expansion": "$(echo $HOME)/%USERPROFILE%/../../etc/passwd",

    # --- Code injection (interpreter eval/exec) ---
    "python_eval": f"__import__('os').system({touch_cmd('python_eval')!r})",
    "python_exec": f"exec(\"__import__('os').system({touch_cmd('python_exec')!r})\")",
    "js_eval": "eval(\"document.title='INJECTED'\")",

    # --- SQL / NoSQL / LDAP / XPath injection ---
    "sql_tautology": "' OR '1'='1' -- ",
    "sql_union": "' UNION SELECT username, password FROM users -- ",
    "sql_stacked_drop": "'; DROP TABLE users; --",
    "sql_blind_sleep": "' OR SLEEP(5) -- ",
    "nosql_operator": '{"$where": "sleep(5000)", "$ne": null}',
    "ldap_injection": "*)(uid=*))(|(uid=*",
    "xpath_injection": "' or '1'='1",

    # --- Server-side template injection ---
    "ssti_jinja2": "{{ 7*7 }}{{ config.items() }}",
    "ssti_freemarker": "${7*7}${\"freemarker.template.utility.Execute\"?new()(\"id\")}",
    "ssti_erb": "<%= 7*7 %>",
    "ssti_twig": "{{ 7*7 }}{{ _self.env.registerUndefinedFilterCallback('exec') }}",

    # --- XSS / HTML injection ---
    "xss_script_tag": "<script>document.title='INJECTED'</script>",
    "xss_event_handler": "<img src=x onerror=\"document.title='INJECTED'\">",
    "xss_svg": "<svg onload=\"document.title='INJECTED'\"></svg>",
    "xss_js_uri": "javascript:document.title='INJECTED'",
    "html_injection": "<h1>injected</h1><iframe src=about:blank></iframe>",

    # --- Header / log injection ---
    "crlf_header_injection": "value\r\nSet-Cookie: injected=true\r\nX-Injected: yes",
    "log_injection_newline": "user logged in\n[FAKE] ADMIN logged in from 10.0.0.1",
    "log4shell_jndi_canary": "${jndi:ldap://127.0.0.1:1/a}",

    # --- Path traversal / LFI / null byte ---
    "path_traversal_unix": "../../../../../../etc/passwd",
    "path_traversal_windows": "..\\..\\..\\..\\windows\\win.ini",
    "null_byte_injection": "safe_filename.png\x00.php",

    # --- Format string vulnerabilities ---
    "format_string_c": "%n%n%n%s%s%s%x%x%x",
    "format_string_python": "{0.__class__.__mro__[1].__subclasses__()}",

    # --- Unsafe deserialization ---
    "yaml_unsafe_load": f"!!python/object/apply:os.system [{touch_cmd('yaml_unsafe_load')!r}]",
    "pickle_marker": "PICKLE_OPCODES:GLOBAL 'os' 'system' STRING 'id' REDUCE  (textual marker only, no real opcodes)",

    # --- ReDoS / CSV formula / SSRF canaries ---
    "redos_pattern": "(a+)+$",
    "csv_formula_injection": "=cmd|' /C calc'!A0",
    "ssrf_metadata_url": "http://169.254.169.254/latest/meta-data/iam/security-credentials/",

    # --- Encoding / Unicode tricks ---
    "unicode_bidi_trick": "user" + chr(0x202E) + "exe.gnp",  # right-to-left override trick
    "unicode_homograph": chr(0x0430) + "pple.com",  # Cyrillic vs Latin lookalike

    # --- Prototype pollution (JS) ---
    "proto_pollution": '{"__proto__": {"isAdmin": true}}',
}

# same payloads, exercised through PIL's UTF-8 iTXt chunk path instead of Latin-1 tEXt
ITXT_PAYLOADS = {
    "itxt_unicode_bidi": "user" + chr(0x202E) + "exe.gnp",
    "itxt_ssti_jinja2": "{{ 7*7 }}",
}

# these categories go through zTXt (zlib-compressed) instead of plain tEXt
ZTXT_KEYS = {"sql_union", "ssti_freemarker", "yaml_unsafe_load", "log4shell_jndi_canary"}

RAW_CHUNK_TYPE = b"caNa"  # ancillary, private, safe-to-copy — hand-built, bypasses PIL
RAW_CHUNK_PAYLOAD = b"RAW_CHUNK_INJECTION_CANARY: '; DROP TABLE users; -- <script>alert(1)</script>"


def build_pixels(width, height):
    rng = np.random.default_rng(42)
    x = np.linspace(0, 255, width, dtype=np.uint8)
    gradient = np.tile(x, (height, 1))
    noise = rng.integers(0, 40, size=(height, width), dtype=np.uint8)
    r = gradient
    g = np.flip(gradient, axis=1)
    b = np.clip(gradient.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return np.dstack([r, g, b])


def make_png_chunk(chunk_type, data):
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    return length + chunk_type + data + crc


def insert_raw_chunk_after_ihdr(png_bytes, chunk_type, data):
    sig_len = 8
    ihdr_len = struct.unpack(">I", png_bytes[sig_len:sig_len + 4])[0]
    ihdr_end = sig_len + 4 + 4 + ihdr_len + 4  # length + type + data + crc
    new_chunk = make_png_chunk(chunk_type, data)
    return png_bytes[:ihdr_end] + new_chunk + png_bytes[ihdr_end:]


def main():
    pixels = build_pixels(WIDTH, HEIGHT)
    image = Image.fromarray(pixels, mode="RGB")

    meta = PngInfo()
    for key, value in PAYLOADS.items():
        meta.add_text(key, value, zip=key in ZTXT_KEYS)
    for key, value in ITXT_PAYLOADS.items():
        meta.add_itxt(key, value, lang="en", tkey=key)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT_PATH, pnginfo=meta)

    png_bytes = OUT_PATH.read_bytes()
    png_bytes = insert_raw_chunk_after_ihdr(png_bytes, RAW_CHUNK_TYPE, RAW_CHUNK_PAYLOAD)
    OUT_PATH.write_bytes(png_bytes)

    all_categories = sorted(set(PAYLOADS) | set(ITXT_PAYLOADS) | {"raw_chunk_" + RAW_CHUNK_TYPE.decode()})
    print(f"wrote {OUT_PATH} ({WIDTH}x{HEIGHT}, {len(png_bytes):,} bytes)")
    print(f"embedded {len(all_categories)} canary categories:")
    for cat in all_categories:
        print(f"  - {cat}")
    print(f"\ncanary marker dir (should be empty/absent unless a payload executes): {CANARY_DIR}")
    print("run check_injection_canaries.py to verify.")


if __name__ == "__main__":
    main()
