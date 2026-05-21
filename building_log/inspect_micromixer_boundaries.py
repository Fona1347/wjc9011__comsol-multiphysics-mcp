"""Inspect micromixer boundary condition selections and geometry diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import mph


if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


MODEL_FILE = Path(r"E:\hycodespace\Models\comsol_database\micromixer_fixed\micromixer_fixed_single_io_20260521_033038.mph")


def tags(collection) -> list[str]:
    try:
        return [str(item.tag()) for item in collection]
    except Exception:
        return []


def java_methods(obj, limit: int = 80) -> list[str]:
    try:
        return sorted({str(method.getName()) for method in obj.getClass().getMethods()})[:limit]
    except Exception:
        return []


def java_array(value):
    try:
        return [int(v) for v in value]
    except Exception:
        try:
            return list(value)
        except Exception:
            return str(value)


def selection_entities(selection):
    attempts = {}
    for name, call in {
        "entities": lambda: selection.entities(),
        "entities_2": lambda: selection.entities(2),
        "inputEntities": lambda: selection.inputEntities(),
    }.items():
        try:
            return java_array(call()), attempts
        except Exception as exc:
            attempts[name] = str(exc)
    return None, attempts


def feature_report(physics):
    rows = []
    for feature in physics.feature():
        selection = feature.selection()
        entities, attempts = selection_entities(selection)
        rows.append(
            {
                "tag": str(feature.tag()),
                "label": str(feature.label()),
                "type": str(feature.getType()),
                "selection": entities,
                "selection_attempt_errors": attempts,
            }
        )
    return rows


def geom_diagnostics(geom):
    report = {
        "tag": str(geom.tag()),
        "label": str(geom.label()),
        "domains": int(geom.getNDomains()),
        "boundaries": int(geom.getNBoundaries()),
        "edges": int(geom.getNEdges()),
        "vertices": int(geom.getNVertices()),
        "boundary_adjacency": {},
        "boundary_vertex_candidates": {},
        "method_errors": {},
        "measure_methods": [],
    }

    for boundary in range(1, report["boundaries"] + 1):
        for args_name, args in {
            "getAdj_2_0": (2, 0, boundary),
            "getAdj_2_1": (2, 1, boundary),
            "getAdj_2_3": (2, 3, boundary),
        }.items():
            try:
                report["boundary_adjacency"].setdefault(str(boundary), {})[args_name] = java_array(geom.getAdj(*args))
            except Exception as exc:
                report["method_errors"].setdefault(args_name, str(exc))

    try:
        measure = geom.measure()
        report["measure_methods"] = java_methods(measure, 120)
    except Exception as exc:
        report["method_errors"]["measure"] = str(exc)

    return report


def main() -> int:
    client = mph.start(cores=4)
    model = client.load(str(MODEL_FILE))
    jm = model.java
    comp = jm.component("comp1")
    geom = comp.geom("geom1")
    geom.run()
    spf = comp.physics("spf")

    report = {
        "model_file": str(MODEL_FILE),
        "model_name": model.name(),
        "components": tags(jm.component()),
        "geometries": tags(comp.geom()),
        "physics": tags(comp.physics()),
        "physics_features": feature_report(spf),
        "geometry": geom_diagnostics(geom),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    client.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
