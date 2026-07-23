"""Generate stylized placeholder product images for Scout's demo catalog.

Every product in Scout's catalog is explicitly synthetic demo data
(see scout/database/seed.py's module docstring) - there is no real
photograph to source. Rather than leave every product card showing a
broken "no image available" placeholder, this script generates a
clean, deterministic, category-themed illustration for each product:
a solid color background (per category), a simple flat icon (matched
to subcategory), and the product name - honestly representing "this
is a demo product" rather than pretending to be real photography.

Run once after seeding the database (or whenever PRODUCTS changes):
    python scripts/generate_product_images.py

Requires Pillow:
    pip install pillow
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from scout.database.seed import PRODUCTS  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "web" / "public" / "images" / "products"
SIZE = (640, 480)  # 4:3, matches ProductCard's rendered aspect ratio

CATEGORY_COLORS = {
    "Footwear": "#D9734E",
    "Bags": "#7C8A5C",
    "Electronics": "#3E5C76",
    "Home and Kitchen": "#C98A3B",
}


def _font(size: int):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _icon_shoe(draw, cx, cy, color):
    draw.polygon(
        [
            (cx - 110, cy + 40), (cx - 110, cy + 10), (cx - 60, cy - 30),
            (cx - 10, cy - 35), (cx + 40, cy - 10), (cx + 120, cy + 5),
            (cx + 120, cy + 40),
        ],
        fill=color,
    )
    draw.rectangle([cx - 115, cy + 40, cx + 120, cy + 55], fill=color)


def _icon_backpack(draw, cx, cy, color):
    draw.rounded_rectangle([cx - 70, cy - 60, cx + 70, cy + 80], radius=28, fill=color)
    draw.rounded_rectangle([cx - 30, cy - 90, cx + 30, cy - 40], radius=14, outline=color, width=10)
    draw.rounded_rectangle([cx - 45, cy - 10, cx + 45, cy + 40], radius=10, fill="#00000022")


def _icon_duffel(draw, cx, cy, color):
    draw.rounded_rectangle([cx - 120, cy - 45, cx + 120, cy + 55], radius=45, fill=color)
    draw.arc([cx - 60, cy - 90, cx + 60, cy - 10], start=180, end=360, fill=color, width=12)


def _icon_tote(draw, cx, cy, color):
    draw.polygon(
        [(cx - 90, cy - 20), (cx + 90, cy - 20), (cx + 70, cy + 80), (cx - 70, cy + 80)],
        fill=color,
    )
    draw.arc([cx - 45, cy - 70, cx - 5, cy - 10], start=180, end=360, fill=color, width=8)
    draw.arc([cx + 5, cy - 70, cx + 45, cy - 10], start=180, end=360, fill=color, width=8)


def _icon_earbuds(draw, cx, cy, color):
    draw.ellipse([cx - 90, cy - 30, cx - 30, cy + 30], fill=color)
    draw.ellipse([cx + 30, cy - 30, cx + 90, cy + 30], fill=color)
    draw.arc([cx - 60, cy - 60, cx + 60, cy + 20], start=200, end=340, fill=color, width=8)


def _icon_speaker(draw, cx, cy, color):
    draw.rounded_rectangle([cx - 60, cy - 90, cx + 60, cy + 90], radius=30, fill=color)
    draw.ellipse([cx - 35, cy - 20, cx + 35, cy + 50], outline="#00000033", width=8)


def _icon_tablet(draw, cx, cy, color):
    draw.rounded_rectangle([cx - 80, cy - 100, cx + 80, cy + 100], radius=14, outline=color, width=12)


def _icon_wearable(draw, cx, cy, color):
    draw.rounded_rectangle([cx - 45, cy - 60, cx + 45, cy + 60], radius=18, fill=color)
    draw.rectangle([cx - 15, cy - 100, cx + 15, cy - 60], fill=color)
    draw.rectangle([cx - 15, cy + 60, cx + 15, cy + 100], fill=color)


def _icon_charger(draw, cx, cy, color):
    draw.rounded_rectangle([cx - 55, cy - 90, cx + 55, cy + 90], radius=20, fill=color)
    draw.polygon(
        [(cx - 10, cy - 30), (cx + 15, cy - 30), (cx - 5, cy + 10), (cx + 20, cy + 10),
         (cx - 15, cy + 60), (cx - 5, cy + 5), (cx - 25, cy + 5)],
        fill="#ffffffcc",
    )


def _icon_smart_home(draw, cx, cy, color):
    draw.rounded_rectangle([cx - 80, cy - 70, cx + 80, cy + 50], radius=16, fill=color)
    draw.rectangle([cx - 15, cy + 50, cx + 15, cy + 75], fill=color)
    draw.rectangle([cx - 40, cy + 75, cx + 40, cy + 88], fill=color)


def _icon_coffee(draw, cx, cy, color):
    draw.rounded_rectangle([cx - 55, cy - 30, cx + 55, cy + 90], radius=16, fill=color)
    draw.polygon([(cx + 55, cy - 5), (cx + 90, cy + 10), (cx + 55, cy + 45)], fill=color)
    draw.rounded_rectangle([cx - 65, cy - 60, cx + 65, cy - 30], radius=10, fill=color)


def _icon_kettle(draw, cx, cy, color):
    draw.ellipse([cx - 65, cy - 20, cx + 65, cy + 90], fill=color)
    draw.polygon([(cx + 55, cy - 5), (cx + 100, cy - 20), (cx + 70, cy + 20)], fill=color)
    draw.arc([cx - 60, cy - 60, cx + 20, cy - 5], start=200, end=350, fill=color, width=10)


def _icon_lamp(draw, cx, cy, color):
    draw.polygon([(cx - 55, cy - 60), (cx + 55, cy - 60), (cx + 35, cy), (cx - 35, cy)], fill=color)
    draw.rectangle([cx - 6, cy, cx + 6, cy + 70], fill=color)
    draw.rectangle([cx - 45, cy + 70, cx + 45, cy + 85], fill=color)


def _icon_storage(draw, cx, cy, color):
    for i, w in enumerate((100, 80, 60)):
        y0 = cy - 20 + i * 40
        draw.rounded_rectangle([cx - w // 2, y0, cx + w // 2, y0 + 30], radius=8, fill=color)


def _icon_fridge(draw, cx, cy, color):
    draw.rounded_rectangle([cx - 55, cy - 100, cx + 55, cy + 100], radius=14, fill=color)
    draw.line([cx - 55, cy - 20, cx + 55, cy - 20], fill="#00000033", width=6)
    draw.rectangle([cx + 30, cy - 80, cx + 38, cy - 40], fill="#ffffffaa")


def _icon_generic(draw, cx, cy, color):
    draw.rounded_rectangle([cx - 80, cy - 80, cx + 80, cy + 80], radius=24, fill=color)


_SUBCATEGORY_ICONS = [
    (("backpack", "day pack"), _icon_backpack),
    (("duffel",), _icon_duffel),
    (("tote", "briefcase", "sling"), _icon_tote),
    (("earbud",), _icon_earbuds),
    (("speaker",), _icon_speaker),
    (("tablet",), _icon_tablet),
    (("wearable",), _icon_wearable),
    (("charger", "power"), _icon_charger),
    (("smart home",), _icon_smart_home),
    (("coffee",), _icon_coffee),
    (("kettle",), _icon_kettle),
    (("lighting",), _icon_lamp),
    (("food storage",), _icon_storage),
    (("small appliance",), _icon_fridge),
]

_CATEGORY_FALLBACK = {
    "Footwear": _icon_shoe,
    "Bags": _icon_backpack,
    "Electronics": _icon_generic,
    "Home and Kitchen": _icon_generic,
}


def _pick_icon(category: str, subcategory: str):
    if category == "Footwear":
        return _icon_shoe
    sub_lower = subcategory.lower()
    for keywords, fn in _SUBCATEGORY_ICONS:
        if any(k in sub_lower for k in keywords):
            return fn
    return _CATEGORY_FALLBACK.get(category, _icon_generic)


def _wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def generate_image(product: dict) -> Image.Image:
    color = CATEGORY_COLORS.get(product["category"], "#666666")
    image = Image.new("RGB", SIZE, color)
    draw = ImageDraw.Draw(image)

    icon_fn = _pick_icon(product["category"], product["subcategory"])
    icon_fn(draw, SIZE[0] // 2, 190, "#ffffff")

    name_font = _font(30)
    lines = _wrap_text(draw, product["name"], name_font, SIZE[0] - 80)
    y = 340
    for line in lines[:2]:
        width = draw.textlength(line, font=name_font)
        draw.text(((SIZE[0] - width) / 2, y), line, font=name_font, fill="#ffffff")
        y += 38

    brand_font = _font(20)
    brand_width = draw.textlength(product["brand"], font=brand_font)
    draw.text(((SIZE[0] - brand_width) / 2, y + 6), product["brand"], font=brand_font, fill="#ffffffcc")

    return image


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for product in PRODUCTS:
        image = generate_image(product)
        out_path = OUTPUT_DIR / f"{product['product_id']}.webp"
        image.save(out_path, "WEBP", quality=90)
        print(f"wrote {out_path.relative_to(REPO_ROOT)}")
    print(f"Generated {len(PRODUCTS)} product images in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()