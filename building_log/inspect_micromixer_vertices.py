"""Inspect COMSOL geometry vertex coordinates for micromixer boundaries."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import mph


if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


MODEL_FILE = Path(r"E:\hycodespace\Models\comsol_database\micromixer_fixed\micromixer_fixed_single_io_20260521_033038.mph")


def arr(value):
    try:
        return [float(v) for v in value]
    except Exception:
        try:
            return [int(v) for v in value]
        except Exception:
            return str(value)


def main() -> int:
    client = mph.start(cores=4)
    model = client.load(str(MODEL_FILE))
    geom = model.java.component("comp1").geom("geom1")
    geom.run()

    vertices = {}
    try:
        raw_coords = [[float(v) for v in row] for row in geom.getVertexCoord()]
        vertex_count = int(geom.getNVertices())
        if len(raw_coords) == 3 and all(len(row) == vertex_count for row in raw_coords):
            for vertex in range(1, vertex_count + 1):
                vertices[str(vertex)] = [
                    raw_coords[0][vertex - 1],
                    raw_coords[1][vertex - 1],
                    raw_coords[2][vertex - 1],
                ]
        else:
            for vertex, coord in enumerate(raw_coords, start=1):
                vertices[str(vertex)] = coord
    except Exception as exc:
        vertices["error"] = str(exc)

    boundaries = {}
    for boundary in range(1, int(geom.getNBoundaries()) + 1):
        try:
            vertex_ids = [int(v) for v in geom.getAdj(2, 0, boundary)]
            coords = [vertices[str(v)] for v in vertex_ids]
            xs = [c[0] for c in coords if isinstance(c, list)]
            ys = [c[1] for c in coords if isinstance(c, list)]
            zs = [c[2] for c in coords if isinstance(c, list)]
            boundaries[str(boundary)] = {
                "vertices": vertex_ids,
                "coords": coords,
                "bbox": {
                    "x": [min(xs), max(xs)] if xs else None,
                    "y": [min(ys), max(ys)] if ys else None,
                    "z": [min(zs), max(zs)] if zs else None,
                },
                "adjacent_domains": [int(v) for v in geom.getAdj(2, 3, boundary)],
            }
        except Exception as exc:
            boundaries[str(boundary)] = {"error": str(exc)}

    print(json.dumps({"vertices": vertices, "boundaries": boundaries}, ensure_ascii=False, indent=2))
    client.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
