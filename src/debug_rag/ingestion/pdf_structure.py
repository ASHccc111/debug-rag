"""Recover narrowly supported PDF structures from native text and vector paths."""

import re


def table_cells(page, table):
    cells = table.extract()
    for values, row in zip(cells, table.rows, strict=False):
        for index, (value, box) in enumerate(zip(values, row.cells, strict=False)):
            if (
                not value
                or box is None
                or not any(line.strip() == "_" for line in value.splitlines())
            ):
                continue
            # Table extraction can detach underscore glyphs. Only use the native
            # cell text when the same glyphs support an identifier-shaped reading.
            native = page.get_textbox(box).strip()
            lines = native.splitlines()
            if not lines or not all(re.fullmatch(r"[A-Za-z0-9_.]+", line) for line in lines):
                continue
            joined = "".join(lines)
            compact = "".join(value.split())
            if (
                re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", joined)
                and joined.count("_") == compact.count("_")
                and joined.replace("_", "") == compact.replace("_", "")
            ):
                values[index] = native
    return cells


def _is_box(path):
    rect = path["rect"]
    if path["type"] not in {"s", "fs"} or rect.width < 20 or rect.height < 12:
        return False
    items = path["items"]
    if len(items) == 1:
        return items[0][0] == "re"
    # Rounded rectangles use four straight sides joined by four corner curves.
    if len(items) == 8 and [item[0] for item in items] == ["l", "c"] * 4:
        return all(a[-1] == b[1] for a, b in zip(items, items[1:] + items[:1], strict=True))
    return (
        len(items) == 4
        and all(item[0] == "l" for item in items)
        and all(a[-1] == b[1] for a, b in zip(items, items[1:] + items[:1], strict=True))
        and all(a.x == b.x or a.y == b.y for _, a, b in items)
    )


def _triangle(path):
    items = path["items"]
    if path["type"] not in {"f", "fs"} or not all(item[0] == "l" for item in items):
        return None
    if len(items) == 2 and path["closePath"] and items[0][2] == items[1][1]:
        return [items[0][1], items[1][1], items[1][2]]
    if len(items) == 3 and all(
        a[2] == b[1] for a, b in zip(items, items[1:] + items[:1], strict=True)
    ):
        return [item[1] for item in items]
    return None


def _arrow(stem, triangle):
    a, b = stem
    axis = 0 if abs(a.x - b.x) >= abs(a.y - b.y) else 1
    across = 1 - axis
    if abs(a[across] - b[across]) > 0.5 or abs(a[axis] - b[axis]) < 5:
        return None
    center = (a[across] + b[across]) / 2
    left, tip, right = sorted(triangle, key=lambda p: p[across])
    if (
        not left[across] < center < right[across]
        or abs(tip[across] - center) > 1
        or abs(left[axis] - right[axis]) > 0.5
        or not 2 <= abs(tip[axis] - left[axis]) <= 18
        or not 2 <= right[across] - left[across] <= 22
    ):
        return None
    direction = 1 if tip[axis] > left[axis] else -1
    tail, head = sorted(stem, key=lambda p: direction * p[axis])
    if (
        direction * (left[axis] - tail[axis]) <= 2
        or direction * (head[axis] - left[axis]) < -1
        or direction * (head[axis] - tip[axis]) > 1
    ):
        return None
    return axis, direction, tail, tip


def _near_side(box, point, axis, high_side):
    across = 1 - axis
    return (
        abs(box[axis + 2 * high_side] - point[axis]) <= 2
        and box[across] + 1 < point[across] < box[across + 2] - 1
    )


def diagram_edges(drawings, lines, table_areas, page_number):
    # Complex graphics remain review items. Keep the pairwise geometry pass bounded.
    if len(drawings) > 2000:
        return []
    nodes, stems, tips = [], [], []
    for path in drawings:
        rect = path["rect"]
        if any(area.intersects(rect) for area in table_areas):
            continue
        if _is_box(path):
            label = " ".join(text.strip() for box, text in lines if rect.contains(box))
            if label:
                nodes.append((rect, label))
        elif path["type"] == "s" and len(path["items"]) == 1 and path["items"][0][0] == "l":
            stems.append(path["items"][0][1:])
        elif (triangle := _triangle(path)) is not None:
            tips.append((rect, triangle))

    edges = []
    for tip_rect, triangle in tips:
        arrows = [arrow for stem in stems if (arrow := _arrow(stem, triangle)) is not None]
        if len(arrows) != 1:
            continue
        axis, direction, tail, tip = arrows[0]
        sources = [node for node in nodes if _near_side(node[0], tail, axis, direction == 1)]
        targets = [node for node in nodes if _near_side(node[0], tip, axis, direction == -1)]
        if len(sources) != 1 or len(targets) != 1 or sources == targets:
            continue
        source, target = sources[0], targets[0]
        bbox = (
            min(tail.x, tip_rect.x0),
            min(tail.y, tip_rect.y0),
            max(tail.x, tip_rect.x1),
            max(tail.y, tip_rect.y1),
        )
        locator = {
            "format": "pdf",
            "page": page_number,
            "bbox": [round(value, 2) for value in bbox],
            "from_bbox": [round(value, 2) for value in source[0]],
            "to_bbox": [round(value, 2) for value in target[0]],
        }
        edges.append((bbox[1], bbox[0], "diagram_edge", f"{source[1]} → {target[1]}", locator, {}))
    return edges
