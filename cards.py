import io
import os
from PIL import Image, ImageDraw, ImageFont

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
FONT = os.path.join(ASSETS, "font.ttf")
LOGO = os.path.join(ASSETS, "logo.jpg")
EXAMPLE = os.path.join(ASSETS, "example_tag.jpg")
GOLD = (255, 200, 40)
VIOLET = (150, 90, 255)

def _font(size):
    return ImageFont.truetype(FONT, size)

def _gradient(w, h, top, bottom):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3)))
    return img

def _fit(d, text, max_w, size):
    while size > 16 and d.textlength(text, font=_font(size)) > max_w:
        size -= 2
    return _font(size)

def _center(d, text, cx, y, font, fill):
    w = d.textlength(text, font=font)
    d.text((cx - w / 2, y), text, font=font, fill=fill)

def render_card(title, name, tag, price_text, range_text, stats, badge="", show_tag=True, watermark=""):
    rows = (min(len(stats), 9) + 2) // 3
    W, H = 1000, 415 + rows * 112 + 12 + (46 if watermark else 0)
    img = _gradient(W, H, (12, 8, 30), (62, 20, 105))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 14, H), fill=VIOLET)
    d.text((50, 36), title.upper(), font=_font(26), fill=VIOLET)
    if badge:
        f = _font(26)
        w = d.textlength(badge, font=f)
        d.rounded_rectangle((950 - w - 40, 28, 950, 76), radius=24, fill=GOLD)
        d.text((950 - w - 20, 36), badge, font=f, fill=(30, 25, 60))
    d.text((50, 80), name, font=_fit(d, name, 900, 58), fill=(255, 255, 255))
    if show_tag:
        d.text((50, 150), f"#{tag}", font=_font(28), fill=(170, 175, 205))
    d.rounded_rectangle((50, 205, 950, 325), radius=26, fill=GOLD)
    _center(d, price_text, 500, 227, _fit(d, price_text, 840, 74), (30, 25, 60))
    _center(d, range_text, 500, 341, _font(26), (200, 205, 230))
    cw, ch, gap = 285, 90, 22
    for i, (label, value) in enumerate(stats[:9]):
        x = 50 + (i % 3) * (cw + gap)
        y = 415 + (i // 3) * (ch + gap)
        d.rounded_rectangle((x, y, x + cw, y + ch), radius=18, fill=(40, 28, 84))
        d.text((x + 20, y + 10), label, font=_fit(d, label, cw - 40, 22), fill=(175, 165, 215))
        d.text((x + 20, y + 40), value, font=_fit(d, value, cw - 40, 38), fill=(255, 255, 255))
    if watermark:
        _center(d, watermark, W // 2, H - 44, _font(22), (170, 160, 215))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf
