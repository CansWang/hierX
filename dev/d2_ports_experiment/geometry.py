"""Acceptance checks on measured, unmodified D2 SVG geometry."""

import html
import math
import re

from .model import Case

TOLERANCE = 2.0  # SVG units, independent of browser/CSS zoom.
EPSILON = 1e-6  # Matrix arithmetic must not reject 2.00000000000003.


def overlap(a, b):
    return (
        min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"]) > 0.5
        and min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"]) > 0.5
    )


def pin_distance(point, pin):
    b = pin["box"]
    x = b["x"] + b["width"] / 2
    y = b["y"] + b["height"] / 2
    dx, dy = point["x"] - x, point["y"] - y
    if pin["primitive"] in {"ellipse", "circle"}:
        rx, ry = b["width"] / 2, b["height"] / 2
        if not rx or not ry:
            return float("inf")
        angle = math.atan2(dy, dx)
        radius = 1 / math.sqrt(
            (math.cos(angle) / rx) ** 2 + (math.sin(angle) / ry) ** 2
        )
        return abs(math.hypot(dx, dy) - radius)
    if pin["primitive"] == "rect":
        outside = math.hypot(
            max(abs(dx) - b["width"] / 2, 0), max(abs(dy) - b["height"] / 2, 0)
        )
        return outside or min(b["width"] / 2 - abs(dx), b["height"] / 2 - abs(dy))
    return float("inf")


def connection_endpoints(identity):
    # D2's SVG identity is compiler output, not user source. Restrict this
    # experiment to simple lowercase qualified identifiers and directed edges.
    if not isinstance(identity, str):
        raise ValueError("Compiled connection has no string identity")
    match = re.fullmatch(
        r"(?:(?P<prefix>[a-z][a-z0-9_.]*)\.)?\((?P<src>[a-z][a-z0-9_.]*) -> (?P<dst>[a-z][a-z0-9_.]*)\)\[\d+\]",
        html.unescape(identity),
    )
    if not match:
        raise ValueError(f"Unmeasurable compiled connection identity: {identity}")
    prefix = (match["prefix"] + ".") if match["prefix"] else ""
    return prefix + match["src"], prefix + match["dst"]


