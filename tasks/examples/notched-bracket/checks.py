import re
from collections import Counter
from fractions import Fraction


OUTLINE = ((0, 0), (3, 0), (3, 1), (1, 1), (1, 2), (0, 2))
CORNERS = {(x, y, z) for x, y in OUTLINE for z in (0, 1)}
COORDINATE = re.compile(r"[-+]?(?:[0-9]{1,12}(?:\.[0-9]{0,12})?|\.[0-9]{1,12})")


def vector(first, second):
    return tuple(end - start for start, end in zip(first, second))


def cross(first, second):
    a, b, c = first
    x, y, z = second
    return b * z - c * y, c * x - a * z, a * y - b * x


def dot(first, second):
    return sum(a * b for a, b in zip(first, second))


def cyclic_pairs(values):
    return zip(values, values[1:] + values[:1])


def read_mesh(path):
    vertices, faces = [], []
    named = False
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.partition("#")[0].split()
        if not parts:
            continue
        kind, *values = parts
        if kind == "o" and values and not named and not vertices and not faces:
            named = True
        elif kind == "v" and len(values) == 3 and all(COORDINATE.fullmatch(value) for value in values):
            vertices.append(tuple(Fraction(value) for value in values))
        elif kind == "f" and len(values) >= 3 and all(re.fullmatch(r"[1-9][0-9]{0,5}", value) for value in values):
            faces.append(tuple(int(value) - 1 for value in values))
        else:
            raise ValueError("Unsupported OBJ record")
        if len(vertices) > 64 or len(faces) > 64:
            raise ValueError("Too many mesh records")
    if not vertices or not faces:
        raise ValueError("No usable mesh")
    return vertices, faces


def clip_notch(polygon, axis):
    clipped = []
    for start, end in cyclic_pairs(polygon):
        start_in = start[axis] >= 1
        end_in = end[axis] >= 1
        if start_in:
            clipped.append(start)
        if start_in != end_in:
            offset = (1 - start[axis]) / (end[axis] - start[axis])
            clipped.append(tuple(a + offset * (b - a) for a, b in zip(start, end)))
    return clipped


def notch_is_clear(triangles):
    for triangle in triangles:
        projected = [vertex[:2] for vertex in triangle]
        clipped = clip_notch(clip_notch(projected, 0), 1)
        if sum(x * v - y * u for (x, y), (u, v) in cyclic_pairs(clipped)) != 0:
            return False
    return True


def surfaces():
    planes = [({(x, y, z) for x, y in OUTLINE}, (0, 0, normal), 8) for z, normal in ((0, -1), (1, 1))]
    for (x, y), (u, v) in cyclic_pairs(OUTLINE):
        dx, dy = u - x, v - y
        length = abs(dx) + abs(dy)
        corners = {(a, b, z) for a, b in ((x, y), (u, v)) for z in (0, 1)}
        planes.append((corners, (dy // length, -dx // length, 0), 2 * length))
    return planes


def evaluate(artifact, run):
    result = dict.fromkeys(
        (
            "obj_document", "triangulated_faces", "vertex_set", "scale", "notch", "boundary_surfaces",
            "surface_coverage", "closed_edges", "outward_winding", "volume",
        ),
        False,
    )
    try:
        vertices, faces = read_mesh(artifact / "bracket.obj")
    except (OSError, ValueError):
        return result

    result["obj_document"] = True
    result["vertex_set"] = len(vertices) == len(CORNERS) and set(vertices) == CORNERS
    result["scale"] = all((min(axis), max(axis)) == expected for axis, expected in zip(zip(*vertices), ((0, 3), (0, 2), (0, 1))))
    if any(len(face) != 3 or len(set(face)) != 3 or max(face) >= len(vertices) for face in faces):
        return result

    triangles = [tuple(vertices[index] for index in face) for face in faces]
    normals = [cross(vector(a, b), vector(a, c)) for a, b, c in triangles]
    result["triangulated_faces"] = (
        all(any(normal) for normal in normals) and len({tuple(sorted(face)) for face in faces}) == len(faces)
    )
    result["notch"] = notch_is_clear(triangles)
    result["closed_edges"] = all(count == 2 for count in Counter(tuple(sorted(edge)) for face in faces for edge in cyclic_pairs(face)).values())
    result["volume"] = sum(dot(a, cross(b, c)) for a, b, c in triangles) == 24

    planes = surfaces()
    projected_areas = Counter()
    orientation = True
    for triangle, normal in zip(triangles, normals):
        matching = [index for index, (corners, _, _) in enumerate(planes) if set(triangle) <= corners]
        if len(matching) != 1:
            return result
        index = matching[0]
        signed_area = dot(normal, planes[index][1])
        orientation = orientation and signed_area > 0
        projected_areas[index] += abs(signed_area)
    result["boundary_surfaces"] = True
    result["surface_coverage"] = all(projected_areas[index] == expected for index, (_, _, expected) in enumerate(planes))
    result["outward_winding"] = orientation
    return result
