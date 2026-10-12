"""Tests for pure topology and boundary-plan helpers."""

from src.tools.topology_utils import (
    bbox_from_points,
    classify_semantics,
    centroid_from_points,
    enrich_topology,
    normalize_point,
    recommend_boundary_plan,
    validate_boundary_plan,
)


def rectangle_topology_2d():
    vertices = {
        "1": {"id": 1, "coord": [0.0, 0.0]},
        "2": {"id": 2, "coord": [1.0, 0.0]},
        "3": {"id": 3, "coord": [1.0, 0.5]},
        "4": {"id": 4, "coord": [0.0, 0.5]},
    }
    boundaries = {
        "1": {"id": 1, "vertices": [1, 2], "adjacent_domains": [1]},
        "2": {"id": 2, "vertices": [2, 3], "adjacent_domains": [1]},
        "3": {"id": 3, "vertices": [3, 4], "adjacent_domains": [1]},
        "4": {"id": 4, "vertices": [4, 1], "adjacent_domains": [1]},
    }
    for boundary in boundaries.values():
        points = [vertices[str(vertex)]["coord"] for vertex in boundary["vertices"]]
        boundary["bbox"] = bbox_from_points(points)
        boundary["centroid"] = centroid_from_points(points)
    return {
        "success": True,
        "dimension_profile": {
            "space_dim": 2,
            "domain_dim": 2,
            "boundary_dim": 1,
            "edge_dim": None,
            "vertex_dim": 0,
            "coordinate_dim": 2,
            "is_axisymmetric": False,
        },
        "entities_by_dimension": [4, 4, 1],
        "counts": {"vertices": 4, "edges": 4, "boundaries": 4, "domains": 1},
        "vertices": vertices,
        "edges": {},
        "boundaries": boundaries,
        "domains": {"1": {"id": 1, "boundaries": [1, 2, 3, 4]}},
        "diagnostics": {"method_errors": {}, "missing_fields": []},
    }


def line_topology_1d():
    vertices = {
        "1": {"id": 1, "coord": [0.0]},
        "2": {"id": 2, "coord": [2.0]},
    }
    boundaries = {
        "1": {"id": 1, "vertices": [1], "adjacent_domains": [1]},
        "2": {"id": 2, "vertices": [2], "adjacent_domains": [1]},
    }
    for boundary in boundaries.values():
        points = [vertices[str(vertex)]["coord"] for vertex in boundary["vertices"]]
        boundary["bbox"] = bbox_from_points(points)
        boundary["centroid"] = centroid_from_points(points)
    return {
        "success": True,
        "dimension_profile": {
            "space_dim": 1,
            "domain_dim": 1,
            "boundary_dim": 0,
            "edge_dim": None,
            "vertex_dim": 0,
            "coordinate_dim": 1,
            "is_axisymmetric": False,
        },
        "entities_by_dimension": [2, 1],
        "counts": {"vertices": 2, "edges": 1, "boundaries": 2, "domains": 1},
        "vertices": vertices,
        "edges": {},
        "boundaries": boundaries,
        "domains": {"1": {"id": 1, "boundaries": [1, 2]}},
        "diagnostics": {"method_errors": {}, "missing_fields": []},
    }


def test_normalize_point_and_bbox_accept_1d_2d_3d():
    assert normalize_point([1.0]) == [1.0, 0.0, 0.0]
    assert normalize_point([1.0, 2.0]) == [1.0, 2.0, 0.0]
    assert normalize_point([1.0, 2.0, 3.0]) == [1.0, 2.0, 3.0]
    assert bbox_from_points([[0.0], [2.0]]) == {"x": [0.0, 2.0], "y": [0.0, 0.0], "z": [0.0, 0.0]}
    assert centroid_from_points([[0.0, 0.0], [2.0, 2.0]]) == [1.0, 1.0, 0.0]


def test_enrich_rectangle_topology_2d_semantics():
    topology = enrich_topology(rectangle_topology_2d())

    assert topology["global_bbox"] == {"x": [0.0, 1.0], "y": [0.0, 0.5], "z": [0.0, 0.0]}
    assert topology["boundaries"]["1"]["position_tags"] == ["min_y"]
    assert topology["boundaries"]["2"]["position_tags"] == ["max_x"]
    assert topology["boundaries"]["3"]["position_tags"] == ["max_y"]
    assert topology["boundaries"]["4"]["position_tags"] == ["min_x"]
    assert all(boundary["entity_dim"] == 1 for boundary in topology["boundaries"].values())


