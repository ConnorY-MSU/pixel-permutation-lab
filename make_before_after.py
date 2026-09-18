# Runs the real theory.py pipeline on a normal-sized image and saves
# original/shuffled/reconstructed stills for the README. No animation --
# see pixel_demo.py for the step-by-step visualization on a small image.

import argparse
from pathlib import Path

from PIL import Image

from theory import (
    array_to_string,
    build_indexed_array,
    flatten_pixels,
    generate_permutation,
    shuffle_pixels,
    string_to_array,
    unshuffle_pixels,
)

SCRIPT_DIR = Path(__file__).resolve().parent


def run(image_path, out_dir, seed=1234):
    image = Image.open(image_path).convert("RGB")
    width, height = image.size
    flat, pixel_count = flatten_pixels(image)
    channels = flat.shape[-1]

    permutation = generate_permutation(pixel_count, seed)
    shuffled = shuffle_pixels(flat, permutation)

    wire_bytes = array_to_string(build_indexed_array(shuffled))
    parsed = string_to_array(wire_bytes, channels)
    reconstructed = unshuffle_pixels(parsed, permutation)

    match = bool((reconstructed == flat).all())
    print(f"{pixel_count:,} pixels, {len(wire_bytes):,} bytes on the wire, bit-for-bit match: {match}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, pixels in (
        ("base-original.png", flat),
        ("base-shuffled.png", shuffled),
        ("base-reconstructed.png", reconstructed),
    ):
        Image.fromarray(pixels.reshape(height, width, channels)).save(out_dir / name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", default=str(SCRIPT_DIR / "docs" / "sample.png"))
    parser.add_argument("--out-dir", default=str(SCRIPT_DIR / "docs"))
    parser.add_argument("--seed", type=int, default=1234)
    args = parser.parse_args()
    run(args.image, args.out_dir, args.seed)
