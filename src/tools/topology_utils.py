"""Pure-Python helpers for geometry topology and boundary planning."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


AXES = ("x", "y", "z")
TOLERANCE = 1e-9


def as_int_list(value: Any) -> list[int]:
    """Convert Java/Python sequence-like values to a list of ints."""
    if value is None:
        return []
    try:
        return [int(v) for v in value]
    except Exception:
        try:
            return [int(v) for v in list(value)]
        except Exception:
            return []


def as_float_list(value: Any) -> list[float]:
    """Convert Java/Python sequence-like values to a list of floats."""
    if value is None:
        return []
    try:
        return [float(v) for v in value]
    except Exception:
        try:
            return [float(v) for v in list(value)]
        except Exception:
            return []


def normalize_point(point: Iterable[float] | None, coordinate_dim: int = 3) -> list[float] | None:
    """Normalize 1D/2D/3D coordinates to a 3D point."""
    if point is None:
        return None
    coords = as_float_list(point)
    if not coords:
        return None
    if len(coords) > coordinate_dim:
        coords = coords[:coordinate_dim]
    if len(coords) > 3:
        coords = coords[:3]
    while len(coords) < 3:
        coords.append(0.0)
    return coords


def normalize_points(points: Iterable[Iterable[float] | None], coordinate_dim: int = 3) -> list[list[float]]:
    """Normalize coordinate-like values to 3D points."""
    normalized = [normalize_point(point, coordinate_dim=coordinate_dim) for point in points]
    return [point for point in normalized if point is not None]


def bbox_from_points(points: Iterable[Iterable[float]]) -> dict[str, list[float]] | None:
    """Return an axis-aligned bounding box from 1D, 2D, or 3D points."""
    coords = normalize_points(points)
    if not coords:
        return None
    return {
        axis: [min(point[index] for point in coords), max(point[index] for point in coords)]
        for index, axis in enumerate(AXES)
    }


def centroid_from_points(points: Iterable[Iterable[float]]) -> list[float] | None:
    """Return the arithmetic centroid from 1D, 2D, or 3D points."""
    coords = normalize_points(points)
    if not coords:
        return None
    return [
        sum(point[index] for point in coords) / len(coords)
        for index in range(3)
    ]


def bbox_points(bbox: dict[str, list[float]] | None) -> list[list[float]]:
    """Return the two diagonal points encoded by a bbox."""
    if not bbox:
        return []
    try:
        return [
            [bbox["x"][0], bbox["y"][0], bbox["z"][0]],
            [bbox["x"][1], bbox["y"][1], bbox["z"][1]],
        ]
    except Exception:
        return []


def boundary_position_tags(
    boundary_bbox: dict[str, list[float]] | None,
    global_bbox: dict[str, list[float]] | None,
    tolerance: float = TOLERANCE,
    axes: Iterable[str] = AXES,
) -> list[str]:
    """Classify a boundary bbox against global min/max planes."""
    if not boundary_bbox or not global_bbox:
        return []

    tags: list[str] = []
    for axis in axes:
        bmin, bmax = boundary_bbox.get(axis, [None, None])
        gmin, gmax = global_bbox.get(axis, [None, None])
        if bmin is None or bmax is None or gmin is None or gmax is None:
            continue
        if abs(bmin - bmax) <= tolerance:
            if abs(bmin - gmin) <= tolerance:
                tags.append(f"min_{axis}")
            if abs(bmin - gmax) <= tolerance:
                tags.append(f"max_{axis}")
    return tags


def enrich_topology(topology: dict[str, Any]) -> dict[str, Any]:
    """Add derived flags and summaries to a GeometryGraph-like dict."""
    dimension_profile = topology.get("dimension_profile") or {}
    boundary_dim = dimension_profile.get("boundary_dim", 2)
    space_dim = int(dimension_profile.get("space_dim", 3) or 3)
    active_axes = AXES[:max(1, min(space_dim, len(AXES)))]
    vertices = topology.get("vertices", {})
    for vertex in vertices.values():
        if vertex.get("coord"):
            vertex["coord"] = normalize_point(vertex.get("coord")) or []
    points = [vertex.get("coord") for vertex in vertices.values() if vertex.get("coord")]
    global_bbox = bbox_from_points(points)
    topology["global_bbox"] = global_bbox

    boundary_to_domains: dict[int, set[int]] = defaultdict(set)
    for domain in topology.get("domains", {}).values():
        domain_id = int(domain["id"])
        for boundary_id in domain.get("boundaries", []):
            boundary_to_domains[int(boundary_id)].add(domain_id)

    domain_to_boundaries: dict[int, set[int]] = defaultdict(set)
    for boundary in topology.get("boundaries", {}).values():
        boundary_id = int(boundary["id"])
        adjacent_domains = [int(item) for item in boundary.get("adjacent_domains", [])]
        if not adjacent_domains and boundary_id in boundary_to_domains:
            adjacent_domains = sorted(boundary_to_domains[boundary_id])
            boundary["adjacent_domains"] = adjacent_domains
        boundary["is_exterior"] = len(adjacent_domains) == 1
        boundary["is_interface"] = len(adjacent_domains) > 1
        boundary["position_tags"] = boundary_position_tags(boundary.get("bbox"), global_bbox, axes=active_axes)
        boundary["entity_dim"] = boundary.get("entity_dim", boundary_dim)
        for domain_id in adjacent_domains:
            domain_to_boundaries[domain_id].add(int(boundary["id"]))

    for domain in topology.get("domains", {}).values():
        domain_id = int(domain["id"])
        if not domain.get("boundaries"):
            domain["boundaries"] = sorted(domain_to_boundaries.get(domain_id, set()))
        boundary_bboxes = [
            topology["boundaries"].get(str(boundary_id), {}).get("bbox")
            or topology["boundaries"].get(boundary_id, {}).get("bbox")
            for boundary_id in domain.get("boundaries", [])
        ]
        domain_points = []
        for bbox in boundary_bboxes:
            domain_points.extend(bbox_points(bbox))
        if domain_points:
            domain["bbox"] = bbox_from_points(domain_points)
            domain["centroid"] = centroid_from_points(domain_points)

    return topology


def classify_semantics(topology: dict[str, Any]) -> dict[str, Any]:
    """Create explainable semantic candidates from a topology graph."""
    topology = enrich_topology(topology)
    boundary_dim = (topology.get("dimension_profile") or {}).get("boundary_dim", 2)
    candidates: list[dict[str, Any]] = []
    summary = {
        "exterior_boundaries": [],
        "interface_boundaries": [],
        "position_tags": {},
    }

    for boundary in topology.get("boundaries", {}).values():
        boundary_id = int(boundary["id"])
        position_tags = list(boundary.get("position_tags", []))
        if boundary.get("is_interface"):
            summary["interface_boundaries"].append(boundary_id)
            candidates.append({
                "entity_dim": boundary_dim,
                "entity_id": boundary_id,
                "label": "interface_candidate",
                "confidence": 0.95,
                "evidence": [
                    f"boundary touches domains {boundary.get('adjacent_domains', [])}",
                ],
                "warnings": ["Do not apply exterior wall/port conditions unless intended."],
            })
            continue

        if boundary.get("is_exterior"):
            summary["exterior_boundaries"].append(boundary_id)
            candidates.extend([
                {
                    "entity_dim": boundary_dim,
                    "entity_id": boundary_id,
                    "label": "wall_candidate",
                    "confidence": 0.75,
                    "evidence": ["boundary touches exactly one domain"],
                    "warnings": [],
                },
                {
                    "entity_dim": boundary_dim,
                    "entity_id": boundary_id,
                    "label": "thermal_boundary_candidate",
                    "confidence": 0.65,
                    "evidence": ["external boundary can accept thermal boundary conditions"],
                    "warnings": [],
                },
                {
                    "entity_dim": boundary_dim,
                    "entity_id": boundary_id,
                    "label": "fixed_support_candidate",
                    "confidence": 0.55,
                    "evidence": ["external boundary can constrain solid mechanics"],
                    "warnings": ["Requires user intent for support direction/location."],
                },
                {
                    "entity_dim": boundary_dim,
                    "entity_id": boundary_id,
                    "label": "load_face_candidate",
                    "confidence": 0.55,
                    "evidence": ["external boundary can receive loads"],
                    "warnings": ["Requires user intent for load direction/value."],
                },
            ])
            if position_tags:
                summary["position_tags"][boundary_id] = position_tags
                candidates.extend([
                    {
                        "entity_dim": boundary_dim,
                        "entity_id": boundary_id,
                        "label": "inlet_candidate",
                        "confidence": 0.7,
                        "evidence": [
                            "external boundary lies on global plane(s): "
                            + ", ".join(position_tags),
                        ],
                        "warnings": ["Requires flow direction/user intent."],
                    },
                    {
                        "entity_dim": boundary_dim,
                        "entity_id": boundary_id,
                        "label": "outlet_candidate",
                        "confidence": 0.7,
                        "evidence": [
                            "external boundary lies on global plane(s): "
                            + ", ".join(position_tags),
                        ],
                        "warnings": ["Requires flow direction/user intent."],
                    },
                    {
                        "entity_dim": boundary_dim,
                        "entity_id": boundary_id,
                        "label": "symmetry_candidate",
                        "confidence": 0.45,
                        "evidence": [
                            "planar boundary lies on global extremum plane(s): "
                            + ", ".join(position_tags),
                        ],
                        "warnings": ["Low confidence unless paired with symmetric geometry."],
                    },
                ])

    return {
        "success": True,
        "semantic_candidates": candidates,
        "summary": summary,
    }


def _boundaries_with_position(topology: dict[str, Any], tag: str) -> list[int]:
    return [
        int(boundary["id"])
        for boundary in topology.get("boundaries", {}).values()
        if tag in boundary.get("position_tags", []) and boundary.get("is_exterior")
    ]


def recommend_boundary_plan(
    physics_tag: str,
    intent: dict[str, Any] | None,
    topology: dict[str, Any],
    semantics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recommend a non-mutating boundary condition plan."""
    del semantics
    topology = enrich_topology(topology)
    intent = intent or {}
    physics_tag = physics_tag or intent.get("physics_tag", "")
    physics_key = physics_tag.lower()
    dimension_profile = topology.get("dimension_profile") or {}
    features: list[dict[str, Any]] = []
    warnings: list[str] = []

    if physics_key in {"spf", "laminar_flow", "laminarflow"}:
        inlet_tag = intent.get("inlet")
        outlet_tag = intent.get("outlet")
        axis = intent.get("flow_axis", "x")
        if not inlet_tag:
            inlet_tag = f"min_{axis}"
        if not outlet_tag:
            outlet_tag = f"max_{axis}"

        inlet_ids = _boundaries_with_position(topology, inlet_tag)
        outlet_ids = _boundaries_with_position(topology, outlet_tag)
        used = set(inlet_ids + outlet_ids)
        wall_ids = [
            int(boundary["id"])
            for boundary in topology.get("boundaries", {}).values()
            if boundary.get("is_exterior") and int(boundary["id"]) not in used
        ]

        features.append({
            "feature_tag": "inl_auto",
            "type": "InletBoundary",
            "boundary_ids": inlet_ids,
            "properties": {"U0in": intent.get("inlet_velocity", "1[mm/s]")},
            "reason": f"Selected exterior boundary on {inlet_tag}.",
            "confidence": 0.8 if inlet_ids else 0.0,
        })
        features.append({
            "feature_tag": "out_auto",
            "type": "OutletBoundary",
            "boundary_ids": outlet_ids,
            "properties": {"p0": intent.get("outlet_pressure", "0")},
            "reason": f"Selected exterior boundary on {outlet_tag}.",
            "confidence": 0.8 if outlet_ids else 0.0,
        })
        if wall_ids:
            features.append({
                "feature_tag": "wall_auto",
                "type": "Wall",
                "boundary_ids": wall_ids,
                "properties": {},
                "reason": "Remaining exterior boundaries default to wall.",
                "confidence": 0.7,
            })
    elif physics_key in {"ht", "heat_transfer", "heattransfer"}:
        thermal_boundaries = intent.get("temperature_boundaries")
        if not thermal_boundaries:
            thermal_boundaries = [{
                "tag": intent.get("target", "max_x"),
                "temperature": intent.get("temperature", "293.15[K]"),
                "feature_tag": "thermal_auto",
            }]
        for index, item in enumerate(thermal_boundaries, start=1):
            target_tag = item.get("tag") or item.get("target") or "max_x"
            boundary_ids = _boundaries_with_position(topology, target_tag)
            feature_type = item.get("boundary_type", intent.get("boundary_type", "TemperatureBoundary"))
            properties = item.get("properties", {"T0": item.get("temperature", "293.15[K]")})
            features.append({
                "feature_tag": item.get("feature_tag", f"thermal_auto_{index}"),
                "type": feature_type,
                "boundary_ids": boundary_ids,
                "properties": properties,
                "reason": f"Selected exterior boundary on {target_tag}.",
                "confidence": 0.7 if boundary_ids else 0.0,
            })
    elif physics_key in {"solid", "solid_mechanics", "solidmechanics"}:
        fixed_tag = intent.get("fixed", "min_z")
        load_tag = intent.get("load", "max_z")
        fixed_ids = _boundaries_with_position(topology, fixed_tag)
        load_ids = _boundaries_with_position(topology, load_tag)
        features.append({
            "feature_tag": "fix_auto",
            "type": "Fixed",
            "boundary_ids": fixed_ids,
            "properties": {},
            "reason": f"Selected exterior boundary on {fixed_tag}.",
            "confidence": 0.75 if fixed_ids else 0.0,
        })
        features.append({
            "feature_tag": "load_auto",
            "type": "BoundaryLoad",
            "boundary_ids": load_ids,
            "properties": intent.get("load_properties", {}),
            "reason": f"Selected exterior boundary on {load_tag}.",
            "confidence": 0.65 if load_ids else 0.0,
        })
        if not fixed_ids:
            warnings.append("Solid mechanics plan has no fixed support; rigid-body drift is likely.")
    else:
        warnings.append(f"No v1 recommender for physics_tag '{physics_tag}'.")

    plan = {
        "physics_tag": physics_tag,
        "component": intent.get("component", "comp1"),
        "geometry": intent.get("geometry", "geom1"),
        "space_dim": dimension_profile.get("space_dim"),
        "boundary_dim": dimension_profile.get("boundary_dim"),
        "features": features,
        "validation": {"status": "unvalidated", "errors": [], "warnings": warnings},
        "requires_user_confirmation": any(feature["confidence"] < 0.5 for feature in features),
    }
    return plan


