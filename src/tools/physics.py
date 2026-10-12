"""Physics tools for COMSOL MCP Server."""

from typing import Optional, Sequence
from mcp.server.fastmcp import FastMCP

from .geometry import _analyze_geometry_topology
from .session import session_manager
from .topology_utils import (
    classify_semantics,
    recommend_boundary_plan,
    validate_boundary_plan,
)


PHYSICS_INTERFACES = {
    "AC/DC": {
        "electrostatic": "Electrostatics (es)",
        "electric_currents": "Electric Currents (ec)",
        "magnetic_fields": "Magnetic Fields (mf)",
        "electromagnetic_waves": "Electromagnetic Waves (emw)",
    },
    "Structural": {
        "solid_mechanics": "Solid Mechanics (solid)",
        "shell": "Shell (shell)",
        "beam": "Beam (beam)",
        "membrane": "Membrane (memb)",
    },
    "Heat Transfer": {
        "heat_transfer": "Heat Transfer in Solids (ht)",
        "conjugate_ht": "Conjugate Heat Transfer (cht)",
        "radiation": "Radiation (rad)",
    },
    "Fluid Flow": {
        "laminar_flow": "Laminar Flow (spf)",
        "turbulent_flow": "Turbulent Flow (spf)",
        "creeping_flow": "Creeping Flow (brinkman)",
    },
    "Acoustics": {
        "pressure_acoustics": "Pressure Acoustics (acpr)",
        "thermoacoustics": "Thermoacoustics (ta)",
    },
    "Chemical": {
        "transport_diluted": "Transport of Diluted Species (tds)",
        "reaction_engineering": "Reaction Engineering (re)",
    },
    "Optics": {
        "ray_optics": "Geometrical Optics (gop)",
        "wave_optics": "Wave Optics (ewfd)",
    },
    "Multiphysics": {
        "thermal_stress": "Thermal Stress (ts)",
        "fluid_structure": "Fluid-Structure Interaction (fsi)",
        "electromechanical": "Electromechanical Forces",
        "joule_heating": "Joule Heating (jh)",
    },
}


def _java_class_name(obj) -> str:
    """Return a Java object's class name without failing the caller."""
    try:
        return str(obj.getClass().getName())
    except Exception:
        return type(obj).__name__


def _java_method_names(obj, limit: int = 120) -> list[str]:
    """Return a compact, sorted list of public Java method names."""
    try:
        names = sorted({str(method.getName()) for method in obj.getClass().getMethods()})
        return names[:limit]
    except Exception:
        return []


def _java_array_to_list(value) -> list:
    """Convert Java arrays/sequences to Python lists where possible."""
    if value is None:
        return []
    try:
        return [int(v) for v in value]
    except Exception:
        try:
            return list(value)
        except Exception:
            return [str(value)]


def _get_component_for_geometry(jm, geometry_name: str):
    """Find the component containing a geometry tag."""
    for comp in jm.component():
        try:
            if geometry_name in [str(g.tag()) for g in comp.geom()]:
                return comp
        except Exception:
            continue
    return None


def _java_tags(collection) -> list[str]:
    """Return Java node tags from a COMSOL collection."""
    tags = []
    try:
        for item in collection:
            tags.append(str(item.tag()))
    except Exception:
        pass
    return tags


def _java_node_label(node) -> str:
    """Return a Java node label, falling back to its tag."""
    try:
        return str(node.label())
    except Exception:
        try:
            return str(node.tag())
        except Exception:
            return ""


def _available_context(jm) -> dict:
    """Summarize available component, geometry, and physics tags."""
    components = []
    for comp in jm.component():
        comp_info = {
            "tag": str(comp.tag()),
            "label": _java_node_label(comp),
            "geometries": [],
            "physics": [],
            "materials": [],
            "meshes": [],
        }
        try:
            comp_info["geometries"] = [
                {"tag": str(geom.tag()), "label": _java_node_label(geom)}
                for geom in comp.geom()
            ]
        except Exception:
            pass
        try:
            comp_info["physics"] = [
                {"tag": str(physics.tag()), "label": _java_node_label(physics)}
                for physics in comp.physics()
            ]
        except Exception:
            pass
        try:
            comp_info["materials"] = [
                {"tag": str(material.tag()), "label": _java_node_label(material)}
                for material in comp.material()
            ]
        except Exception:
            pass
        try:
            comp_info["meshes"] = [
                {"tag": str(mesh.tag()), "label": _java_node_label(mesh)}
                for mesh in comp.mesh()
            ]
        except Exception:
            pass
        components.append(comp_info)
    return {"components": components}


def _get_component_by_tag(jm, component_name: str):
    """Resolve a component by Java tag."""
    available = _java_tags(jm.component())
    if component_name not in available:
        return None, {
            "success": False,
            "error": f"Component tag not found: {component_name}",
            "available": _available_context(jm),
        }
    return jm.component(component_name), None


def _get_geometry_by_tag(comp, geometry_name: str):
    """Resolve a geometry under a component by Java tag."""
    available = _java_tags(comp.geom())
    if geometry_name not in available:
        return None, {
            "success": False,
            "error": (
                f"Geometry tag not found in component '{comp.tag()}': "
                f"{geometry_name}"
            ),
            "available_geometries": available,
        }
    return comp.geom(geometry_name), None


def _resolve_component_geometry(model, component_name: str, geometry_name: str):
    """Resolve the explicit COMSOL component and geometry context."""
    jm = model.java
    comp, error = _get_component_by_tag(jm, component_name)
    if error:
        return None, None, error
    geom, error = _get_geometry_by_tag(comp, geometry_name)
    if error:
        error["available"] = _available_context(jm)
        return None, None, error
    return comp, geom, None


