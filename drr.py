"""Frame-resolved particle coverage and dust removal ratio (DRR).

Based on the user's 10sdDRR.py: gray enhancement, a fixed first-frame
percentile threshold, and DRR = (R0 - Rt) / R0. This version adds a CLI,
frame-directory input, explicit ROI masks, and guards for empty input.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def read_image(path: Path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)
    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError(f"Cannot read image: {path}")
    return frame


def frame_stream(path: Path):
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
        if not files:
            raise ValueError(f"No image frames in {path}")
        for file in files:
            yield read_image(file)
    elif path.is_file():
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {path}")
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                yield frame
        finally:
            cap.release()
    else:
        raise FileNotFoundError(path)


def infer_fps(path: Path, fallback: float) -> float:
    if path.is_dir():
        return fallback
    cap = cv2.VideoCapture(str(path))
    try:
        measured = float(cap.get(cv2.CAP_PROP_FPS))
    finally:
        cap.release()
    return measured if np.isfinite(measured) and measured > 0 else fallback


def enhance_gray(frame: np.ndarray, brightness: float, contrast: float) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
    sharp = cv2.filter2D(gray, -1, kernel)
    value = (sharp + brightness - 127.5) * contrast + 127.5
    return np.clip(value, 0, 255).astype(np.uint8)


def block_slices(length: int, blocks: int):
    return [(i * length // blocks, (i + 1) * length // blocks) for i in range(blocks)]


def first_frame_thresholds(gray: np.ndarray, roi: np.ndarray, blocks: int, percentile: float):
    if blocks > min(gray.shape):
        raise ValueError("Block count exceeds image dimensions")
    thresholds = np.full((blocks, blocks), 255, dtype=np.uint8)
    ys, xs = block_slices(gray.shape[0], blocks), block_slices(gray.shape[1], blocks)
    for row, (y0, y1) in enumerate(ys):
        for col, (x0, x1) in enumerate(xs):
            region = gray[y0:y1, x0:x1]
            selected = region[roi[y0:y1, x0:x1]]
            if selected.size:
                thresholds[row, col] = np.uint8(np.percentile(selected, percentile))
    return thresholds


def identify(gray: np.ndarray, roi: np.ndarray, thresholds: np.ndarray) -> np.ndarray:
    blocks = thresholds.shape[0]
    result = np.zeros(gray.shape, dtype=np.uint8)
    ys, xs = block_slices(gray.shape[0], blocks), block_slices(gray.shape[1], blocks)
    for row, (y0, y1) in enumerate(ys):
        for col, (x0, x1) in enumerate(xs):
            area = gray[y0:y1, x0:x1]
            selected = roi[y0:y1, x0:x1] & (area > thresholds[row, col])
            result[y0:y1, x0:x1][selected] = 255
    return result


def labeled_panel(raw: np.ndarray, mask: np.ndarray, width: int = 480) -> Image.Image:
    raw_rgb = cv2.cvtColor(raw, cv2.COLOR_BGR2RGB)
    raw_image = Image.fromarray(raw_rgb)
    mask_image = Image.fromarray(mask).convert("RGB")
    height = max(1, round(raw_image.height * width / raw_image.width))
    raw_image = raw_image.resize((width, height))
    mask_image = mask_image.resize((width, height))
    panel = Image.new("RGB", (width * 2, height + 22), "white")
    panel.paste(raw_image, (0, 22))
    panel.paste(mask_image, (width, 22))
    draw = ImageDraw.Draw(panel)
    draw.text((8, 4), "Input", fill="black")
    draw.text((width + 8, 4), "Detected particles", fill="black")
    return panel


def analyze(args: argparse.Namespace) -> dict:
    source = args.input.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    fps = infer_fps(source, args.fps)
    limit = max(1, int(np.ceil(args.seconds * fps)))
    stream = frame_stream(source)
    try:
        first = next(stream)
    except StopIteration as exc:
        raise ValueError("Input contains no frames") from exc

    first_raw_gray = cv2.cvtColor(first, cv2.COLOR_BGR2GRAY)
    if args.roi_mask:
        roi_image = read_image(args.roi_mask)
        if roi_image.shape[:2] != first.shape[:2]:
            raise ValueError("ROI mask and video frame dimensions differ")
        roi = cv2.cvtColor(roi_image, cv2.COLOR_BGR2GRAY) > 0
        roi_source = str(args.roi_mask)
    else:
        roi = first_raw_gray > 5
        roi_source = "nonblack pixels of the first frame"
    if args.roi_erode:
        kernel = np.ones((3, 3), dtype=np.uint8)
        roi = cv2.erode(roi.astype(np.uint8), kernel, iterations=args.roi_erode) > 0
    roi_area = int(roi.sum())
    if roi_area == 0:
        raise ValueError("ROI has zero pixels; provide --roi-mask")

    baseline_gray = enhance_gray(first, args.brightness, args.contrast)
    thresholds = first_frame_thresholds(baseline_gray, roi, args.blocks, args.percentile)
    rows, gif_panels = [], []
    first_panel = None
    last_frame = None
    last_mask = None
    baseline_ratio = None

    def process(index: int, frame: np.ndarray) -> None:
        nonlocal baseline_ratio, first_panel, last_frame, last_mask
        if frame.shape[:2] != first.shape[:2]:
            raise ValueError(f"Frame {index} dimensions changed")
        gray = enhance_gray(frame, args.brightness, args.contrast)
        mask = identify(gray, roi, thresholds)
        ratio = float((mask > 0).sum() / roi_area)
        if baseline_ratio is None:
            baseline_ratio = ratio
        drr = (baseline_ratio - ratio) / baseline_ratio if baseline_ratio > 0 else None
        rows.append({"frame": index, "time_s": index / fps, "dust_area_ratio": ratio,
                     "drr": drr, "clear_area_ratio": 1.0 - ratio})
        if index == 0 or (args.save_gif and index % args.gif_stride == 0):
            panel = labeled_panel(frame, mask)
            if index == 0:
                first_panel = panel
            if args.save_gif and index % args.gif_stride == 0:
                gif_panels.append(panel)
        last_frame, last_mask = frame, mask
        if index == 0:
            Image.fromarray((roi * 255).astype(np.uint8)).save(output / "roi_mask.png")

    process(0, first)
    for index, frame in enumerate(stream, start=1):
        if index >= limit:
            break
        process(index, frame)
    last_panel = labeled_panel(last_frame, last_mask)

    with (output / "metrics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    if first_panel and last_panel:
        comparison = Image.new("RGB", (first_panel.width, first_panel.height * 2), "white")
        comparison.paste(first_panel, (0, 0))
        comparison.paste(last_panel, (0, first_panel.height))
        comparison.save(output / "first_last_comparison.png")
    if gif_panels:
        gif_panels[0].save(output / "recognition_preview.gif", save_all=True,
                           append_images=gif_panels[1:], duration=max(40, round(1000 * args.gif_stride / fps)), loop=0)
    summary = {"input": str(source), "frames_processed": len(rows), "fps": fps,
               "roi_pixels": roi_area, "roi_source": roi_source,
               "first_ratio": baseline_ratio, "last_ratio": rows[-1]["dust_area_ratio"],
               "last_drr": rows[-1]["drr"], "thresholds": thresholds.tolist(),
               "formula": "DRR=(R0-Rt)/R0; CRR=1-Rt"}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Particle video recognition and DRR calculation")
    parser.add_argument("--input", type=Path, required=True, help="Video file or ordered image-frame folder")
    parser.add_argument("--output", type=Path, default=Path("results"))
    parser.add_argument("--roi-mask", type=Path, help="White ROI on black background, matching frame size")
    parser.add_argument("--fps", type=float, default=30.0, help="Frame-folder FPS or video fallback FPS")
    parser.add_argument("--seconds", type=float, default=10.0)
    parser.add_argument("--percentile", type=float, default=50.0)
    parser.add_argument("--blocks", type=int, default=1)
    parser.add_argument("--roi-erode", type=int, default=2,
                        help="Exclude ROI boundary pixels to reduce sharpening artifacts; 0 disables")
    parser.add_argument("--brightness", type=float, default=-20.0)
    parser.add_argument("--contrast", type=float, default=1.4)
    parser.add_argument("--save-gif", action="store_true")
    parser.add_argument("--gif-stride", type=int, default=3)
    args = parser.parse_args()
    if args.fps <= 0 or args.seconds <= 0 or args.blocks < 1 or not 0 <= args.percentile <= 100 or args.gif_stride < 1 or args.roi_erode < 0:
        parser.error("Check fps, seconds, blocks, percentile, gif-stride, and roi-erode")
    result = analyze(args)
    print(f"Processed {result['frames_processed']} frames; final DRR = {result['last_drr']}")
    print(f"Results: {args.output.resolve()}")


if __name__ == "__main__":
    main()
