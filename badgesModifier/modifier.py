# -*- coding: utf-8 -*-

import os
import sys
from PIL import Image, ImageDraw
import xmltodict
from shutil import copyfile

colors = {
    "badge_10": 'bot.png',
    "badge_11": (241, 0, 0, 255),  # "red"
    "badge_12": (0, 193, 0, 255),  # "green"
    "badge_13": (102, 170, 255, 255),  # "blue"
    "badge_14": (204, 68, 255, 255),  # "purple"
    "badge_15": (255, 215, 0, 255),  # "golden"
    "badge_16": 'crown.png',
}

OUTPUT_PATH = './output'

def _get_base_path():
    """
    返回资源基础路径：
    - 被 PyInstaller 打包后，从临时目录 sys._MEIPASS 读取内置资源
    - 源码运行时，从当前文件所在目录读取
    """
    return getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))

ICON_BASE_PATH = os.path.join(_get_base_path(), 'assets')  # 图标文件基础路径

# SRC_XML = "./input/battleAtlas.xml"
# SRC_IMAGE = "./input"
# TARGET_XML = "./output/battleAtlas.xml"
# TARGET_IMAGE = "./output/battleAtlas.png"

def main():
    """
    主函数：处理雪碧图修改
    支持将指定badge替换为本地图标，其他badge保持原有圆形样式
    
    配置说明：
    - colors字典中的值可以是：
      * 颜色元组 (R, G, B, A): 绘制对应颜色的圆形
      * 图标文件名 (如 'bot.png'): 使用./input/目录下的图标文件
    
    Args:
        src_img: 源图片路径
        src_xml: 源XML配置文件路径  
        output_name: 输出文件名（不含扩展名）
    """
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

        badge_config = colors[badgeName]
        
        # 检查是否为图标文件路径（字符串且以.png结尾）
        if isinstance(badge_config, str) and badge_config.endswith('.png'):
            icon_path = os.path.join(ICON_BASE_PATH, badge_config)
            
            # 如果图标文件存在，使用图标
            if os.path.exists(icon_path):
                try:
                    icon_image = Image.open(icon_path)
                    
                    # 计算图标在目标区域中的位置和大小
                    icon_width = int(metrics[2] * 0.8)  # 图标宽度为区域宽度的80%
                    icon_height = int(metrics[3] * 0.8)  # 图标高度为区域高度的80%
                    
                    # 调整图标大小
                    resized_icon = icon_image.resize((icon_width, icon_height), Image.Resampling.LANCZOS)
                    
                    # 计算居中位置
                    x_offset = metrics[0] + (metrics[2] - icon_width) // 2
                    y_offset = metrics[1] + (metrics[3] - icon_height) // 2
                    
                    # 将图标粘贴到目标位置
                    if resized_icon.mode == 'RGBA':
                        image.paste(resized_icon, (x_offset, y_offset), resized_icon)
                    else:
                        image.paste(resized_icon, (x_offset, y_offset))
                    
                    print(f"已应用图标: {badge_config} -> {badgeName}")
                except Exception as e:
                    print(f"加载图标失败 {badge_config}: {e}")
                    # 如果图标加载失败，跳过该badge
                    continue
            else:
                print(f"图标文件不存在: {icon_path}")
                # 如果图标文件不存在，跳过该badge
                continue
        else:
            # 原有的圆形绘制逻辑（颜色元组）
            dx = metrics[2] / 4
            dy = metrics[3] / 4

            rectangle[0] += dx
            rectangle[2] -= dx
            rectangle[1] += dy
            rectangle[3] -= dy
            
            if isinstance(badge_config, tuple) and len(badge_config) >= 3:
                fillColor = badge_config
                halvedAlphaColor = fillColor[:3] + (128,)
                draw.ellipse(rectangle, fill=fillColor, outline=halvedAlphaColor)
                print(f"已绘制圆形: {badgeName} -> {fillColor}")

    image.save(tg_img)
    copyfile(src_xml, tg_xml)
    os.rename(tg_img, rn_img)


if __name__ == "__main__":
    main()