PHYSICS_TYPE_MAP = {
    "es": ("es", "Electrostatics", "Electrostatics"),
    "electrostatics": ("es", "Electrostatics", "Electrostatics"),
    "Electrostatics": ("es", "Electrostatics", "Electrostatics"),
    "solid": ("solid", "SolidMechanics", "Solid Mechanics"),
    "solid_mechanics": ("solid", "SolidMechanics", "Solid Mechanics"),
    "SolidMechanics": ("solid", "SolidMechanics", "Solid Mechanics"),
    "ht": ("ht", "HeatTransfer", "Heat Transfer"),
    "heat_transfer": ("ht", "HeatTransfer", "Heat Transfer"),
    "HeatTransfer": ("ht", "HeatTransfer", "Heat Transfer"),
    "spf": ("spf", "LaminarFlow", "Laminar Flow"),
    "laminar_flow": ("spf", "LaminarFlow", "Laminar Flow"),
    "LaminarFlow": ("spf", "LaminarFlow", "Laminar Flow"),
}


def _physics_definition(physics_type: str, physics_tag: Optional[str] = None):
    """Resolve shorthand physics identifiers to Java tag/type/label."""
    default_tag, java_type, label = PHYSICS_TYPE_MAP.get(
        physics_type,
        (physics_type.lower(), physics_type, physics_type),
    )
    return physics_tag or default_tag, java_type, label


def _apply_domain_selection(node, domain_selection):
    """Apply a COMSOL domain selection to a physics/material node when provided."""
    if domain_selection is None:
        return
    try:
        if isinstance(domain_selection, str):
            node.selection().named(domain_selection)
        else:
            node.selection().set([int(domain) for domain in domain_selection])
    except Exception:
        pass


def _create_component_physics(
    model,
    physics_type: str,
    component_name: str,
    geometry_name: str,
    physics_tag: Optional[str] = None,
    domain_selection=None,
) -> dict:
    """Create or reuse a physics interface in an explicit component/geometry."""
    comp, geom, error = _resolve_component_geometry(model, component_name, geometry_name)
    if error:
        return error

    tag, java_type, label = _physics_definition(physics_type, physics_tag)
    existing = _java_tags(comp.physics())
    if tag in existing:
        physics = comp.physics(tag)
        created = False
    else:
        physics = comp.physics().create(tag, java_type, geometry_name)
        created = True
        try:
            physics.label(label)
        except Exception:
            pass

    _apply_domain_selection(physics, domain_selection)

    return {
        "success": True,
        "model": model.name(),
        "component": str(comp.tag()),
        "geometry": str(geom.tag()),
        "physics": {
            "tag": str(physics.tag()),
            "label": _java_node_label(physics),
            "type": java_type,
            "created": created,
            "domain_selection": domain_selection,
        },
    }


def _resolve_physics_interface(
    model,
    physics_tag: Optional[str] = None,
    physics_name: Optional[str] = None,
    component_name: Optional[str] = None,
):
    """Resolve a physics interface by tag first, then label/name."""
    jm = model.java
    for comp in jm.component():
        if component_name and str(comp.tag()) != component_name:
            continue
        for physics in comp.physics():
            tag = str(physics.tag())
            label = _java_node_label(physics)
            if physics_tag and tag == physics_tag:
                return comp, physics, None
            if not physics_tag and physics_name and physics_name in (tag, label):
                return comp, physics, None
    target = physics_tag or physics_name
    return None, None, {
        "success": False,
        "error": f"Physics interface tag/label not found: {target}",
        "available": _available_context(jm),
    }


def _next_feature_tag(container, prefix: str) -> str:
    """Choose a deterministic feature tag that does not already exist."""
    existing = set(_java_tags(container.feature()))
    index = 1
    tag = f"{prefix}{index}"
    while tag in existing:
        index += 1
        tag = f"{prefix}{index}"
    return tag


def _resolve_java_target(model, target: str):
    """Resolve a small set of target descriptors for Java API diagnostics."""
    jm = model.java
    target = target or "model"

    if target == "model":
        return jm, "model"

    if target.startswith("component:"):
        tag = target.split(":", 1)[1]
        return jm.component(tag), target

    if target.startswith("geometry:"):
        tag = target.split(":", 1)[1]
        comp = _get_component_for_geometry(jm, tag)
        if comp is None:
            raise ValueError(f"Geometry not found in components: {tag}")
        return comp.geom(tag), target

    if target.startswith("physics:"):
        tag = target.split(":", 1)[1]
        for comp in jm.component():
            for physics in comp.physics():
                if tag in (str(physics.tag()), str(physics.label())):
                    return physics, target
        raise ValueError(f"Physics interface not found: {tag}")

    if target.startswith("study:"):
        tag = target.split(":", 1)[1]
        return jm.study(tag), target

    raise ValueError(
        "Unknown target. Use one of: model, component:<tag>, geometry:<tag>, "
        "physics:<tag-or-label>, study:<tag>."
    )


def _topology_for_plan(
    model,
    plan: dict,
    topology: Optional[dict] = None,
) -> dict:
    """Resolve topology for validation/recommendation helpers."""
    if topology:
        return topology
    component_name = plan.get("component", "comp1")
    geometry_name = plan.get("geometry", "geom1")
    return _analyze_geometry_topology(model, geometry_name, component_name)


def _create_boundary_feature(physics, feature: dict) -> dict:
    """Create one COMSOL physics boundary feature from a plan entry."""
    requested_tag = feature.get("feature_tag") or "bc_auto"
    existing = set(_java_tags(physics.feature()))
    tag = requested_tag if requested_tag not in existing else _next_feature_tag(physics, "bc")
    feature_type = feature.get("type", "")
    bc = physics.create(tag, feature_type)
    boundary_ids = [int(boundary_id) for boundary_id in feature.get("boundary_ids", [])]
    bc.selection().set(boundary_ids)

    property_errors = {}
    for prop_name, prop_value in (feature.get("properties") or {}).items():
        try:
            bc.set(prop_name, prop_value)
        except Exception as exc:
            property_errors[prop_name] = str(exc)

    try:
        bc.label(f"{feature_type} ({boundary_ids})")
    except Exception:
        pass

    return {
        "tag": str(bc.tag()),
        "type": feature_type,
        "boundary_ids": boundary_ids,
        "properties": feature.get("properties") or {},
        "property_errors": property_errors,
    }


