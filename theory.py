from pathlib import Path

from PIL import Image
import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
PATH = SCRIPT_DIR / "injection_test.png"
DATA_PATH = SCRIPT_DIR / "shuffled.dat"
OUTPUT_PATH = SCRIPT_DIR / "reconstructed.png"
SEED = 1234


def load_image(path):
    image = Image.open(path)
    width, height = image.size
    return image, width, height


def flatten_pixels(image):
    pixels = np.array(image)
    flat = pixels.reshape(-1, pixels.shape[-1])
    pixel_count = flat.shape[0]
    return flat, pixel_count


def generate_permutation(pixel_count, seed=SEED):
    rng = np.random.default_rng(seed)  # same seed -> same permutation; this is the "key"
    permutation = rng.permutation(pixel_count)
    return permutation


def shuffle_pixels(flat_pixels, permutation):
    shuffled = np.empty_like(flat_pixels)
    shuffled[permutation] = flat_pixels  # scatter: pixel i -> slot permutation[i]
    return shuffled


def indexed_dtype(channels):
    return np.dtype([("id", "<u4"), ("pixel", np.uint8, (channels,))])


def build_indexed_array(shuffled_pixels):
    count, channels = shuffled_pixels.shape
    indexed = np.empty(count, dtype=indexed_dtype(channels))
    indexed["id"] = np.arange(count)
    indexed["pixel"] = shuffled_pixels
    return indexed


def array_to_string(indexed_array):
    return indexed_array.tobytes()


def save_to_file(data, path=DATA_PATH):
    with open(path, "wb") as f:
        f.write(data)


def encode(path=PATH, seed=SEED):
    image, width, height = load_image(path)
    flat_pixels, pixel_count = flatten_pixels(image)
    permutation = generate_permutation(pixel_count, seed)
    shuffled = shuffle_pixels(flat_pixels, permutation)
    indexed = build_indexed_array(shuffled)
    data = array_to_string(indexed)
    save_to_file(data)
    channels = flat_pixels.shape[-1]
    return width, height, permutation, channels


# --- reversal ---------------------------------------------------------


def load_from_file(path=DATA_PATH):
    with open(path, "rb") as f:
        return f.read()


def string_to_array(data, channels):
    return np.frombuffer(data, dtype=indexed_dtype(channels))


def unshuffle_pixels(indexed_array, permutation):
    shuffled = indexed_array["pixel"]
    original = np.empty_like(shuffled)
    original[:] = shuffled[permutation]  # gather: the inverse of the scatter above
    return original


def save_image(pixel_array, width, height, path=OUTPUT_PATH):
    channels = pixel_array.shape[-1]
    image_array = pixel_array.reshape(height, width, channels)
    Image.fromarray(image_array.astype(np.uint8)).save(path)


def decode(width, height, permutation, channels):
    data = load_from_file()
    indexed = string_to_array(data, channels)
    original_pixels = unshuffle_pixels(indexed, permutation)
    save_image(original_pixels, width, height)


def main():
    width, height, permutation, channels = encode()
    decode(width, height, permutation, channels)


if __name__ == "__main__":
    main()
