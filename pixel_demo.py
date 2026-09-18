import argparse
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.patches import ConnectionPatch

SCRIPT_DIR = Path(__file__).resolve().parent
SEED = 1234
PLACEHOLDER = 000  # gray value standing in for "not yet revealed" pixels

# how many animation frames each phase of the pipeline gets
PHASE_FRAMES = {
    "separate": 15,
    "shuffle": 90,
    "serialize": 15,
    "save": 8,
    "load": 8,
    "parse": 15,
    "unshuffle": 90,
    "done": 20,
}

TRACK_COUNT = 10  # how many pixels get a visible path + console callout
LOG_LINES_VISIBLE = 20  # scrollback depth of each console panel
TRACK_MARKER_SIZE = 6 / 16  # circle marker size for each tracked pixel


def pick_tracked_pixels(pixel_count, count=TRACK_COUNT):
    return np.linspace(0, pixel_count - 1, count, dtype=int)


def load_image(path):
    return np.array(Image.open(path).convert("RGB"))


def indexed_dtype(channels):
    return np.dtype([("id", "<u4"), ("pixel", np.uint8, (channels,))])


def demo_wire_format(flat, permutation, channels, count=3):
    dtype = indexed_dtype(channels)
    print(f"\n=== Wire format demo (first {count} pixels) ===")
    print(f"Each record on disk: {dtype.itemsize} bytes = uint32 id + {channels} uint8 channel(s)\n")

    for src in range(count):
        dest = int(permutation[src])
        color = tuple(int(c) for c in flat[src])

        record = np.empty(1, dtype=dtype)
        record["id"] = dest
        record["pixel"] = flat[src]
        raw = record.tobytes()

        parsed = np.frombuffer(raw, dtype=dtype)[0]
        parsed_id = int(parsed["id"])
        parsed_color = tuple(int(c) for c in parsed["pixel"])

        print(f"pixel #{src} color={color} -> stored at id={dest}")
        print(f"  SENT     (bytes) : {raw!r}")
        print(f"  SENT     (hex)   : {raw.hex()}")
        print(f"  RECEIVED (parsed): id={parsed_id}, pixel={parsed_color}")
        print(f"  round-trip match : {parsed_id == dest and parsed_color == color}\n")


def build_wire_string(flat, permutation, channels):
    indexed = np.empty(flat.shape[0], dtype=indexed_dtype(channels))
    indexed["id"] = permutation
    indexed["pixel"] = flat
    return indexed.tobytes()


def demo_full_wire_string(flat, permutation, channels, preview_bytes=200, full=False):
    wire_bytes = build_wire_string(flat, permutation, channels)
    print(f"\n=== Full transfer string ({len(wire_bytes):,} bytes total) ===")
    print("This is the literal byte string sent from the sending device to the")
    print("receiving device, before it is parsed back into pixels.\n")

    if full or len(wire_bytes) <= preview_bytes * 2:
        print(f"STRING (bytes): {wire_bytes!r}")
        print(f"STRING (hex)  : {wire_bytes.hex()}")
    else:
        head, tail = wire_bytes[:preview_bytes], wire_bytes[-preview_bytes:]
        print(f"STRING (first {preview_bytes} bytes): {head!r} ...")
        print(f"STRING (last {preview_bytes} bytes) : ... {tail!r}")
        print(
            f"(middle omitted for brevity — {len(wire_bytes):,} bytes total; "
            "pass --full-string to print every byte)"
        )
    return wire_bytes


def build_timeline():
    timeline = []
    for phase, n in PHASE_FRAMES.items():
        for f in range(n):
            timeline.append((phase, f, n))
    return timeline