def _probe_geometry_entities(model, geometry_name: Optional[str] = None) -> dict:
    """Probe geometry entity counts using COMSOL 6.4 GeomInfo methods."""
    geometries = model.geometries()
    if not geometries:
        return {"success": False, "error": "No geometries found"}

    target_geom = geometry_name or geometries[0]
    jm = model.java
    comp = _get_component_for_geometry(jm, target_geom)
    if comp is None:
        return {"success": False, "error": "Geometry not found in components"}

    geom = comp.geom(target_geom)
    geom.run()

    diagnostics = {
        "java_class": _java_class_name(geom),
        "available_methods": _java_method_names(geom),
        "entity_source": "GeomInfo methods on GeomSequence",
        "method_errors": {},
    }

    counts = {}
    for key, method_name in (
        ("domains", "getNDomains"),
        ("boundaries", "getNBoundaries"),
        ("edges", "getNEdges"),
        ("vertices", "getNVertices"),
    ):
        try:
            counts[key] = int(getattr(geom, method_name)())
        except Exception as exc:
            counts[key] = None
            diagnostics["method_errors"][method_name] = str(exc)

    try:
        counts["entities_by_dimension"] = _java_array_to_list(geom.getNEntities())
    except Exception as exc:
        counts["entities_by_dimension"] = []
        diagnostics["method_errors"]["getNEntities"] = str(exc)

    boundary_count = counts.get("boundaries")
    boundaries = []
    if isinstance(boundary_count, int) and boundary_count >= 0:
        boundaries = [{"boundary_number": i} for i in range(1, boundary_count + 1)]

    return {
        "success": True,
        "geometry": target_geom,
        "counts": counts,
        "boundaries": boundaries,
        "diagnostics": diagnostics,
    }


