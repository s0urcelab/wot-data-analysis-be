# -*- coding: utf-8 -*-
"""把 battleAtlas 里指定徽章替换成图标或色块。

用法:
    python modifier.py <图片> <xml> <输出名>

图片可以是 PNG，或由宿主提供的 dds2png 转换的 DDS。可用环境变量 DDS2PNG
指定该程序路径，未设置时从 PATH 查找 dds2png。结果写到本目录 output/ 下，
PNG 数据会按原实现改名为 .dds，并复制一份 XML。
"""

import os
import shutil
import subprocess
import sys

import xmltodict
from PIL import Image, ImageDraw

COLORS = {
    "badge_10": "bot.png",
    "badge_11": (241, 0, 0, 255),  # red
    "badge_12": (0, 193, 0, 255),  # green
    "badge_13": (102, 170, 255, 255),  # blue
    "badge_14": (204, 68, 255, 255),  # purple
    "badge_15": (255, 215, 0, 255),  # golden
    "badge_16": "crown.png",
    "badge_17": "question.png",
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_PATH = os.path.join(BASE_DIR, "output")
ICON_BASE_PATH = os.path.join(BASE_DIR, "assets")

PNG_SIG = b"\x89PNG\r\n\x1a\n"
DDS_SIG = b"DDS "


def _text(value):
    if value is None:
        return ""
    if isinstance(value, list):
        return _text(value[0]) if value else ""
    if isinstance(value, dict):
        if "#text" in value:
            return str(value["#text"]).strip()
        return ""
    return str(value).strip()


def _field(node, key):
    if key in node:
        return node[key]
    attr = f"@{key}"
    if attr in node:
        return node[attr]
    return None


def _coord_from_node(node):
    if not isinstance(node, dict):
        return None
    raw = {key: _field(node, key) for key in ("name", "x", "y", "width", "height")}
    if any(value is None for value in raw.values()):
        return None
    try:
        return {
            "name": _text(raw["name"]),
            "x": int(float(_text(raw["x"]))),
            "y": int(float(_text(raw["y"]))),
            "width": int(float(_text(raw["width"]))),
            "height": int(float(_text(raw["height"]))),
        }
    except ValueError:
        return None


def _collect(node, acc):
    if isinstance(node, list):
        for item in node:
            _collect(item, acc)
        return
    if not isinstance(node, dict):
        return
    coord = _coord_from_node(node)
    if coord is not None:
        acc.append(coord)
    for value in node.values():
        _collect(value, acc)


def parse_coordinates(xml_path):
    with open(xml_path, "r", encoding="utf-8-sig") as handle:
        parsed = xmltodict.parse(handle.read())

    sub = None
    root = parsed.get("root") if isinstance(parsed, dict) else None
    if isinstance(root, dict):
        sub = root.get("SubTexture")

    if isinstance(sub, list):
        nodes = sub
    elif sub:
        nodes = [sub]
    else:
        nodes = []
        _collect(parsed, nodes)

    coords = []
    for node in nodes:
        coord = _coord_from_node(node)
        if coord and coord["name"] in COLORS:
            coords.append(coord)
    return coords


def clear_rect(image, rect):
    blank = Image.new("RGBA", (rect["width"], rect["height"]), (0, 0, 0, 0))
    image.paste(blank, (rect["x"], rect["y"]))


def draw_circle(image, rect, rgba):
    size = int(min(rect["width"], rect["height"]) * 0.6)
    if size <= 0:
        return
    left = rect["x"] + (rect["width"] - size) // 2
    top = rect["y"] + (rect["height"] - size) // 2
    draw = ImageDraw.Draw(image)
    draw.ellipse((left, top, left + size - 1, top + size - 1), fill=tuple(rgba))


def _contain(icon, target_w, target_h):
    scale = min(target_w / icon.width, target_h / icon.height)
    new_w = max(1, int(icon.width * scale))
    new_h = max(1, int(icon.height * scale))
    resized = icon.resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    canvas.paste(
        resized,
        ((target_w - new_w) // 2, (target_h - new_h) // 2),
        resized,
    )
    return canvas


def paste_icon(image, rect, icon_file):
    icon_path = os.path.join(ICON_BASE_PATH, icon_file)
    if not os.path.isfile(icon_path):
        print(f"图标文件不存在: {icon_path}")
        return False
    try:
        icon = Image.open(icon_path).convert("RGBA")
    except OSError as exc:
        raise RuntimeError(f"加载图标失败 {icon_file}: {exc}") from exc

    target_w = int(rect["width"] * 0.8)
    target_h = int(rect["height"] * 0.8)
    if target_w <= 0 or target_h <= 0:
        return False
    canvas = _contain(icon, target_w, target_h)
    left = rect["x"] + (rect["width"] - target_w) // 2
    top = rect["y"] + (rect["height"] - target_h) // 2
    image.paste(canvas, (left, top), canvas)
    return True


def icon_modifier(src_img, src_xml, output_name):
    os.makedirs(OUTPUT_PATH, exist_ok=True)
    tg_img = os.path.join(OUTPUT_PATH, f"{output_name}.png")
    tg_xml = os.path.join(OUTPUT_PATH, f"{output_name}.xml")
    rn_img = os.path.join(OUTPUT_PATH, f"{output_name}.dds")

    coords = parse_coordinates(src_xml)
    if len(coords) != len(COLORS):
        raise RuntimeError(f"坐标数量({len(coords)})与 colors 键数({len(COLORS)})不一致")

    image = Image.open(src_img).convert("RGBA")
    for coord in coords:
        clear_rect(image, coord)
        conf = COLORS[coord["name"]]
        if isinstance(conf, str) and conf.endswith(".png"):
            if paste_icon(image, coord, conf):
                print(f"已应用图标: {conf} -> {coord['name']}")
        elif isinstance(conf, (list, tuple)) and len(conf) >= 3:
            rgba = tuple(conf) if len(conf) >= 4 else tuple(conf[:3]) + (255,)
            draw_circle(image, coord, rgba)
            print(f"已绘制圆形: {coord['name']} -> rgba({','.join(str(channel) for channel in rgba)})")

    image.save(tg_img, format="PNG", compress_level=3)
    shutil.copyfile(src_xml, tg_xml)
    # 与原实现一致：文件内容仍是 PNG，只把扩展名改成 .dds。
    os.replace(tg_img, rn_img)


def detect_file_type(path):
    with open(path, "rb") as handle:
        header = handle.read(8)
    if header[:8] == PNG_SIG:
        return "png"
    if header[:4] == DDS_SIG:
        return "dds"
    return "unknown"


def dds_to_png(src_img, dest_png):
    binary = os.environ.get("DDS2PNG", "dds2png")
    proc = subprocess.run(
        [binary, "-i", src_img, "-o", dest_png],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"dds2png exited with code {proc.returncode}: {detail}")
    print(f"dds转换png成功：{dest_png}")


def main(src_img, src_xml, output_name):
    img_type = detect_file_type(src_img)
    if img_type == "unknown":
        raise RuntimeError("无法识别dds文件")
    if img_type == "png":
        icon_modifier(src_img, src_xml, output_name)
        return
    png_path = src_img[:-4] + ".png" if src_img.lower().endswith(".dds") else src_img + ".png"
    dds_to_png(src_img, png_path)
    icon_modifier(png_path, src_xml, output_name)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("用法: python modifier.py <图片> <xml> <输出名>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
