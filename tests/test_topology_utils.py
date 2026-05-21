"""Tests for pure topology and boundary-plan helpers."""

from src.tools.topology_utils import (
    classify_semantics,
    enrich_topology,
    recommend_boundary_plan,
    validate_boundary_plan,
)


def cube_topology():
    vertices = {
        "1": {"id": 1, "coord": [0.0, 0.0, 0.0]},
        "2": {"id": 2, "coord": [1.0, 0.0, 0.0]},
        "3": {"id": 3, "coord": [1.0, 1.0, 0.0]},
        "4": {"id": 4, "coord": [0.0, 1.0, 0.0]},
        "5": {"id": 5, "coord": [0.0, 0.0, 1.0]},
        "6": {"id": 6, "coord": [1.0, 0.0, 1.0]},
        "7": {"id": 7, "coord": [1.0, 1.0, 1.0]},
        "8": {"id": 8, "coord": [0.0, 1.0, 1.0]},
    }
    edges = {
        str(i): {"id": i, "vertices": pair}
        for i, pair in enumerate(
            [
                [1, 2], [2, 3], [3, 4], [4, 1],
                [5, 6], [6, 7], [7, 8], [8, 5],
                [1, 5], [2, 6], [3, 7], [4, 8],
            ],
            start=1,
        )
    }
    boundaries = {
        "1": {"id": 1, "vertices": [1, 4, 8, 5], "edges": [4, 8, 9, 12], "adjacent_domains": [1]},
        "2": {"id": 2, "vertices": [2, 3, 7, 6], "edges": [2, 6, 10, 11], "adjacent_domains": [1]},
        "3": {"id": 3, "vertices": [1, 2, 6, 5], "edges": [1, 5, 9, 10], "adjacent_domains": [1]},
        "4": {"id": 4, "vertices": [4, 3, 7, 8], "edges": [3, 7, 11, 12], "adjacent_domains": [1]},
        "5": {"id": 5, "vertices": [1, 2, 3, 4], "edges": [1, 2, 3, 4], "adjacent_domains": [1]},
        "6": {"id": 6, "vertices": [5, 6, 7, 8], "edges": [5, 6, 7, 8], "adjacent_domains": [1]},
    }
    for boundary in boundaries.values():
        points = [vertices[str(vertex)]["coord"] for vertex in boundary["vertices"]]
        boundary["bbox"] = {
            axis: [min(point[index] for point in points), max(point[index] for point in points)]
            for index, axis in enumerate(("x", "y", "z"))
        }

    return {
        "success": True,
        "entities_by_dimension": [8, 12, 6, 1],
        "counts": {"vertices": 8, "edges": 12, "boundaries": 6, "domains": 1},
        "vertices": vertices,
        "edges": edges,
        "boundaries": boundaries,
        "domains": {"1": {"id": 1, "boundaries": [1, 2, 3, 4, 5, 6]}},
        "diagnostics": {"method_errors": {}, "missing_fields": []},
    }


def test_enrich_cube_topology_invariants():
    topology = enrich_topology(cube_topology())

    assert topology["global_bbox"] == {"x": [0.0, 1.0], "y": [0.0, 1.0], "z": [0.0, 1.0]}
    assert len(topology["vertices"]) == 8
    assert len(topology["edges"]) == 12
    assert len(topology["boundaries"]) == 6
    assert len(topology["domains"]) == 1
    assert topology["domains"]["1"]["boundaries"] == [1, 2, 3, 4, 5, 6]
    for boundary in topology["boundaries"].values():
        assert len(boundary["vertices"]) == 4
        assert len(boundary["edges"]) == 4
        assert boundary["adjacent_domains"] == [1]
        assert boundary["is_exterior"] is True
        assert boundary["is_interface"] is False
        assert boundary["position_tags"]


def test_classify_cube_semantics():
    semantics = classify_semantics(cube_topology())

    assert semantics["success"] is True
    assert sorted(semantics["summary"]["exterior_boundaries"]) == [1, 2, 3, 4, 5, 6]
    assert semantics["summary"]["interface_boundaries"] == []
    labels = {candidate["label"] for candidate in semantics["semantic_candidates"]}
    assert "wall_candidate" in labels
    assert "inlet_candidate" in labels
    assert "outlet_candidate" in labels


def test_recommend_and_validate_laminar_flow_cube_plan():
    topology = enrich_topology(cube_topology())
    plan = recommend_boundary_plan(
        "spf",
        {"flow_axis": "x", "inlet_velocity": "1[m/s]", "outlet_pressure": "0"},
        topology,
    )
    validation = validate_boundary_plan(plan, topology)

    assert validation["status"] == "valid"
    feature_types = {feature["type"] for feature in plan["features"]}
    assert {"InletBoundary", "OutletBoundary", "Wall"}.issubset(feature_types)


def test_validate_rejects_interface_wall_conflict():
    topology = cube_topology()
    topology["boundaries"]["1"]["adjacent_domains"] = [1, 2]
    topology["domains"]["2"] = {"id": 2, "boundaries": [1]}
    topology = enrich_topology(topology)
    plan = {
        "physics_tag": "spf",
        "features": [
            {"type": "InletBoundary", "boundary_ids": [2], "properties": {}},
            {"type": "OutletBoundary", "boundary_ids": [3], "properties": {}},
            {"type": "Wall", "boundary_ids": [1], "properties": {}},
        ],
        "validation": {"warnings": []},
    }

    validation = validate_boundary_plan(plan, topology)

    assert validation["status"] == "invalid"
    assert any("internal interface" in error for error in validation["errors"])