def register_physics_tools(mcp: FastMCP) -> None:
    """Register physics tools with the MCP server."""
    
    @mcp.tool()
    def physics_list(model_name: Optional[str] = None) -> dict:
        """
        List all physics interfaces defined in a model.
        
        Args:
            model_name: Model name (default: current model)
        
        Returns:
            List of physics interface names
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            physics = model.physics()
            multiphysics = model.multiphysics()
            
            return {
                "success": True,
                "physics": physics,
                "multiphysics": multiphysics,
                "physics_count": len(physics),
                "multiphysics_count": len(multiphysics),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list physics: {str(e)}"}
    
    @mcp.tool()
    def physics_get_available() -> dict:
        """
        Get a list of available physics interfaces organized by category.
        
        Returns:
            Dictionary of physics categories and their interfaces
        """
        return {
            "success": True,
            "interfaces": PHYSICS_INTERFACES,
            "note": "Interface identifiers (in parentheses) are used when adding physics.",
        }
    
    @mcp.tool()
    def physics_add(
        physics_type: str,
        component_name: str = "comp1",
        geometry_name: str = "geom1",
        physics_tag: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add a physics interface to the model.
        
        Common physics types:
        - "Electrostatics" or "es": Electrostatic field analysis
        - "ElectricCurrents" or "ec": Electric current conduction
        - "SolidMechanics" or "solid": Structural stress analysis
        - "HeatTransfer" or "ht": Heat transfer in solids
        - "LaminarFlow" or "spf": Fluid dynamics
        
        Args:
            physics_type: Type identifier (e.g., "Electrostatics", "es")
            component_name: Component tag to add physics to (default: comp1)
            geometry_name: Geometry tag to bind physics to (default: geom1)
            physics_tag: Physics interface tag (default inferred from type)
            model_name: Model name (default: current model)
        
        Returns:
            Created physics interface info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            return _create_component_physics(
                model,
                physics_type,
                component_name,
                geometry_name,
                physics_tag,
            )
        except Exception as e:
            return {"success": False, "error": f"Failed to add physics: {str(e)}"}
    
    @mcp.tool()
    def physics_add_electrostatics(
        domain_selection: Optional[str] = None,
        component_name: str = "comp1",
        geometry_name: str = "geom1",
        physics_tag: str = "es",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add Electrostatics physics interface for electric field analysis.
        
        Args:
            domain_selection: Selection name for domains (default: all domains)
            component_name: Component tag (default: comp1)
            geometry_name: Geometry tag (default: geom1)
            physics_tag: Physics tag (default: es)
            model_name: Model name (default: current model)
        
        Returns:
            Created physics info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            return _create_component_physics(
                model,
                "Electrostatics",
                component_name,
                geometry_name,
                physics_tag,
                domain_selection,
            )
        except Exception as e:
            return {"success": False, "error": f"Failed to add Electrostatics: {str(e)}"}
    
    @mcp.tool()
    def physics_add_solid_mechanics(
        domain_selection: Optional[str] = None,
        component_name: str = "comp1",
        geometry_name: str = "geom1",
        physics_tag: str = "solid",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add Solid Mechanics physics for structural analysis.
        
        Args:
            domain_selection: Selection name for domains (default: all domains)
            component_name: Component tag (default: comp1)
            geometry_name: Geometry tag (default: geom1)
            physics_tag: Physics tag (default: solid)
            model_name: Model name (default: current model)
        
        Returns:
            Created physics info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            return _create_component_physics(
                model,
                "SolidMechanics",
                component_name,
                geometry_name,
                physics_tag,
                domain_selection,
            )
        except Exception as e:
            return {"success": False, "error": f"Failed to add Solid Mechanics: {str(e)}"}
    
    @mcp.tool()
    def physics_add_heat_transfer(
        domain_selection: Optional[str] = None,
        component_name: str = "comp1",
        geometry_name: str = "geom1",
        physics_tag: str = "ht",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add Heat Transfer physics for thermal analysis.
        
        Args:
            domain_selection: Selection name for domains (default: all domains)
            component_name: Component tag (default: comp1)
            geometry_name: Geometry tag (default: geom1)
            physics_tag: Physics tag (default: ht)
            model_name: Model name (default: current model)
        
        Returns:
            Created physics info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            return _create_component_physics(
                model,
                "HeatTransfer",
                component_name,
                geometry_name,
                physics_tag,
                domain_selection,
            )
        except Exception as e:
            return {"success": False, "error": f"Failed to add Heat Transfer: {str(e)}"}
    
    @mcp.tool()
    def physics_add_laminar_flow(
        domain_selection: Optional[str] = None,
        component_name: str = "comp1",
        geometry_name: str = "geom1",
        physics_tag: str = "spf",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add Laminar Flow physics for fluid dynamics.
        
        Args:
            domain_selection: Selection name for domains (default: all domains)
            component_name: Component tag (default: comp1)
            geometry_name: Geometry tag (default: geom1)
            physics_tag: Physics tag (default: spf)
            model_name: Model name (default: current model)
        
        Returns:
            Created physics info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            return _create_component_physics(
                model,
                "LaminarFlow",
                component_name,
                geometry_name,
                physics_tag,
                domain_selection,
            )
        except Exception as e:
            return {"success": False, "error": f"Failed to add Laminar Flow: {str(e)}"}
    
    @mcp.tool()
    def physics_configure_boundary(
        physics_name: Optional[str] = None,
        boundary_condition: str = "",
        boundary_selection: Sequence[int] = (),
        properties: Optional[dict] = None,
        physics_tag: Optional[str] = None,
        component_name: Optional[str] = None,
        feature_tag: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Configure a boundary condition for a physics interface.
        
        Common boundary conditions for Electrostatics:
        - "Ground": Zero potential boundary
        - "ElectricPotential": Specified voltage
        - "SurfaceChargeDensity": Surface charge
        - "ZeroCharge": Zero normal displacement field
        
        Common for Solid Mechanics:
        - "Fixed": Fixed constraint
        - "Roller": Roller constraint
        - "Symmetry": Symmetry plane
        - "BoundaryLoad": Applied force/pressure
        
        Common for Heat Transfer:
        - "Temperature": Fixed temperature
        - "HeatFlux": Heat flux boundary
        - "ConvectiveHeatFlux": Convection cooling
        - "Symmetry": Symmetry (adiabatic)
        
        Args:
            physics_name: Physics interface tag or label (legacy)
            boundary_condition: Type of boundary condition
            boundary_selection: Boundary/edge numbers to apply condition to
            properties: Dictionary of property names and values
            physics_tag: Physics interface tag (preferred)
            component_name: Component tag to search within
            feature_tag: Boundary condition feature tag
            model_name: Model name (default: current model)
        
        Returns:
            Created boundary condition info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            comp, physics_node, error = _resolve_physics_interface(
                model,
                physics_tag=physics_tag,
                physics_name=physics_name,
                component_name=component_name,
            )
            if error:
                return error

            bc_tag = feature_tag or _next_feature_tag(
                physics_node,
                boundary_condition[:3].lower(),
            )
            bc_node = physics_node.create(bc_tag, boundary_condition)
            bc_node.selection().set([int(b) for b in boundary_selection])

            if properties:
                for prop_name, prop_value in properties.items():
                    try:
                        bc_node.set(prop_name, prop_value)
                    except Exception:
                        pass
            
            return {
                "success": True,
                "model": model.name(),
                "component": str(comp.tag()),
                "boundary_condition": {
                    "tag": str(bc_node.tag()),
                    "label": _java_node_label(bc_node),
                    "type": boundary_condition,
                    "physics": str(physics_node.tag()),
                    "selection": list(boundary_selection),
                    "properties": properties,
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to configure boundary: {str(e)}"}

    @mcp.tool()
    def material_create_basic(
        component_name: str = "comp1",
        material_tag: str = "mat1",
        label: str = "Material",
        properties: Optional[dict] = None,
        domain_selection: Optional[Sequence[int]] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Create or update a basic material under a component.

        Args:
            component_name: Component tag (default: comp1)
            material_tag: Material tag (default: mat1)
            label: Material label
            properties: PropertyGroup('def') properties to set
            domain_selection: Domain numbers to assign (default: all domains)
            model_name: Model name (default: current model)

        Returns:
            Created or updated material information
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        try:
            jm = model.java
            comp, error = _get_component_by_tag(jm, component_name)
            if error:
                return error

            existing = _java_tags(comp.material())
            if material_tag in existing:
                material = comp.material(material_tag)
                created = False
            else:
                material = comp.material().create(material_tag, "Common")
                created = True

            material.label(label)
            if domain_selection is not None:
                material.selection().set([int(domain) for domain in domain_selection])

            applied = {}
            for prop_name, prop_value in (properties or {}).items():
                try:
                    material.propertyGroup("def").set(prop_name, prop_value)
                    applied[prop_name] = prop_value
                except Exception:
                    applied[prop_name] = {
                        "value": prop_value,
                        "error": "Failed to set property",
                    }

            return {
                "success": True,
                "model": model.name(),
                "component": str(comp.tag()),
                "material": {
                    "tag": str(material.tag()),
                    "label": _java_node_label(material),
                    "created": created,
                    "domain_selection": list(domain_selection) if domain_selection else None,
                    "properties": applied,
                },
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create material: {str(e)}"}
    
    @mcp.tool()
    def physics_set_material(
        physics_name: str,
        material_name: str,
        domain_selection: Optional[Sequence[int]] = None,
        component_name: str = "comp1",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Assign a material to physics domains.
        
        Args:
            physics_name: Name of the physics interface
            material_name: Name of the material to assign
            domain_selection: Domain numbers (default: all domains for this physics)
            component_name: Component tag (default: comp1)
            model_name: Model name (default: current model)
        
        Returns:
            Assignment confirmation
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            jm = model.java
            comp, error = _get_component_by_tag(jm, component_name)
            if error:
                return error

            material_tags = _java_tags(comp.material())
            if material_name not in material_tags:
                return {
                    "success": False,
                    "error": f"Material tag not found in component '{component_name}': {material_name}",
                    "available": _available_context(jm),
                }

            material = comp.material(material_name)
            if domain_selection is not None:
                material.selection().set([int(domain) for domain in domain_selection])

            _, physics, error = _resolve_physics_interface(
                model,
                physics_name=physics_name,
                component_name=component_name,
            )
            if error:
                return error

            return {
                "success": True,
                "model": model.name(),
                "component": component_name,
                "physics": str(physics.tag()),
                "material": {
                    "tag": str(material.tag()),
                    "label": _java_node_label(material),
                    "domain_selection": list(domain_selection) if domain_selection else None,
                },
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to set material: {str(e)}"}
    
    @mcp.tool()
    def multiphysics_add(
        coupling_type: str,
        physics_list: Sequence[str],
        model_name: Optional[str] = None
    ) -> dict:
        """
        Add a multiphysics coupling between physics interfaces.
        
        Common coupling types:
        - "ThermalStress": Couples Heat Transfer and Solid Mechanics
        - "FluidStructureInteraction": Couples Fluid Flow and Solid Mechanics
        - "ElectromechanicalForces": Couples Electrostatics and Solid Mechanics
        - "JouleHeating": Couples Electric Currents and Heat Transfer
        
        Args:
            coupling_type: Type of multiphysics coupling
            physics_list: Names of physics interfaces to couple
            model_name: Model name (default: current model)
        
        Returns:
            Created coupling info
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            coupling_node = model.create("multiphysics", coupling_type)
            
            return {
                "success": True,
                "coupling": {
                    "name": coupling_node.name() if hasattr(coupling_node, 'name') else coupling_type,
                    "type": coupling_type,
                    "physics": list(physics_list),
                }
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to add multiphysics: {str(e)}"}
    
    @mcp.tool()
    def physics_list_features(
        physics_name: Optional[str] = None,
        physics_tag: Optional[str] = None,
        component_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        List all features (boundary conditions, domain settings) in a physics interface.
        
        Args:
            physics_name: Physics interface tag or label (legacy)
            physics_tag: Physics interface tag (preferred)
            component_name: Optional component tag to search within
            model_name: Model name (default: current model)
        
        Returns:
            List of physics features
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            comp, physics_node, error = _resolve_physics_interface(
                model,
                physics_tag=physics_tag,
                physics_name=physics_name,
                component_name=component_name,
            )
            if error:
                return error

            features = []
            for child in physics_node.feature():
                feat_info = {
                    "tag": str(child.tag()),
                    "label": _java_node_label(child),
                }
                try:
                    feat_info["type"] = str(child.getType())
                except Exception:
                    try:
                        feat_info["type"] = str(child.type())
                    except Exception:
                        feat_info["type"] = "unknown"
                features.append(feat_info)
            
            return {
                "success": True,
                "component": str(comp.tag()),
                "physics": {
                    "tag": str(physics_node.tag()),
                    "label": _java_node_label(physics_node),
                },
                "features": features,
                "count": len(features),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to list features: {str(e)}"}
    
    @mcp.tool()
    def physics_remove(
        physics_name: str,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Remove a physics interface from the model.
        
        Args:
            physics_name: Name of the physics interface to remove
            model_name: Model name (default: current model)
        
        Returns:
            Removal confirmation
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            physics_interfaces = model.physics()
            if physics_name not in physics_interfaces:
                return {"success": False, "error": f"Physics interface not found: {physics_name}"}
            
            physics_node = model / "physics" / physics_name
            model.remove(physics_node)
            
            return {
                "success": True,
                "removed": physics_name,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to remove physics: {str(e)}"}
    
    @mcp.tool()
    def geometry_get_boundaries(
        geometry_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Get all boundaries from a geometry with their properties.
        
        Use this to identify which boundary numbers correspond to which faces
        before setting boundary conditions.
        
        Args:
            geometry_name: Geometry sequence name (default: first geometry)
            model_name: Model name (default: current model)
        
        Returns:
            List of boundaries with their numbers and areas
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            geometries = model.geometries()
            if not geometries:
                return {"success": False, "error": "No geometries found"}
            
            probe = _probe_geometry_entities(model, geometry_name)
            if not probe.get("success"):
                return probe

            counts = probe["counts"]
            
            return {
                "success": True,
                "geometry": probe["geometry"],
                "total_boundaries": counts.get("boundaries"),
                "total_domains": counts.get("domains"),
                "total_edges": counts.get("edges"),
                "total_vertices": counts.get("vertices"),
                "entities_by_dimension": counts.get("entities_by_dimension"),
                "boundaries": probe["boundaries"],
                "diagnostics": probe["diagnostics"],
                "hint": "Use boundary_number to set boundary conditions with physics_configure_boundary",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to get boundaries: {str(e)}"}

    @mcp.tool()
    def java_introspect_model(
        target: str = "model",
        model_name: Optional[str] = None,
        method_limit: int = 120
    ) -> dict:
        """
        Introspect a COMSOL Java API object in the active model.

        Args:
            target: model, component:<tag>, geometry:<tag>, physics:<tag-or-label>, or study:<tag>
            model_name: Model name (default: current model)
            method_limit: Maximum number of method names to return

        Returns:
            Java class name and public method name summary
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            obj, resolved_target = _resolve_java_target(model, target)
            return {
                "success": True,
                "target": resolved_target,
                "java_class": _java_class_name(obj),
                "methods": _java_method_names(obj, method_limit),
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to introspect target: {str(e)}"}

    @mcp.tool()
    def geometry_probe_entities(
        geometry_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Probe geometry entity counts and Java diagnostics.

        Args:
            geometry_name: Geometry sequence name (default: first geometry)
            model_name: Model name (default: current model)

        Returns:
            Domains, boundaries, edges, vertices, and diagnostic details
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            return _probe_geometry_entities(model, geometry_name)
        except Exception as e:
            return {"success": False, "error": f"Failed to probe geometry entities: {str(e)}"}
    
    @mcp.tool()
    def physics_interactive_setup_flow(
        physics_name: str = "Laminar Flow",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Interactive setup wizard for Laminar Flow boundary conditions.
        
        This tool helps identify and configure flow boundary conditions:
        1. Lists all available boundaries
        2. Prompts user to select inlet, outlet, and wall boundaries
        3. Configures appropriate boundary conditions
        
        Args:
            physics_name: Name of the Laminar Flow physics interface
            model_name: Model name (default: current model)
        
        Returns:
            Boundary information and setup instructions
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            # Get geometry boundaries
            boundaries_info = geometry_get_boundaries(None, model_name)
            if not boundaries_info.get("success"):
                return boundaries_info
            
            return {
                "success": True,
                "message": "Interactive Flow Setup - Please specify boundaries",
                "available_boundaries": boundaries_info["total_boundaries"],
                "boundaries": boundaries_info["boundaries"],
                "setup_instructions": {
                    "step1": "Identify which boundary numbers are INLETS (flow enters)",
                    "step2": "Identify which boundary numbers are OUTLETS (flow exits)",
                    "step3": "Use physics_configure_boundary to set conditions",
                },
                "boundary_condition_types": {
                    "InletBoundary": "Set inlet velocity (U0 parameter)",
                    "OutletBoundary": "Set outlet pressure (p0 parameter, default 0)",
                    "Wall": "No-slip wall (default for unspecified boundaries)",
                    "Symmetry": "Symmetry plane",
                },
                "example_usage": {
                    "inlet": "physics_configure_boundary(physics_name='Laminar Flow', boundary_condition='InletBoundary', boundary_selection=[1, 2], properties={'U0': '1[mm/s]'})",
                    "outlet": "physics_configure_boundary(physics_name='Laminar Flow', boundary_condition='OutletBoundary', boundary_selection=[3])",
                },
                "next_step": "Please tell me which boundary numbers to use for inlet(s) and outlet(s)",
            }
        except Exception as e:
            return {"success": False, "error": f"Interactive setup failed: {str(e)}"}
    
    @mcp.tool()
    def physics_setup_flow_boundaries(
        physics_name: Optional[str] = None,
        inlet_boundaries: Sequence[int] = (),
        outlet_boundaries: Sequence[int] = (),
        inlet_velocity: str = "1[mm/s]",
        outlet_pressure: str = "0",
        physics_tag: Optional[str] = "spf",
        component_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Setup Laminar Flow boundary conditions with specified boundaries.
        
        This tool configures inlet velocity and outlet pressure boundary conditions
        for a fluid flow simulation.
        
        Args:
            physics_name: Name of the Laminar Flow physics interface
            inlet_boundaries: List of boundary numbers for inlets
            outlet_boundaries: List of boundary numbers for outlets
            inlet_velocity: Inlet velocity expression (default: "1[mm/s]")
            outlet_pressure: Outlet pressure expression (default: "0")
            physics_tag: Physics interface tag (preferred, default searches by name)
            component_name: Component tag to search within
            model_name: Model name (default: current model)
        
        Returns:
            Configuration confirmation
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            comp, physics, error = _resolve_physics_interface(
                model,
                physics_tag=physics_tag,
                physics_name=physics_name,
                component_name=component_name,
            )
            if error:
                return error
            
            results = {"inlets": [], "outlets": []}
            
            # Add inlet boundary conditions
            for i, boundary in enumerate(inlet_boundaries):
                inlet_tag = f'inl{i+1}'
                inlet = physics.create(inlet_tag, 'InletBoundary')
                inlet.selection().set([int(boundary)])
                inlet.set('U0in', inlet_velocity)
                inlet.label(f'Inlet {i+1} (Boundary {boundary})')
                results["inlets"].append({
                    "tag": inlet_tag,
                    "boundary": boundary,
                    "velocity": inlet_velocity
                })
            
            # Add outlet boundary conditions
            for i, boundary in enumerate(outlet_boundaries):
                outlet_tag = f'out{i+1}'
                outlet = physics.create(outlet_tag, 'OutletBoundary')
                outlet.selection().set([int(boundary)])
                outlet.set('p0', outlet_pressure)
                outlet.label(f'Outlet {i+1} (Boundary {boundary})')
                results["outlets"].append({
                    "tag": outlet_tag,
                    "boundary": boundary,
                    "pressure": outlet_pressure
                })
            
            return {
                "success": True,
                "model": model.name(),
                "component": str(comp.tag()),
                "physics": str(physics.tag()),
                "configured_boundaries": results,
                "inlet_velocity": inlet_velocity,
                "outlet_pressure": outlet_pressure,
                "message": f"Configured {len(inlet_boundaries)} inlet(s) and {len(outlet_boundaries)} outlet(s)",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to setup boundaries: {str(e)}"}

    @mcp.tool()
    def physics_interactive_setup_heat(
        physics_name: str = "Heat Transfer in Solids",
        model_name: Optional[str] = None
    ) -> dict:
        """
        Interactive setup wizard for Heat Transfer boundary conditions.
        
        This tool helps identify and configure thermal boundary conditions:
        1. Lists all available boundaries
        2. Shows typical boundary condition types for thermal analysis
        3. Provides setup instructions
        
        Args:
            physics_name: Name of the Heat Transfer physics interface
            model_name: Model name (default: current model)
        
        Returns:
            Boundary information and setup instructions
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            boundaries_info = geometry_get_boundaries(None, model_name)
            if not boundaries_info.get("success"):
                return boundaries_info
            
            return {
                "success": True,
                "message": "Interactive Heat Transfer Setup",
                "available_boundaries": boundaries_info["total_boundaries"],
                "boundaries": boundaries_info["boundaries"],
                "boundary_condition_types": {
                    "TemperatureBoundary": "Fixed temperature (heat sink/source)",
                    "HeatFluxBoundary": "Prescribed heat flux (heat source)",
                    "ConvectiveHeatFlux": "Convection cooling/heating",
                    "Symmetry": "Symmetry plane (adiabatic)",
                    "ThermalInsulation": "Thermal insulation (default)"
                },
                "typical_setup": {
                    "heat_source": "Use HeatFluxBoundary with q0 parameter (W/m^2)",
                    "heat_sink": "Use TemperatureBoundary with T0 parameter (K or degC)",
                    "convection": "Use ConvectiveHeatFlux with h and Text parameters"
                },
                "example_usage": {
                    "heat_source": "physics_setup_heat_boundaries(physics_name='Heat Transfer in Solids', heat_flux_boundaries=[1, 2], heat_flux_value='1e6[W/m^2]')",
                    "heat_sink": "physics_setup_heat_boundaries(physics_name='Heat Transfer in Solids', temperature_boundaries=[3], temperature_value='293.15[K]')"
                },
                "next_step": "Tell me which boundary numbers to use for heat source and heat sink",
            }
        except Exception as e:
            return {"success": False, "error": f"Interactive setup failed: {str(e)}"}

    @mcp.tool()
    def physics_setup_heat_boundaries(
        physics_name: Optional[str] = None,
        heat_flux_boundaries: Sequence[int] = [],
        temperature_boundaries: Sequence[int] = [],
        convection_boundaries: Sequence[int] = [],
        heat_flux_value: str = "1e6[W/m^2]",
        temperature_value: str = "293.15[K]",
        convection_coeff: str = "10[W/(m^2*K)]",
        ambient_temp: str = "293.15[K]",
        physics_tag: Optional[str] = "ht",
        component_name: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Setup Heat Transfer boundary conditions with specified boundaries.
        
        This tool configures thermal boundary conditions for heat transfer simulation:
        - Heat flux boundaries (heat sources)
        - Temperature boundaries (heat sinks)
        - Convective cooling/heating boundaries
        
        Args:
            physics_name: Name of the Heat Transfer physics interface
            heat_flux_boundaries: List of boundary numbers for heat flux
            temperature_boundaries: List of boundary numbers for fixed temperature
            convection_boundaries: List of boundary numbers for convection
            heat_flux_value: Heat flux value (default: "1e6[W/m^2]")
            temperature_value: Temperature value (default: "293.15[K]" = 20°C)
            convection_coeff: Convection coefficient (default: "10[W/(m^2*K)]")
            ambient_temp: Ambient temperature for convection (default: "293.15[K]")
            model_name: Model name (default: current model)
        
        Returns:
            Configuration confirmation
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        
        try:
            comp, physics, error = _resolve_physics_interface(
                model,
                physics_tag=physics_tag,
                physics_name=physics_name,
                component_name=component_name,
            )
            if error:
                return error
            
            results = {"heat_flux": [], "temperature": [], "convection": []}
            
            # Add heat flux boundaries (heat sources)
            for i, boundary in enumerate(heat_flux_boundaries):
                tag = f'hf{i+1}'
                bc = physics.create(tag, 'HeatFluxBoundary')
                bc.selection().set([int(boundary)])
                bc.set('q0', heat_flux_value)
                bc.label(f'Heat Flux {i+1} (Boundary {boundary})')
                results["heat_flux"].append({
                    "tag": tag,
                    "boundary": boundary,
                    "heat_flux": heat_flux_value
                })
            
            # Add temperature boundaries (heat sinks)
            for i, boundary in enumerate(temperature_boundaries):
                tag = f'temp{i+1}'
                bc = physics.create(tag, 'TemperatureBoundary')
                bc.selection().set([int(boundary)])
                bc.set('T0', temperature_value)
                bc.label(f'Temperature {i+1} (Boundary {boundary})')
                results["temperature"].append({
                    "tag": tag,
                    "boundary": boundary,
                    "temperature": temperature_value
                })
            
            # Add convection boundaries
            for i, boundary in enumerate(convection_boundaries):
                tag = f'conv{i+1}'
                bc = physics.create(tag, 'ConvectiveHeatFlux')
                bc.selection().set([int(boundary)])
                bc.set('h', convection_coeff)
                bc.set('Text', ambient_temp)
                bc.label(f'Convection {i+1} (Boundary {boundary})')
                results["convection"].append({
                    "tag": tag,
                    "boundary": boundary,
                    "h": convection_coeff,
                    "T_amb": ambient_temp
                })
            
            return {
                "success": True,
                "model": model.name(),
                "component": str(comp.tag()),
                "physics": str(physics.tag()),
                "configured_boundaries": results,
                "summary": {
                    "heat_flux_boundaries": len(heat_flux_boundaries),
                    "temperature_boundaries": len(temperature_boundaries),
                    "convection_boundaries": len(convection_boundaries)
                },
                "message": f"Configured {len(heat_flux_boundaries)} heat flux, {len(temperature_boundaries)} temperature, and {len(convection_boundaries)} convection boundaries",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to setup heat boundaries: {str(e)}"}

    @mcp.tool()
    def physics_recommend_boundary_plan(
        physics_tag: str,
        intent: Optional[dict] = None,
        component_name: str = "comp1",
        geometry_name: str = "geom1",
        topology: Optional[dict] = None,
        semantics: Optional[dict] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Recommend a non-mutating boundary condition plan.

        The returned BoundaryPlan is not applied to COMSOL. Validate it with
        physics_validate_boundary_plan before calling physics_apply_boundary_plan.
        """
        model = session_manager.get_model(model_name)
        if model is None and topology is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            resolved_intent = dict(intent or {})
            resolved_intent.setdefault("component", component_name)
            resolved_intent.setdefault("geometry", geometry_name)
            if topology is None:
                topology = _analyze_geometry_topology(model, geometry_name, component_name)
                if not topology.get("success"):
                    return topology
            if semantics is None:
                semantics = classify_semantics(topology)

            plan = recommend_boundary_plan(physics_tag, resolved_intent, topology, semantics)
            validation = validate_boundary_plan(plan, topology)
            plan["validation"] = validation
            plan["requires_user_confirmation"] = validation["status"] == "needs_confirmation"
            return {"success": True, "plan": plan, "semantics_summary": semantics.get("summary", {})}
        except Exception as e:
            return {"success": False, "error": f"Failed to recommend boundary plan: {str(e)}"}

    @mcp.tool()
    def physics_validate_boundary_plan(
        plan: dict,
        topology: Optional[dict] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Validate a BoundaryPlan without modifying COMSOL.

        Returns status valid, needs_confirmation, or invalid plus errors and warnings.
        """
        model = session_manager.get_model(model_name)
        if topology is None and model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            if topology is None:
                topology = _topology_for_plan(model, plan)
                if not topology.get("success"):
                    return topology
            validation = validate_boundary_plan(plan, topology)
            return {"success": True, "validation": validation}
        except Exception as e:
            return {"success": False, "error": f"Failed to validate boundary plan: {str(e)}"}

    @mcp.tool()
    def physics_apply_boundary_plan(
        plan: dict,
        topology: Optional[dict] = None,
        require_valid: bool = True,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Apply a validated BoundaryPlan to a COMSOL physics interface.

        By default, invalid or confirmation-required plans are rejected.
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }

        try:
            if topology is None:
                topology = _topology_for_plan(model, plan)
                if not topology.get("success"):
                    return topology
            validation = validate_boundary_plan(plan, topology)
            if require_valid and validation.get("status") != "valid":
                return {
                    "success": False,
                    "error": "Boundary plan is not valid.",
                    "validation": validation,
                }

            comp, physics, error = _resolve_physics_interface(
                model,
                physics_tag=plan.get("physics_tag"),
                component_name=plan.get("component"),
            )
            if error:
                return error

            applied = []
            for feature in plan.get("features", []):
                applied.append(_create_boundary_feature(physics, feature))

            return {
                "success": True,
                "model": model.name(),
                "component": str(comp.tag()),
                "physics": str(physics.tag()),
                "applied": applied,
                "validation": validation,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to apply boundary plan: {str(e)}"}

    @mcp.tool()
    def physics_boundary_selection(
        physics_name: Optional[str] = None,
        boundary_condition_type: str = "",
        boundary_numbers: Sequence[int] = (),
        properties: dict = {},
        physics_tag: Optional[str] = None,
        component_name: Optional[str] = None,
        feature_tag: Optional[str] = None,
        model_name: Optional[str] = None
    ) -> dict:
        """
        Generic boundary condition setup with boundary selection.
        
        Use this tool to configure any boundary condition by specifying:
        1. The physics interface name
        2. The boundary condition type
        3. The boundary numbers to apply the condition to
        4. Properties specific to the boundary condition
        
        Common boundary condition types by physics:
        
        Heat Transfer (ht):
        - TemperatureBoundary: Set T0 (temperature)
        - HeatFluxBoundary: Set q0 (heat flux)
        - ConvectiveHeatFlux: Set h (coefficient), Text (ambient temp)
        
        Laminar Flow (spf):
        - InletBoundary: Set U0 (velocity)
        - OutletBoundary: Set p0 (pressure)
        - Wall: No-slip wall
        
        Solid Mechanics (solid):
        - Fixed: Fixed constraint
        - BoundaryLoad: Set Fx, Fy, Fz or FAx, FAy, FAz
        
        Args:
            physics_name: Name of the physics interface
            boundary_condition_type: Type of boundary condition
            boundary_numbers: List of boundary numbers
            properties: Dictionary of property names and values
            model_name: Model name (default: current model)
        
        Returns:
            Configuration confirmation
        """
        model = session_manager.get_model(model_name)
        if model is None:
            return {
                "success": False,
                "error": f"Model not found: {model_name or 'no current model'}"
            }
        if not boundary_condition_type:
            return {"success": False, "error": "boundary_condition_type is required."}
        if not boundary_numbers:
            return {"success": False, "error": "boundary_numbers is required."}
        
        try:
            comp, physics, error = _resolve_physics_interface(
                model,
                physics_tag=physics_tag,
                physics_name=physics_name,
                component_name=component_name,
            )
            if error:
                return error

            tag = feature_tag or _next_feature_tag(physics, "bc")
            bc = physics.create(tag, boundary_condition_type)
            bc.selection().set([int(b) for b in boundary_numbers])
            
            # Set properties
            for prop_name, prop_value in properties.items():
                try:
                    bc.set(prop_name, prop_value)
                except Exception as e:
                    pass  # Property might not exist
            
            bc.label(f'{boundary_condition_type} (Boundaries {list(boundary_numbers)})')
            
            return {
                "success": True,
                "model": model.name(),
                "component": str(comp.tag()),
                "physics": str(physics.tag()),
                "boundary_condition": {
                    "type": boundary_condition_type,
                    "tag": tag,
                    "boundaries": list(boundary_numbers),
                    "properties": properties
                },
                "message": f"Created {boundary_condition_type} on boundaries {list(boundary_numbers)}",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create boundary condition: {str(e)}"}