def test_recommend_heat_transfer_rectangle_two_temperature_boundaries():
    topology = enrich_topology(rectangle_topology_2d())
    plan = recommend_boundary_plan(
        "ht",
        {
            "temperature_boundaries": [
                {"tag": "min_x", "temperature": "T_hot", "feature_tag": "temp_hot"},
                {"tag": "max_x", "temperature": "T_cold", "feature_tag": "temp_cold"},
            ],
        },
        topology,
    )
    validation = validate_boundary_plan(plan, topology)

    assert validation["status"] == "valid"
    assert plan["space_dim"] == 2
    assert plan["boundary_dim"] == 1
    assert [feature["boundary_ids"] for feature in plan["features"]] == [[4], [2]]
    assert [feature["properties"]["T0"] for feature in plan["features"]] == ["T_hot", "T_cold"]


def test_enrich_line_topology_1d_semantics():
    topology = enrich_topology(line_topology_1d())

    assert topology["global_bbox"] == {"x": [0.0, 2.0], "y": [0.0, 0.0], "z": [0.0, 0.0]}
    assert topology["boundaries"]["1"]["position_tags"] == ["min_x"]
    assert topology["boundaries"]["2"]["position_tags"] == ["max_x"]
    assert all(boundary["entity_dim"] == 0 for boundary in topology["boundaries"].values())


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


def test_geometry_dimension_profile_2d_and_vertex_fallback():
    from src.tools.geometry import _geometry_dimension_profile, _get_vertex_coord

    class FakeGeom:
        def getSDim(self):
            return 2

        def isAxisymmetric(self):
            return False

        def getVtxCoord(self, vertex_id):
            raise AttributeError("getVtxCoord unavailable")

        def getVertexCoord(self, vertex_id):
            return [float(vertex_id), float(vertex_id + 1)]

    diagnostics = {"method_errors": {}, "method_success": {}}
    profile = _geometry_dimension_profile(
        FakeGeom(),
        {"entities_by_dimension": [4, 4, 1], "vertices": 4, "edges": 4, "boundaries": 4, "domains": 1},
        diagnostics,
    )
    coord = _get_vertex_coord(FakeGeom(), 1, profile, diagnostics)

    assert profile == {
        "space_dim": 2,
        "domain_dim": 2,
        "boundary_dim": 1,
        "edge_dim": None,
        "vertex_dim": 0,
        "coordinate_dim": 2,
        "is_axisymmetric": False,
    }
    assert coord == [1.0, 2.0, 0.0]
    assert "getVtxCoord(1)" in diagnostics["method_errors"]
    assert diagnostics["method_success"]["getVertexCoord(1)"] == [1.0, 2.0, 0.0]


def test_resolve_physics_interface_by_tag_and_label():
    from src.tools.physics import _resolve_physics_interface

    class FakePhysics:
        def __init__(self, tag, label):
            self._tag = tag
            self._label = label

        def tag(self):
            return self._tag

        def label(self):
            return self._label

    class FakeComponent:
        def __init__(self):
            self._physics = [FakePhysics("ht", "Heat Transfer")]

        def tag(self):
            return "comp1"

        def physics(self):
            return self._physics

        def geom(self):
            return []

        def material(self):
            return []

        def mesh(self):
            return []

    class FakeJavaModel:
        def __init__(self):
            self._components = [FakeComponent()]

        def component(self):
            return self._components

    class FakeModel:
        java = FakeJavaModel()

    comp_by_tag, physics_by_tag, error_by_tag = _resolve_physics_interface(FakeModel(), physics_tag="ht")
    comp_by_label, physics_by_label, error_by_label = _resolve_physics_interface(
        FakeModel(),
        physics_name="Heat Transfer",
    )

    assert error_by_tag is None
    assert error_by_label is None
    assert comp_by_tag.tag() == "comp1"
    assert physics_by_tag.tag() == "ht"
    assert physics_by_label.label() == "Heat Transfer"
