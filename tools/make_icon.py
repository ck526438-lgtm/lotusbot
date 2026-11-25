"""Génère assets/lotus.png et assets/lotus.ico (fleur de lotus stylisée)."""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

S = 1024
OUT = Path(__file__).resolve().parents[1] / "assets"


def petal(draw, cx, cy, length, width, angle, fill):
    pts = []
    for t in range(0, 181, 4):
        a = math.radians(t)
        x = math.sin(a) * width / 2 * (1 - 0.15 * math.cos(a))
        y = -length * (1 - math.cos(a)) / 2
        pts.append((x, y))
    pts += [(-x, y) for x, y in reversed(pts)]
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    draw.polygon([(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts], fill=fill)


def main():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((40, 40, S - 40, S - 40), radius=220, fill=(15, 17, 21, 255))
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((230, 260, 794, 820), fill=(232, 111, 168, 90))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(90)))
    d = ImageDraw.Draw(img)
    cx, cy = S / 2, 700
    layers = [(-62, (155, 60, 110, 255)), (62, (155, 60, 110, 255)),
              (-36, (205, 85, 145, 255)), (36, (205, 85, 145, 255)), (0, (240, 130, 185, 255))]
    for ang, col in layers:
        petal(d, cx, cy, 430 if ang == 0 else 380, 210, ang, col)
    d.ellipse((cx - 300, cy - 18, cx + 300, cy + 40), fill=(62, 207, 142, 255))
    d.line([(250, 840), (420, 800), (560, 830), (774, 790)], fill=(62, 207, 142, 255), width=22, joint="curve")
    OUT.mkdir(exist_ok=True)
    img.resize((256, 256), Image.LANCZOS).save(OUT / "lotus.png")
    img.save(OUT / "lotus.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


if __name__ == "__main__":
    main()