def analyze(case: Case, measured: dict, urls: dict[str, str]):
    """Return independent errors and metrics; an unknown measurement never passes."""
    errors = []
    metrics = {"pins": {}, "connections": []}

    def fail(code, subject, message):
        errors.append({"code": code, "subject": subject, "message": message})

    for error in measured["errors"]:
        fail("measurement-unavailable", error.get("id") or "", error["message"])
    objects = {}
    for obj in measured["objects"]:
        if obj["id"] in objects:
            fail(
                "duplicate-identity",
                obj["id"],
                "More than one SVG object has this identity",
            )
        objects[obj["id"]] = obj
    blocks = {b.id: b for b in case.blocks}
    ports = {p.id: p for p in case.ports}
    for block in case.blocks:
        if block.id not in objects or objects[block.id]["role"] != "block":
            fail("missing-block", block.id, "Block outline is absent")
    expected_ids = set(blocks) | set(ports)
    actual_ids = {
        k for k, v in objects.items() if v["role"] in {"block", "input", "output"}
    }
    for extra in actual_ids - expected_ids:
        fail("unexpected-object", extra, "Object is outside the fixture model")
    for port in case.ports:
        pin = objects.get(port.id)
        owner = objects.get(port.block)
        if not pin or pin["role"] != ("input" if port.direction == "in" else "output"):
            fail(
                "missing-pin",
                port.id,
                "Visible pin with the expected direction is absent",
            )
            continue
        if not owner or "box" not in owner:
            continue
        b = pin["box"]
        border = owner["box"]
        cx = b["x"] + b["width"] / 2
        cy = b["y"] + b["height"] / 2
        side = border["x"] if port.direction == "in" else border["x"] + border["width"]
        distance = abs(cx - side)
        metrics["pins"][port.id] = {
            "side": "left" if port.direction == "in" else "right",
            "border_distance": distance,
            "center": {"x": cx, "y": cy},
        }
        if pin["primitive"] not in {"circle", "ellipse", "rect"} or not (
            0 < b["width"] <= 16 and 0 < b["height"] <= 16
        ):
            fail(
                "pin-symbol",
                port.id,
                "Expected a dedicated small circle or square, not a label/link icon",
            )
        if distance > TOLERANCE + EPSILON or not (
            border["y"] + b["height"] / 2
            <= cy
            <= border["y"] + border["height"] - b["height"] / 2
        ):
            fail(
                "pin-not-on-boundary",
                port.id,
                f"Pin centre is {distance:.2f} SVG units from its assigned border",
            )
    for identity in expected_ids:
        obj = objects.get(identity)
        if obj and (not urls.get(identity) or urls[identity] not in obj["hrefs"]):
            fail(
                "missing-code-link",
                identity,
                "The exact resolved code target is not linked",
            )

    edges = {}
    for obj in objects.values():
        if obj["role"] not in {"wire", "exposure"}:
            continue
        try:
            key = (*connection_endpoints(obj["id"]), obj["role"])
        except ValueError as exc:
            fail("measurement-unavailable", obj["id"], str(exc))
            continue
        if key in edges:
            fail("duplicate-connection", obj["id"], "Unexpected repeated edge")
        edges[key] = obj
    expected_edges = {(c.source, c.target, c.kind) for c in case.connections}
    for key in edges.keys() - expected_edges:
        fail(
            "unexpected-connection",
            edges[key]["id"],
            "Connection does not match declared endpoints/kind",
        )

    def ancestors(name):
        found = set()
        while name in blocks:
            found.add(name)
            name = blocks[name].parent
        return found

    for connection in case.connections:
        key = (connection.source, connection.target, connection.kind)
        edge = edges.get(key)
        if not edge:
            fail(
                (
                    "missing-exposure"
                    if connection.kind == "exposure"
                    else "missing-connection"
                ),
                f"{connection.source} -> {connection.target}",
                "Expected connection is absent",
            )
            continue
        label = " ".join(x["text"] for x in edge["labels"])
        if label != connection.label:
            fail(
                "connection-label",
                edge["id"],
                f"Expected label {connection.label!r}, got {label!r}",
            )
        distances = {}
        for endpoint, identity in [
            ("start", connection.source),
            ("end", connection.target),
        ]:
            if identity in objects and "box" in objects[identity]:
                distance = pin_distance(edge[endpoint], objects[identity])
                distances[endpoint] = distance if math.isfinite(distance) else None
                if distance > TOLERANCE + EPSILON:
                    fail(
                        "wrong-endpoint",
                        edge["id"],
                        f"{endpoint} is {distance:.2f} SVG units from {identity}",
                    )
        metrics["connections"].append(
            {
                "source": connection.source,
                "target": connection.target,
                "kind": connection.kind,
                "endpoint_distances": distances,
            }
        )
        allowed = ancestors(ports[connection.source].block) | ancestors(
            ports[connection.target].block
        )
        for name in blocks.keys() - allowed:
            if name not in objects:
                continue
            b = objects[name]["box"]
            if any(
                b["x"] + TOLERANCE < p["x"] < b["x"] + b["width"] - TOLERANCE
                and b["y"] + TOLERANCE < p["y"] < b["y"] + b["height"] - TOLERANCE
                for p in edge["points"]
            ):
                fail(
                    "route-through-block",
                    edge["id"],
                    f"Route crosses unrelated block {name}",
                )

    labels = []
    view = measured["view_box"]
    for obj in objects.values():
        if not obj["labels"] or not any(x["text"] for x in obj["labels"]):
            fail("missing-label", obj["id"], "Expected a readable label")
        for label in obj["labels"]:
            b = label["box"]
            labels.append((obj["id"], b))
            if b["width"] <= 0 or b["height"] < 10:
                fail(
                    "unreadable-label",
                    obj["id"],
                    "Label has empty or very small measured text",
                )
            if (
                b["x"] < view["x"] - TOLERANCE
                or b["y"] < view["y"] - TOLERANCE
                or b["x"] + b["width"] > view["x"] + view["width"] + TOLERANCE
                or b["y"] + b["height"] > view["y"] + view["height"] + TOLERANCE
            ):
                fail("clipped-label", obj["id"], "Text lies outside the SVG view box")
            for port in ports:
                if port in objects and overlap(b, objects[port]["box"]):
                    fail("label-over-pin", obj["id"], f"Label overlaps {port}")
    for i, (identity, b) in enumerate(labels):
        for other, c in labels[i + 1 :]:
            if identity != other and overlap(b, c):
                fail("label-overlap", identity, f"Label overlaps {other}")
    return {
        "passed": not errors,
        "errors": errors,
        "metrics": metrics,
        "identities": sorted(objects),
    }