def run(
    image_path,
    fps,
    wire_demo_count=3,
    show_full_string=True,
    full_string=False,
    full_string_preview=200,
    track_count=TRACK_COUNT,
    save_path=None,
):
    if save_path:
        plt.switch_backend("Agg")  # headless, for writing a GIF instead of opening a window

    original = load_image(image_path)
    height, width, channels = original.shape
    flat = original.reshape(-1, channels)
    pixel_count = flat.shape[0]

    permutation = np.random.default_rng(SEED).permutation(pixel_count)
    shuffled_full = np.empty_like(flat)
    shuffled_full[permutation] = flat

    if wire_demo_count:
        demo_wire_format(flat, permutation, channels, count=wire_demo_count)

    if show_full_string:
        demo_full_wire_string(
            flat, permutation, channels, preview_bytes=full_string_preview, full=full_string
        )

    shuffled_view = np.full_like(flat, PLACEHOLDER)
    reconstructed_view = np.full_like(flat, PLACEHOLDER)

    record_bytes = 4 + channels  # uint32 id + one byte per channel
    total_bytes = pixel_count * record_bytes

    fig = plt.figure(figsize=(13, 8))
    fig.canvas.manager.set_window_title("Pixel Permutation Lab")
    gs = fig.add_gridspec(2, 6, height_ratios=[2, 1.3])
    ax_orig = fig.add_subplot(gs[0, 0:2])
    ax_shuf = fig.add_subplot(gs[0, 2:4])
    ax_recon = fig.add_subplot(gs[0, 4:6])
    for ax, title in zip((ax_orig, ax_shuf, ax_recon), ["Original", "Shuffled", "Reconstructed"]):
        ax.set_title(title)
        ax.axis("off")

    ax_sender_log = fig.add_subplot(gs[1, 0:3])
    ax_receiver_log = fig.add_subplot(gs[1, 3:6])
    for ax, title in zip((ax_sender_log, ax_receiver_log), ["DEVICE A — sender", "DEVICE B — receiver"]):
        ax.set_title(title, loc="left", color="#dddddd", fontsize=10)
        ax.set_facecolor("black")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color("#444444")

    sender_lines = deque(maxlen=LOG_LINES_VISIBLE)
    receiver_lines = deque(maxlen=LOG_LINES_VISIBLE)
    sender_text = ax_sender_log.text(
        0.02, 0.96, "", transform=ax_sender_log.transAxes, va="top", ha="left",
        family="monospace", fontsize=8, color="#3dff6e",
    )
    receiver_text = ax_receiver_log.text(
        0.02, 0.96, "", transform=ax_receiver_log.transAxes, va="top", ha="left",
        family="monospace", fontsize=8, color="#3dff6e",
    )

    def log(lines, message):
        lines.append(message)

    ax_orig.imshow(original)
    im_shuffled = ax_shuf.imshow(shuffled_view.reshape(height, width, channels))
    im_reconstructed = ax_recon.imshow(reconstructed_view.reshape(height, width, channels))
    status = fig.suptitle("")

    # tracked pixels get a drawn path across panels; every pixel still gets a console line
    track_count = max(0, min(track_count, pixel_count))
    tracked_src = pick_tracked_pixels(pixel_count, count=track_count) if track_count else []
    palette = plt.cm.tab10(np.linspace(0, 1, max(track_count, 1)))
    tracked = []
    for src, color in zip(tracked_src, palette):
        src = int(src)
        dest = int(permutation[src])
        src_row, src_col = divmod(src, width)
        dest_row, dest_col = divmod(dest, width)

        ax_orig.plot(src_col, src_row, marker="o", color=color, ms=TRACK_MARKER_SIZE, mec="white", mew=0.8, zorder=5)

        marker_shuf, = ax_shuf.plot(dest_col, dest_row, marker="o", color=color, ms=TRACK_MARKER_SIZE, mec="white", mew=0.8, zorder=5)
        marker_shuf.set_visible(False)
        marker_recon, = ax_recon.plot(src_col, src_row, marker="o", color=color, ms=TRACK_MARKER_SIZE, mec="white", mew=0.8, zorder=5)
        marker_recon.set_visible(False)

        forward_path = ConnectionPatch(
            xyA=(src_col, src_row), coordsA="data", axesA=ax_orig,
            xyB=(dest_col, dest_row), coordsB="data", axesB=ax_shuf,
            color=color, lw=1.3, alpha=0.85, arrowstyle="-|>", mutation_scale=12, zorder=4,
        )
        forward_path.set_visible(False)
        fig.add_artist(forward_path)

        backward_path = ConnectionPatch(
            xyA=(dest_col, dest_row), coordsA="data", axesA=ax_shuf,
            xyB=(src_col, src_row), coordsB="data", axesB=ax_recon,
            color=color, lw=1.3, alpha=0.85, arrowstyle="-|>", mutation_scale=12, zorder=4,
        )
        backward_path.set_visible(False)
        fig.add_artist(backward_path)

        tracked.append({
            "src": src,
            "dest": dest,
            "marker_shuf": marker_shuf,
            "marker_recon": marker_recon,
            "forward_path": forward_path,
            "backward_path": backward_path,
        })

    tracked_by_src = {t["src"]: t for t in tracked}

    timeline = build_timeline()

    def update(step):
        phase, f, n = timeline[step]
        frac = (f + 1) / n
        n_prev = int((f / n) * pixel_count)
        n_new = int(frac * pixel_count)

        if phase == "separate" and f == 0:
            log(sender_lines, f"[DEVICE A] loading image, flattening to {pixel_count:,} pixels...")

        elif phase == "shuffle":
            if f == 0:
                log(sender_lines, f"[DEVICE A] shuffling pixels with permutation (seed={SEED})...")
            srcs = np.arange(n_prev, n_new)
            dests = permutation[srcs]
            shuffled_view[dests] = flat[srcs]
            im_shuffled.set_data(shuffled_view.reshape(height, width, channels))

            revealed_tracked = []
            for s, d, c in zip(srcs.tolist(), dests.tolist(), flat[srcs].tolist()):
                log(sender_lines, f"[DEVICE A] px {s:>6} {tuple(c)} -> slot {d:>6}")
                if s in tracked_by_src:
                    revealed_tracked.append(s)
            for s in revealed_tracked:
                t = tracked_by_src[s]
                t["marker_shuf"].set_visible(True)
                t["forward_path"].set_visible(True)
                log(sender_lines, f"[DEVICE A] px {s:>6} -> slot {t['dest']:>6}  *** tracked path ***")

        elif phase == "serialize":
            if f == 0:
                log(sender_lines, "[DEVICE A] packing (id, pixel) records into a byte string...")
            if f == n - 1:
                log(sender_lines, f"[DEVICE A] serialized {total_bytes:,} bytes")

        elif phase == "save":
            if f == 0:
                log(sender_lines, f"[DEVICE A] sending {total_bytes:,} bytes to Device B...")
            if f == n - 1:
                log(sender_lines, "[DEVICE A] transfer sent")

        elif phase == "load":
            if f == 0:
                log(receiver_lines, f"[DEVICE B] receiving {total_bytes:,} bytes from Device A...")
            if f == n - 1:
                log(receiver_lines, "[DEVICE B] all bytes received")

        elif phase == "parse":
            if f == 0:
                log(receiver_lines, "[DEVICE B] parsing byte string into (id, pixel) records...")

        elif phase == "unshuffle":
            if f == 0:
                log(receiver_lines, "[DEVICE B] placing pixels back at their original positions...")
            srcs = np.arange(n_prev, n_new)
            dests = permutation[srcs]
            reconstructed_view[srcs] = shuffled_full[dests]
            im_reconstructed.set_data(reconstructed_view.reshape(height, width, channels))

            revealed_tracked = []
            for s, d in zip(srcs.tolist(), dests.tolist()):
                log(receiver_lines, f"[DEVICE B] slot {d:>6} -> px {s:>6} restored")
                if s in tracked_by_src:
                    revealed_tracked.append(s)
            for s in revealed_tracked:
                t = tracked_by_src[s]
                t["marker_recon"].set_visible(True)
                t["backward_path"].set_visible(True)
                log(receiver_lines, f"[DEVICE B] slot {t['dest']:>6} -> px {s:>6} restored  *** tracked path ***")

        elif phase == "done" and f == 0:
            match = np.array_equal(reconstructed_view, flat)
            print(f"Bit-for-bit match: {match}")
            print(f"{pixel_count:,} pixels -> {total_bytes:,} bytes as shuffled.dat")
            log(receiver_lines, f"[DEVICE B] reconstruction complete — bit-for-bit match: {match}")

        sender_text.set_text("\n".join(sender_lines))
        receiver_text.set_text("\n".join(receiver_lines))
        status.set_text(f"{phase.upper()} — {int(frac * 100)}%")
        artists = [im_shuffled, im_reconstructed, status, sender_text, receiver_text]
        for t in tracked:
            artists.extend((t["marker_shuf"], t["marker_recon"], t["forward_path"], t["backward_path"]))
        return artists

    anim = FuncAnimation(fig, update, frames=len(timeline), interval=1000 / fps, repeat=False)

    paused = {"value": False}

    def on_key(event):
        if event.key == " ":
            if paused["value"]:
                anim.event_source.start()
            else:
                anim.event_source.stop()
            paused["value"] = not paused["value"]

    fig.canvas.mpl_connect("key_press_event", on_key)

    fig.subplots_adjust(top=0.93, bottom=0.04, left=0.03, right=0.97, hspace=0.05, wspace=0.3)

    if save_path:
        anim.save(save_path, writer=PillowWriter(fps=fps))
    else:
        plt.show()
    return anim  # keep a reference alive for interactive use (e.g. in a REPL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", default=str(SCRIPT_DIR / "injection_test.png"))
    parser.add_argument("--fps", type=float, default=45)
    parser.add_argument(
        "--wire-demo-count",
        type=int,
        default=3,
        help="print this many raw sent/received byte records before animating (0 to skip)",
    )
    parser.add_argument(
        "--no-wire-string",
        dest="show_full_string",
        action="store_false",
        help="don't print the full device-to-device transfer string",
    )
    parser.add_argument(
        "--full-string",
        action="store_true",
        help="print every byte of the transfer string instead of a head/tail preview",
    )
    parser.add_argument(
        "--string-preview-bytes",
        type=int,
        default=200,
        help="how many bytes to show from each end of the transfer string preview",
    )
    parser.add_argument(
        "--track-count",
        type=int,
        default=TRACK_COUNT,
        help="how many pixels get a drawn path + highlighted console line (0 to disable paths)",
    )
    parser.add_argument(
        "--save",
        metavar="PATH",
        help="save the animation as a GIF to PATH instead of opening an interactive window",
    )
    args = parser.parse_args()
    run(
        args.image,
        args.fps,
        args.wire_demo_count,
        show_full_string=args.show_full_string,
        full_string=args.full_string,
        full_string_preview=args.string_preview_bytes,
        track_count=args.track_count,
        save_path=args.save,
    )
