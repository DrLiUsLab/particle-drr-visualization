"""Create a small, synthetic particle-removal sequence for the README demo."""

from pathlib import Path
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
FRAMES = HERE / "synthetic_frames"
FRAMES.mkdir(parents=True, exist_ok=True)

width, height = 220, 140
roi = (15, 15, 205, 125)
points = [(35 + col * 28, 38 + row * 28) for row in range(3) for col in range(6)]

mask = Image.new("L", (width, height), 0)
ImageDraw.Draw(mask).rectangle(roi, fill=255)
mask.save(HERE / "synthetic_roi_mask.png")

for frame_index in range(30):
    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle(roi, fill=(55, 55, 55))
    remaining = max(1, len(points) - frame_index // 2)
    for index, (x, y) in enumerate(points[:remaining]):
        dx = round(1.5 * frame_index * ((index % 3) - 1))
        draw.ellipse((x + dx - 4, y - 4, x + dx + 4, y + 4), fill=(30, 225, 30))
    image.save(FRAMES / f"frame_{frame_index:03d}.png")

print(f"Synthetic example: {len(list(FRAMES.glob('*.png')))} frames in {FRAMES}")
