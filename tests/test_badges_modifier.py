import importlib.util
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "badges_modifier",
    ROOT / "badgesModifier" / "modifier.py",
)
modifier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(modifier)


def _atlas(badges):
    parts = ["<root>"]
    for name, x, y, width, height in badges:
        parts.append(
            "<SubTexture>"
            f"<name>{name}</name><x>{x}</x><y>{y}</y>"
            f"<width>{width}</width><height>{height}</height>"
            "</SubTexture>"
        )
    parts.append("</root>")
    return "".join(parts)


def _all_badges():
    return [
        (name, index * 50, 0, 40, 40)
        for index, name in enumerate(modifier.COLORS)
    ]


def test_parse_coordinates_reads_elements_and_attributes(tmp_path):
    element_xml = tmp_path / "elements.xml"
    element_xml.write_text(_atlas([("badge_11", 1, 2, 30, 40)]), encoding="utf-8")
    parsed = modifier.parse_coordinates(element_xml)
    assert parsed == [{"name": "badge_11", "x": 1, "y": 2, "width": 30, "height": 40}]

    attr_xml = tmp_path / "attrs.xml"
    attr_xml.write_text(
        '<root><SubTexture name="badge_12" x="4" y="5" width="6" height="7"/></root>',
        encoding="utf-8",
    )
    assert modifier.parse_coordinates(attr_xml) == [
        {"name": "badge_12", "x": 4, "y": 5, "width": 6, "height": 7},
    ]

    wrapped_xml = tmp_path / "wrapped.xml"
    wrapped_xml.write_text(
        '<Images><Item name="badge_13" x="8" y="9" width="10" height="11"/></Images>',
        encoding="utf-8",
    )
    assert modifier.parse_coordinates(wrapped_xml) == [
        {"name": "badge_13", "x": 8, "y": 9, "width": 10, "height": 11},
    ]


def test_icon_modifier_replaces_badges(tmp_path, monkeypatch):
    monkeypatch.setattr(modifier, "OUTPUT_PATH", str(tmp_path / "output"))
    src = tmp_path / "atlas.png"
    xml = tmp_path / "atlas.xml"
    Image.new("RGBA", (400, 80), (1, 2, 3, 255)).save(src)
    xml.write_text(_atlas(_all_badges()), encoding="utf-8")

    modifier.main(str(src), str(xml), "battle")

    result_path = tmp_path / "output" / "battle.dds"
    assert result_path.is_file()
    assert (tmp_path / "output" / "battle.xml").read_text(encoding="utf-8") == xml.read_text(encoding="utf-8")
    assert not (tmp_path / "output" / "battle.png").exists()

    result = Image.open(result_path).convert("RGBA")
    assert result.getpixel((0, 0)) == (0, 0, 0, 0)
    assert result.getpixel((45, 0)) == (1, 2, 3, 255)
    # badge_11 在 x=50，圆形直径为 24，中心落在 (70, 20)。
    assert result.getpixel((70, 20)) == (241, 0, 0, 255)
    assert result.getpixel((50, 0)) == (0, 0, 0, 0)
    # bot.png 中心是透明的，图标落在 badge_10 区域内即可。
    badge_pixels = [result.getpixel((x, y)) for x in range(40) for y in range(40)]
    assert any(pixel[3] > 0 for pixel in badge_pixels)


def test_icon_modifier_rejects_incomplete_atlas(tmp_path, monkeypatch):
    monkeypatch.setattr(modifier, "OUTPUT_PATH", str(tmp_path / "output"))
    src = tmp_path / "atlas.png"
    xml = tmp_path / "atlas.xml"
    Image.new("RGBA", (40, 40), (0, 0, 0, 255)).save(src)
    xml.write_text(_atlas([("badge_11", 0, 0, 40, 40)]), encoding="utf-8")

    with pytest.raises(RuntimeError, match=r"坐标数量\(1\)"):
        modifier.main(str(src), str(xml), "partial")


def test_unknown_file_type(tmp_path):
    src = tmp_path / "atlas.bin"
    src.write_bytes(b"not-an-image")
    with pytest.raises(RuntimeError, match="无法识别"):
        modifier.main(str(src), str(tmp_path / "missing.xml"), "out")


def test_dds_is_converted_before_edit(tmp_path, monkeypatch):
    monkeypatch.setattr(modifier, "OUTPUT_PATH", str(tmp_path / "output"))
    dds = tmp_path / "atlas.dds"
    dds.write_bytes(b"DDS " + b"\x00" * 16)
    xml = tmp_path / "atlas.xml"
    xml.write_text(_atlas(_all_badges()), encoding="utf-8")

    def fake_dds_to_png(src_img, dest_png):
        assert src_img == str(dds)
        Image.new("RGBA", (400, 80), (9, 9, 9, 255)).save(dest_png)

    monkeypatch.setattr(modifier, "dds_to_png", fake_dds_to_png)
    modifier.main(str(dds), str(xml), "fromdds")
    assert (tmp_path / "output" / "fromdds.dds").is_file()
    assert (tmp_path / "atlas.png").is_file()


def test_dds_to_png_uses_host_binary(monkeypatch):
    seen = {}

    def fake_run(cmd, **_kwargs):
        seen["cmd"] = cmd

        class Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        return Proc()

    monkeypatch.setenv("DDS2PNG", r"C:\tools\dds2png.exe")
    monkeypatch.setattr(modifier.subprocess, "run", fake_run)
    modifier.dds_to_png("a.dds", "a.png")
    assert seen["cmd"] == [r"C:\tools\dds2png.exe", "-i", "a.dds", "-o", "a.png"]
