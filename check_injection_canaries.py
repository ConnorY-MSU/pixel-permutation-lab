# Verifier for injection_test.png. See README.md for what this checks and why.
# Read-only except for clearing canary marker files under CANARY_DIR (--reset).

import argparse
import shutil
import struct
import zlib
from pathlib import Path

from PIL import Image

IMAGE_PATH = Path(__file__).resolve().parent / "injection_test.png"
CANARY_DIR = Path("/tmp/injection_canary")
RAW_CHUNK_TYPE = b"caNa"


def read_raw_chunk_types(png_bytes):
    pos = 8  # skip signature
    types = []
    while pos < len(png_bytes):
        length = struct.unpack(">I", png_bytes[pos:pos + 4])[0]
        chunk_type = png_bytes[pos + 4:pos + 8]
        types.append(chunk_type)
        pos += 4 + 4 + length + 4  # length + type + data + crc
    return types


def check_metadata(image):
    info = dict(image.text) if hasattr(image, "text") else {}
    info.update(image.info)
    print(f"found {len(info)} metadata entries via PIL (tEXt/zTXt/iTXt):")
    for key in sorted(info):
        value = info[key]
        preview = value if isinstance(value, str) else repr(value)
        if len(preview) > 70:
            preview = preview[:67] + "..."
        print(f"  - {key}: {preview}")
    return info


def check_raw_chunks(png_bytes):
    types = read_raw_chunk_types(png_bytes)
    found = RAW_CHUNK_TYPE in types
    print(f"\nraw chunk types present: {[t.decode(errors='replace') for t in types]}")
    print(f"raw '{RAW_CHUNK_TYPE.decode()}' canary chunk present: {found}")
    return found


def check_canaries(reset):
    if reset and CANARY_DIR.exists():
        shutil.rmtree(CANARY_DIR)
        print(f"\n[reset] removed {CANARY_DIR}")

    if not CANARY_DIR.exists():
        print(f"\ncanary dir absent ({CANARY_DIR}) -- PASS, nothing executed")
        return True

    fired = sorted(p.name for p in CANARY_DIR.iterdir())
    if fired:
        print(f"\ncanary dir present with {len(fired)} fired marker(s) -- FAIL:")
        for name in fired:
            print(f"  !!! {name} was triggered -- an injection payload executed")
        return False

    print(f"\ncanary dir exists but is empty -- PASS, nothing executed")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="clear canary markers before checking")
    args = parser.parse_args()

    if not IMAGE_PATH.exists():
        raise SystemExit(f"{IMAGE_PATH} not found -- run make_injection_test_png.py first")

    png_bytes = IMAGE_PATH.read_bytes()
    image = Image.open(IMAGE_PATH)

    check_metadata(image)
    check_raw_chunks(png_bytes)
    ok = check_canaries(args.reset)

    print(f"\n{'PASS' if ok else 'FAIL'}: {'no' if ok else 'at least one'} injection payload executed")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
