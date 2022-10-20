# -*- coding: utf-8 -*-

import os
import sys
from PIL import Image, ImageDraw
import xmltodict
from shutil import copyfile

colors = {
    "badge_10": (241, 0, 0, 255),  # "red"
    "badge_11": (0, 193, 0, 255),  # "green"
    "badge_12": (102, 170, 255, 255),  # "blue"
    "badge_13": (204, 68, 255, 255),  # "purple"
    "badge_14": (255, 215, 0, 255),  # "golden"
}

OUTPUT_PATH = './output'

# SRC_XML = "./input/battleAtlas.xml"
# SRC_IMAGE = "./input"
# TARGET_XML = "./output/battleAtlas.xml"
# TARGET_IMAGE = "./output/battleAtlas.png"

def main():
    src_img = sys.argv[1]
    src_xml = sys.argv[2]
    output_name = sys.argv[3]
    tg_img = os.path.join(OUTPUT_PATH, f'{output_name}.png')
    tg_xml = os.path.join(OUTPUT_PATH, f'{output_name}.xml')
    rn_img = os.path.join(OUTPUT_PATH, f'{output_name}.dds')

    atlas = xmltodict.parse(open(src_xml, "r", encoding="utf-8").read())
    coordinates = dict()
    for subTexture in atlas["root"]["SubTexture"]:
        if subTexture["name"] in colors.keys():
            coordinates[subTexture["name"]] = (
                int(subTexture["x"]),
                int(subTexture["y"]),
                int(subTexture["width"]),
                int(subTexture["height"]),
            )

    assert len(coordinates) == len(colors)

    image = Image.open(src_img)
    draw = ImageDraw.Draw(image)
    for badgeName, metrics in coordinates.items():
        rectangle = [metrics[0], metrics[1], metrics[0] + metrics[2], metrics[1] + metrics[3]]
        draw.rectangle(rectangle, fill=(0, 0, 0, 0))  # clear rect

        dx = metrics[2] / 4
        dy = metrics[3] / 4

        rectangle[0] += dx
        rectangle[2] -= dx
        rectangle[1] += dy
        rectangle[3] -= dy
        fillColor = colors[badgeName]
        halvedAlphaColor = fillColor[:3] + (128,)
        draw.ellipse(rectangle, fill=fillColor, outline=halvedAlphaColor)

    image.save(tg_img)
    copyfile(src_xml, tg_xml)
    os.rename(tg_img, rn_img)


if __name__ == "__main__":
    main()