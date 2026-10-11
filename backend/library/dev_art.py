"""Original, reproducible CC0 development illustrations; no network assets or fonts."""

import math
from io import BytesIO

from PIL import Image, ImageDraw

DEV_ART = [
    ("lighthouse", ["light house", "beacon"], "places"),
    ("bicycle", ["bike", "cycle"], "objects"),
    ("cherries", ["cherry"], "food-drink"),
    ("hot air balloon", ["balloon", "hot-air balloon"], "objects"),
]
ATTRIBUTION = "Original Pixelguessr development artwork, created for this project (CC0 1.0)."


def illustration(subject):
    palette = {
        "lighthouse": ((161, 196, 212), (227, 221, 194)),
        "bicycle": ((247, 232, 208), (229, 198, 168)),
        "cherries": ((224, 173, 147), (242, 210, 179)),
        "hot air balloon": ((178, 212, 194), (231, 231, 201)),
    }
    top, bottom = palette[subject]
    image = Image.new("RGB", (960, 720))
    draw = ImageDraw.Draw(image)
    for y in range(720):
        color = tuple(round(a + (b - a) * y / 719) for a, b in zip(top, bottom, strict=True))
        draw.line((0, y, 960, y), fill=color)
    if subject == "lighthouse":
        draw.ellipse((695, 80, 805, 190), fill="#f9df9d")
        draw.rectangle((0, 490, 960, 720), fill="#498b98")
        for y in (520, 575, 640):
            draw.line((0, y, 960, y), fill="#80b1b7", width=5)
        draw.polygon([(85, 660), (310, 525), (510, 540), (675, 665)], fill="#6a7667")
        draw.polygon([(350, 565), (390, 210), (510, 210), (550, 565)], fill="#fff0d3")
        draw.polygon([(380, 300), (520, 300), (530, 395), (370, 395)], fill="#d27060")
        draw.rounded_rectangle((421, 455, 480, 565), radius=29, fill="#354859")
        draw.rectangle((378, 172, 523, 230), fill="#394e5e")
        draw.rectangle((405, 178, 495, 213), fill="#ffe6a4")
        draw.polygon([(360, 174), (450, 105), (541, 174)], fill="#c56657")
        draw.line((450, 89, 450, 110), fill="#394e5e", width=6)
        draw.line((350, 237, 550, 237), fill="#394e5e", width=8)
        for x in range(360, 551, 26):
            draw.line((x, 218, x, 245), fill="#394e5e", width=4)
    elif subject == "bicycle":
        draw.ellipse((120, 582, 860, 648), fill="#d5b39b")
        for x in (245, 715):
            draw.ellipse((x - 123, 350, x + 123, 596), fill="#273b42")
            draw.ellipse((x - 110, 363, x + 110, 583), fill="#efddbf")
            for angle in range(0, 360, 20):
                a = math.radians(angle)
                draw.line(
                    (x, 473, x + 108 * math.cos(a), 473 + 108 * math.sin(a)),
                    fill="#87948b",
                    width=3,
                )
            draw.ellipse((x - 8, 465, x + 8, 481), fill="#273b42")
        frame = [(245, 473), (367, 297), (465, 473), (245, 473), (585, 297), (465, 473)]
        draw.line(frame, fill="#459b8a", width=17, joint="curve")
        draw.line((367, 297, 585, 297, 715, 473), fill="#459b8a", width=17, joint="curve")
        draw.line((367, 297, 350, 250), fill="#344953", width=12)
        draw.rounded_rectangle((300, 231, 392, 252), radius=10, fill="#344953")
        draw.line((585, 297, 565, 230, 613, 212, 654, 230), fill="#344953", width=12, joint="curve")
        draw.ellipse((441, 449, 489, 497), fill="#344953")
        draw.line((465, 473, 502, 509), fill="#ced4be", width=9)
        draw.line((487, 512, 525, 512), fill="#344953", width=12)
    elif subject == "cherries":
        draw.ellipse((223, 550, 758, 634), fill="#ce9986")
        draw.arc((278, 85, 685, 700), 225, 310, fill="#596f4d", width=18)
        draw.line((499, 150, 616, 420), fill="#596f4d", width=16)
        draw.polygon([(503, 165), (610, 99), (710, 118), (630, 179), (550, 190)], fill="#789364")
        draw.line((515, 164, 675, 126), fill="#b7c393", width=4)
        draw.ellipse((242, 346, 476, 582), fill="#bb4554")
        draw.ellipse((482, 370, 718, 606), fill="#b83c4f")
        draw.ellipse((277, 375, 334, 421), fill="#f2a09a")
        draw.ellipse((520, 399, 574, 443), fill="#ed8e8e")
        draw.arc((262, 363, 457, 563), 40, 120, fill="#9a3449", width=11)
        draw.arc((502, 389, 699, 587), 35, 120, fill="#963049", width=11)
    else:
        for x, y in ((180, 130), (700, 235), (120, 405)):
            draw.ellipse((x, y, x + 100, y + 35), fill="#f4efdd")
            draw.ellipse((x + 28, y - 22, x + 78, y + 25), fill="#f4efdd")
        draw.polygon(
            [
                (0, 665),
                (175, 592),
                (340, 649),
                (570, 592),
                (780, 660),
                (960, 603),
                (960, 720),
                (0, 720),
            ],
            fill="#90b49a",
        )
        draw.ellipse((301, 80, 661, 430), fill="#cb7661")
        draw.ellipse((365, 80, 595, 430), fill="#f0be78")
        draw.ellipse((426, 80, 534, 430), fill="#cf7864")
        draw.polygon([(330, 340), (630, 340), (535, 487), (426, 487)], fill="#c8725f")
        draw.polygon([(390, 350), (572, 350), (516, 487), (448, 487)], fill="#efbd78")
        draw.line((432, 475, 450, 555), fill="#4d6155", width=5)
        draw.line((527, 475, 512, 555), fill="#4d6155", width=5)
        draw.rounded_rectangle((433, 545, 532, 614), radius=9, fill="#9d7251")
        draw.line((434, 566, 531, 566), fill="#c19566", width=7)
        for x in range(448, 530, 18):
            draw.line((x, 574, x, 610), fill="#ba8c5e", width=4)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
