#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ポッドキャストのカバー画像を作る。てらこ先生キャラ＋番組名。

Spotify の要件（1400〜3000px の正方形・RGB）に合わせて 3000x3000 で書き出す。
色はサイトのヒーロー（濃紺）とアクセント（ティール #0e7490）に合わせる。
キャラはメガネなし（characters.json のルール：講義以外の用途は plain）。
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

CHAR = Path.home() / "ai-office/advisors/lecture/character/bust/center-plain-point-wide.png"
FONTS = Path.home() / "Library/Fonts"
OUT = Path(__file__).parent / "cover-new.jpg"
SIZE = 3000

INK_TOP, INK_BOTTOM = (15, 23, 42), (30, 41, 59)      # サイトのヒーローと同じ濃紺
TEAL = (34, 211, 238)                                  # サイトの btn-primary と同じ明るいシアン


def strip_white_background(img: Image.Image, tol: int = 3) -> Image.Image:
    """外周から白をたどって背景だけ透明にする。

    白衣とTシャツの白（250前後）と背景の白（253〜255）は差が小さいので、
    許容差は 3 まで。緩くすると服が背景と一緒に抜ける（2026-09-07 に実際に起きた）。"""
    img = img.convert("RGBA")
    w, h = img.size
    px = img.load()
    seen = [[False] * w for _ in range(h)]
    stack = [(x, y) for x in range(w) for y in (0, h - 1)] + \
            [(x, y) for y in range(h) for x in (0, w - 1)]
    while stack:
        x, y = stack.pop()
        if not (0 <= x < w and 0 <= y < h) or seen[y][x]:
            continue
        r, g, b, a = px[x, y]
        if r < 255 - tol or g < 255 - tol or b < 255 - tol:
            continue
        seen[y][x] = True
        px[x, y] = (r, g, b, 0)
        stack += [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    return img


def shave_edge(img: Image.Image) -> Image.Image:
    """輪郭に残る白い縁を消す。切り抜きの境目は白と背景が混ざった半透明の画素で、
    濃い背景に置くと白フチとして見えるため、アルファを1画素分だけ内側に縮める。"""
    r, g, b, a = img.split()
    return Image.merge("RGBA", (r, g, b, a.filter(ImageFilter.MinFilter(3))))


def trim(img: Image.Image) -> Image.Image:
    box = img.getbbox()
    return img.crop(box) if box else img


def gradient(size: int) -> Image.Image:
    bg = Image.new("RGB", (1, size))
    d = ImageDraw.Draw(bg)
    for y in range(size):
        t = y / size
        d.point((0, y), fill=tuple(round(a + (b - a) * t) for a, b in zip(INK_TOP, INK_BOTTOM)))
    return bg.resize((size, size))


def main():
    canvas = gradient(SIZE).convert("RGBA")

    # キャラの後ろに置く光の輪（沈んだ背景から人物を浮かせる）
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([540, 1180, 2460, 3100], fill=TEAL + (46,))
    canvas = Image.alpha_composite(canvas, glow.filter(ImageFilter.GaussianBlur(120)))

    # キャラ（背景の白を抜いて余白を詰める）。頭頂を文字の下に置き、肩から下は下端で切る
    ch = trim(shave_edge(strip_white_background(Image.open(CHAR))))
    target_w = 1480
    ch = ch.resize((target_w, round(ch.height * target_w / ch.width)), Image.LANCZOS)
    top = 1380
    canvas.alpha_composite(ch, (round((SIZE - target_w) / 2) + 30, top))
    print("  キャラ:", ch.size, "頭頂 y =", top, "下端 y =", top + ch.height)

    d = ImageDraw.Draw(canvas)
    f_sub = ImageFont.truetype(str(FONTS / "ZenKakuGothicNew-Medium.ttf"), 250)
    f_main = ImageFont.truetype(str(FONTS / "ZenKakuGothicNew-Bold.ttf"), 470)

    def centered(text, font, y, fill):
        w = d.textbbox((0, 0), text, font=font)[2]
        d.text(((SIZE - w) / 2, y), text, font=font, fill=fill)

    centered("世界一わかりやすい", f_sub, 380, (203, 213, 225))
    centered("AIニュース", f_main, 680, (255, 255, 255))
    # 番組名とキャラの境目に短い線を1本。小さく表示されたとき、文字の塊とキャラを切り分ける
    d.rounded_rectangle([1350, 1268, 1650, 1288], radius=10, fill=TEAL)

    canvas.convert("RGB").save(OUT, "JPEG", quality=92, optimize=True)
    print("できました:", OUT, Image.open(OUT).size)


if __name__ == "__main__":
    main()