def validate_boundary_plan(
    plan: dict[str, Any],
    topology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a boundary condition plan against topology and v1 physics rules."""
    errors: list[str] = []
    warnings: list[str] = list(plan.get("validation", {}).get("warnings", []))
    topology = enrich_topology(topology or {})
    boundary_by_id = {
        int(boundary["id"]): boundary
        for boundary in topology.get("boundaries", {}).values()
        if "id" in boundary
    }
    valid_boundary_ids = set(boundary_by_id)
    boundary_claims: dict[int, list[str]] = defaultdict(list)

    for feature in plan.get("features", []):
        feature_type = feature.get("type", "")
        boundary_ids = [int(boundary_id) for boundary_id in feature.get("boundary_ids", [])]
        if not boundary_ids:
            errors.append(f"{feature_type} has no boundary_ids.")
            continue
        for boundary_id in boundary_ids:
            if valid_boundary_ids and boundary_id not in valid_boundary_ids:
                errors.append(f"{feature_type} references missing boundary {boundary_id}.")
                continue
            boundary_claims[boundary_id].append(feature_type)
            boundary = boundary_by_id.get(boundary_id, {})
            if boundary.get("is_interface") and feature_type in {
                "Wall",
                "InletBoundary",
                "OutletBoundary",
                "TemperatureBoundary",
                "HeatFluxBoundary",
                "ConvectiveHeatFlux",
            }:
                errors.append(
                    f"{feature_type} on boundary {boundary_id} targets an internal interface."
                )

    for boundary_id, types in boundary_claims.items():
        unique = set(types)
        if len(unique) > 1:
            errors.append(f"Boundary {boundary_id} has conflicting conditions: {sorted(unique)}.")

    physics_key = str(plan.get("physics_tag", "")).lower()
    feature_types = [feature.get("type") for feature in plan.get("features", [])]
    if physics_key in {"spf", "laminar_flow", "laminarflow"}:
        if "InletBoundary" not in feature_types:
            errors.append("Laminar flow plan requires at least one InletBoundary.")
        if "OutletBoundary" not in feature_types:
            errors.append("Laminar flow plan requires at least one OutletBoundary.")
    if physics_key in {"solid", "solid_mechanics", "solidmechanics"} and "Fixed" not in feature_types:
        warnings.append("Solid mechanics plan has no Fixed boundary; rigid-body drift is likely.")

    status = "invalid" if errors else "needs_confirmation" if plan.get("requires_user_confirmation") else "valid"
    return {"status": status, "errors": errors, "warnings": warnings}


def unit_cube_topology() -> dict[str, Any]:
    """Return a deterministic 1 x 1 x 1 cube topology fixture."""
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
        boundary["bbox"] = bbox_from_points(points)
        boundary["centroid"] = centroid_from_points(points)
        boundary["area"] = 1.0
    return enrich_topology({
        "success": True,
        "model": "unit_cube_fixture",
        "component": "comp1",
        "geometry": "geom1",
        "entities_by_dimension": [8, 12, 6, 1],
        "counts": {"vertices": 8, "edges": 12, "boundaries": 6, "domains": 1},
        "vertices": vertices,
        "edges": edges,
        "boundaries": boundaries,
        "domains": {"1": {"id": 1, "boundaries": [1, 2, 3, 4, 5, 6]}},
        "diagnostics": {"method_errors": {}, "missing_fields": []},
    })
