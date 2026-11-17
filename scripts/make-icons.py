"""Draws the app icons from the VIDHI brand mark already used in the app (the diamond in a diamond, as on the sign-in page).

    python scripts/make-icons.py

Writes frontend/public: favicon.svg, favicon.ico, favicon-16x16.png, favicon-32x32.png, apple-touch-icon.png, icon-192.png, icon-512.png,
icon-maskable-512.png. This is a stand-in until the owner has a designed logo: replace the files (same names and sizes) and nothing else changes."""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "frontend" / "public"
BG, BLUE = (11, 12, 13, 255), (91, 140, 255, 255)
SS = 4  # draw big, then shrink for smooth edges


def mark(size: int, safe: float, rounded: bool) -> Image.Image:
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, n - 1, n - 1], radius=int(n * 0.22) if rounded else 0, fill=BG)
    c, r = n / 2, n / 2 * safe

    def diamond(radius, fill=None, outline=None, width=0):
        d.polygon([(c, c - radius), (c + radius, c), (c, c + radius), (c - radius, c)], fill=fill, outline=outline, width=width)

    # outer diamond ring: a filled diamond with a smaller background diamond cut out, then a solid centre
    diamond(r, fill=BLUE)
    diamond(r * 0.80, fill=BG)
    diamond(r * 0.46, fill=BLUE)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    mark(512, 0.72, True).save(OUT / "icon-512.png")
    mark(192, 0.72, True).save(OUT / "icon-192.png")
    mark(512, 0.50, False).save(OUT / "icon-maskable-512.png")  # full-bleed: the phone crops it to its own shape, so the mark sits well inside
    mark(180, 0.72, False).save(OUT / "apple-touch-icon.png")  # iOS rounds the corners itself
    mark(32, 0.80, True).save(OUT / "favicon-32x32.png")
    mark(16, 0.80, True).save(OUT / "favicon-16x16.png")
    mark(48, 0.80, True).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    (OUT / "favicon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 104 104"><rect width="104" height="104" rx="23" fill="#0B0C0D"/>'
        '<path d="M52 14 90 52 52 90 14 52Z" fill="#5B8CFF"/><path d="M52 21.6 82.4 52 52 82.4 21.6 52Z" fill="#0B0C0D"/>'
        '<path d="M52 36 68 52 52 68 36 52Z" fill="#5B8CFF"/></svg>\n',
        encoding="utf-8",
    )
    print("icons written to", OUT)


main()