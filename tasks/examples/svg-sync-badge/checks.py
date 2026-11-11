import math
import re
import xml.etree.ElementTree as ET


NAMESPACE = "{http://www.w3.org/2000/svg}"
SVG_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
ATTRIBUTES = {
    "title": {"id"},
    "rect": {"x", "y", "width", "height", "rx", "fill"},
    "circle": {"cx", "cy", "r", "fill"},
    "text": {"x", "y", "font-family", "font-size", "fill"},
}


def numbers(element, *attributes):
    raw = [element.get(attribute, "").strip() for attribute in attributes]
    if all(SVG_NUMBER.fullmatch(value) for value in raw):
        values = tuple(float(value) for value in raw)
        if all(math.isfinite(value) and abs(value) <= 10000 for value in values):
            return values
    return (math.nan,) * len(attributes)


def luminance(color):
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return None
    rgb = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in rgb]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(first, second, minimum):
    return (
        first is not None
        and second is not None
        and (max(first, second) + 0.05) / (min(first, second) + 0.05) >= minimum
    )


def evaluate(artifact, run):
    result = dict.fromkeys(
        (
            "svg_document", "restricted_primitives", "canvas", "accessible_name", "background_geometry",
            "indicator_geometry", "label_geometry", "foreground_visibility", "fill_colors", "text_contrast", "indicator_contrast",
        ),
        False,
    )
    try:
        raw = (artifact / "badge.svg").read_text(encoding="utf-8")
        if re.search(r"<!\s*(?:doctype|entity)|<\?(?!xml(?:\s|\?>))", raw, re.IGNORECASE):
            return result
        root = ET.fromstring(raw)
    except (ET.ParseError, OSError, UnicodeError):
        return result
    if root.tag != NAMESPACE + "svg":
        return result

    result["svg_document"] = True
    result["canvas"] = root.get("viewBox") == "0 0 160 40"
    children = {child.tag: child for child in root}
    expected = {NAMESPACE + name for name in ATTRIBUTES}
    if len(root) != len(expected) or children.keys() != expected:
        return result
    title, background, indicator, label = (children[NAMESPACE + name] for name in ATTRIBUTES)
    result["restricted_primitives"] = (
        root.attrib.keys() <= {"viewBox", "role", "aria-labelledby"}
        and not (root.text or "").strip()
        and all(not len(child) and not (child.tail or "").strip() for child in root)
        and all(not (child.text or "").strip() for child in (background, indicator))
        and all(children[NAMESPACE + name].attrib.keys() <= allowed for name, allowed in ATTRIBUTES.items())
    )
    title_id = title.get("id", "")
    result["accessible_name"] = (
        root.get("role") == "img"
        and bool(title_id)
        and not any(character.isspace() for character in title_id)
        and root.get("aria-labelledby") == title_id
        and (title.text or "").strip() == "Sync complete"
    )
    left, top, width, height, corner = numbers(background, "x", "y", "width", "height", "rx")
    center_x, center_y, radius = numbers(indicator, "cx", "cy", "r")
    label_x, label_y, size = numbers(label, "x", "y", "font-size")
    result["background_geometry"] = (left, top, width, height) == (0, 0, 160, 40) and 6 <= corner <= 10
    result["indicator_geometry"] = 18 <= center_x <= 22 and 19 <= center_y <= 21 and 6 <= radius <= 8
    result["label_geometry"] = (
        label.text == "SYNCED" and label.get("font-family") == "sans-serif"
        and 36 <= label_x <= 42 and 24 <= label_y <= 26 and 13 <= size <= 15
    )
    paint_order = list(root)
    result["foreground_visibility"] = (
        paint_order.index(background) < min(paint_order.index(indicator), paint_order.index(label))
        and 0 < radius <= min(center_x, center_y, 160 - center_x, 40 - center_y)
        and label_x - center_x - radius >= 6
        and 0 < label_y - size < label_y < 40
        and label_x + 6 * size <= 160
    )
    background_color, icon_color, label_color = (luminance(element.get("fill", "")) for element in (background, indicator, label))
    result["fill_colors"] = all(color is not None for color in (background_color, icon_color, label_color))
    result["text_contrast"] = contrast(background_color, label_color, 4.5)
    result["indicator_contrast"] = contrast(background_color, icon_color, 3.0)
    return result
