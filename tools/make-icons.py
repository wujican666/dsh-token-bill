"""Generate the icon set for dsh-token-bill.

Output: ../assets/icons/<name>.ico (16..256) + <name>.png (256), plus preview.png
Run:    py -3.15 tools/make-icons.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

S = 1024
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(BASE, "..", "assets", "icons"))
os.makedirs(OUT, exist_ok=True)

BG_TOP = (34, 34, 38)
BG_BOT = (10, 10, 12)
BLUE = (10, 132, 255, 255)
BLUE_D = (0, 84, 190, 255)
BLUE_L = (86, 176, 255, 255)
WHITE = (246, 246, 248, 255)
ORANGE = (255, 159, 10, 255)
K = S / 256.0


def font(size, bold=True):
    names = ("arialbd.ttf", "seguisb.ttf", "segoeuib.ttf") if bold else ("arial.ttf", "segoeui.ttf")
    for n in names:
        p = os.path.join(r"C:\Windows\Fonts", n)
        if os.path.exists(p):
            return ImageFont.truetype(p, int(size))
    return ImageFont.load_default()


def base():
    """Dark rounded square with a subtle gradient + hairline border."""
    grad = Image.new("RGBA", (1, S))
    for y in range(S):
        t = y / (S - 1.0)
        grad.putpixel((0, y), tuple(int(BG_TOP[i] * (1 - t) + BG_BOT[i] * t) for i in range(3)) + (255,))
    grad = grad.resize((S, S))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.225), fill=255)
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    ImageDraw.Draw(img).rounded_rectangle([5, 5, S - 6, S - 6], radius=int(S * 0.215),
                                         outline=(255, 255, 255, 24), width=5)
    return img


def center_text(d, cx, cy, text, f, fill):
    box = d.textbbox((0, 0), text, font=f)
    d.text((cx - (box[2] - box[0]) / 2.0 - box[0], cy - (box[3] - box[1]) / 2.0 - box[1]),
           text, font=f, fill=fill)


def icon_bill():
    img = base()
    x0, y0, x1, y1 = 78 * K, 46 * K, 178 * K, 202 * K
    mask = Image.new("L", (S, S), 0)
    dm = ImageDraw.Draw(mask)
    dm.rounded_rectangle([x0, y0, x1, y1], radius=16 * K, fill=255)
    n = 6
    w = (x1 - x0) / n
    for i in range(n):
        cx = x0 + w * (i + 0.5)
        dm.polygon([(cx - w / 2, y1 - 18 * K), (cx, y1 + 6 * K), (cx + w / 2, y1 - 18 * K)], fill=0)
    img.paste(Image.new("RGBA", (S, S), WHITE), (0, 0), mask)
    d = ImageDraw.Draw(img)
    center_text(d, (x0 + x1) / 2, 116 * K, "\u00a5", font(96 * K), BLUE)
    d.rounded_rectangle([100 * K, 158 * K, 156 * K, 170 * K], radius=6 * K, fill=BLUE)
    d.rounded_rectangle([100 * K, 178 * K, 138 * K, 190 * K], radius=6 * K, fill=(10, 132, 255, 150))
    return img


def icon_campus():
    img = base()
    d = ImageDraw.Draw(img)
    d.polygon([(128 * K, 66 * K), (216 * K, 112 * K), (128 * K, 158 * K), (40 * K, 112 * K)], fill=BLUE)
    d.polygon([(128 * K, 92 * K), (188 * K, 120 * K), (128 * K, 148 * K), (68 * K, 120 * K)], fill=BLUE_L)
    d.polygon([(68 * K, 148 * K), (188 * K, 148 * K), (172 * K, 182 * K), (84 * K, 182 * K)], fill=BLUE_D)
    d.line([(198 * K, 118 * K), (208 * K, 166 * K)], fill=ORANGE, width=int(10 * K))
    d.ellipse([200 * K, 162 * K, 220 * K, 182 * K], fill=ORANGE)
    return img


def icon_coin():
    img = base()
    d = ImageDraw.Draw(img)
    d.ellipse([40 * K, 40 * K, 216 * K, 216 * K], fill=BLUE_D)
    d.ellipse([46 * K, 46 * K, 210 * K, 210 * K], fill=BLUE)
    d.ellipse([60 * K, 60 * K, 196 * K, 196 * K], outline=(255, 255, 255, 150), width=int(7 * K))
    center_text(d, 128 * K, 130 * K, "\u00a5", font(104 * K), WHITE)
    return img


def icon_chart():
    img = base()
    d = ImageDraw.Draw(img)
    bars = ((70, 128, BLUE), (114, 96, BLUE), (158, 168, ORANGE))
    for x, top, col in bars:
        d.rounded_rectangle([x * K, top * K, (x + 30) * K, 200 * K], radius=9 * K, fill=col)
    pts = [(62 * K, 104 * K), (118 * K, 70 * K), (168 * K, 92 * K), (196 * K, 52 * K)]
    d.line(pts, fill=WHITE, width=int(9 * K), joint="curve")
    d.polygon([(196 * K, 34 * K), (212 * K, 62 * K), (182 * K, 60 * K)], fill=WHITE)
    return img


def icon_whale():
    img = base()
    d = ImageDraw.Draw(img)
    d.polygon([(170 * K, 148 * K), (230 * K, 112 * K), (210 * K, 158 * K)], fill=BLUE)
    d.polygon([(170 * K, 162 * K), (230 * K, 198 * K), (210 * K, 152 * K)], fill=BLUE)
    d.ellipse([46 * K, 118 * K, 194 * K, 194 * K], fill=BLUE)
    d.ellipse([62 * K, 150 * K, 178 * K, 192 * K], fill=(255, 255, 255, 55))
    d.ellipse([98 * K, 132 * K, 116 * K, 150 * K], fill=WHITE)
    d.arc([126 * K, 150 * K, 184 * K, 190 * K], start=20, end=80, fill=WHITE, width=int(7 * K))
    for x, y, r in ((104, 82, 13), (128, 62, 10), (150, 86, 8)):
        d.ellipse([(x - r) * K, (y - r) * K, (x + r) * K, (y + r) * K], fill=BLUE_L)
    return img


ICONS = [
    ("bill", "\u6536\u636e\uff1a\u603b\u8d26\u5355", icon_bill),
    ("campus", "\u5b66\u58eb\u5e3d\uff1a\u5b66\u6821", icon_campus),
    ("coin", "\u91d1\u5e01\uff1a\u7701\u94b1", icon_coin),
    ("chart", "\u67f1\u72b6\u56fe\uff1a\u7528\u91cf", icon_chart),
    ("whale", "\u5c0f\u9cb8\u9c7c\uff1aDSH \u540c\u6b3e", icon_whale),
]


def main():
    made = []
    for name, _label, fn in ICONS:
        img = fn().resize((256, 256), Image.LANCZOS)
        png = os.path.join(OUT, name + ".png")
        img.save(png)
        ico = os.path.join(OUT, name + ".ico")
        img.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        made.append((name, png, ico))
        print("wrote", ico, os.path.getsize(ico), "bytes;", png, os.path.getsize(png))

    # preview strip for the user to choose from
    pad, cell, label_h = 28, 200, 54
    W = pad + len(ICONS) * (cell + pad)
    H = pad + cell + label_h + pad
    sheet = Image.new("RGBA", (W, H), (18, 18, 20, 255))
    ds = ImageDraw.Draw(sheet)
    f = ImageFont.truetype(os.path.join(r"C:\Windows\Fonts", "msyh.ttc"), 26)
    fn_ = ImageFont.truetype(os.path.join(r"C:\Windows\Fonts", "arialbd.ttf"), 30)
    for i, (name, label, _fn) in enumerate(ICONS):
        x = pad + i * (cell + pad)
        big = Image.open(os.path.join(OUT, name + ".png")).resize((cell, cell), Image.LANCZOS)
        sheet.paste(big, (x, pad), big)
        center_text(ds, x + cell / 2, pad + cell + 6, str(i + 1), fn_, (255, 255, 255, 255))
        center_text(ds, x + cell / 2, pad + cell + 30, label, f, (163, 163, 168, 255))
    prev = os.path.join(OUT, "preview.png")
    sheet.save(prev)
    print("wrote", prev, os.path.getsize(prev), "bytes")


if __name__ == "__main__":
    main()
