"""Build and solve the micromixer_fixed COMSOL model from the latest partial."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import mph


if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


MODEL_NAME = "micromixer_fixed_single_io_b6"
MODEL_DIR = Path(r"E:\hycodespace\Models\comsol_database\micromixer_fixed")
PARTIAL_FILE = MODEL_DIR / "partial_micromixer_fixed_20260520_225902.mph"


def tags(collection) -> set[str]:
    try:
        return {str(item.tag()) for item in collection}
    except Exception:
        return set()


def set_first_available(node, candidates: list[str], value: str) -> str | None:
    for prop in candidates:
        try:
            node.set(prop, value)
            return prop
        except Exception:
            continue
    return None


def remove_if_exists(collection, tag: str) -> None:
    try:
        if tag in tags(collection):
            collection.remove(tag)
    except Exception:
        pass


def main() -> int:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    version_file = MODEL_DIR / f"{MODEL_NAME}_{timestamp}.mph"
    latest_file = MODEL_DIR / f"{MODEL_NAME}_latest.mph"
    run_log_file = MODEL_DIR / f"complete_run_log_{timestamp}.json"
    error_file = MODEL_DIR / f"complete_error_{timestamp}.json"

    log: dict = {
        "timestamp": timestamp,
        "source_partial": str(PARTIAL_FILE),
        "model_name": MODEL_NAME,
        "steps": [],
        "artifacts": {
            "version_mph": str(version_file),
            "latest_mph": str(latest_file),
            "run_log": str(run_log_file),
            "error_log": str(error_file),
        },
    }

    def heartbeat(step: str) -> None:
        log["current_step"] = step
        log["heartbeat_time"] = datetime.now().isoformat(timespec="seconds")
        run_log_file.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        print(step, flush=True)

    try:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        if not PARTIAL_FILE.exists():
            raise FileNotFoundError(PARTIAL_FILE)

        heartbeat("[1] Starting COMSOL client")
        client = mph.start(cores=4)
        log["steps"].append("comsol_client_started")

        heartbeat(f"[2] Loading partial: {PARTIAL_FILE}")
        model = client.load(str(PARTIAL_FILE))
        jm = model.java
        log["steps"].append("partial_loaded")

        comp = jm.component("comp1")
        geom = comp.geom("geom1")
        geom.run()
        log["geometry"] = {
            "domains": int(geom.getNDomains()),
            "boundaries": int(geom.getNBoundaries()),
            "edges": int(geom.getNEdges()),
            "vertices": int(geom.getNVertices()),
        }
        print(f"    Geometry: {log['geometry']}")

        heartbeat("[3] Creating mesh")
        if "mesh1" not in tags(comp.mesh()):
            mesh = comp.mesh().create("mesh1", "geom1")
        else:
            mesh = comp.mesh("mesh1")
        mesh.autoMeshSize(5)
        mesh.run()
        log["steps"].append("mesh_created")

        heartbeat("[4] Creating water material")
        if "mat1" not in tags(comp.material()):
            mat = comp.material().create("mat1", "Common")
        else:
            mat = comp.material("mat1")
        mat.label("Water")
        mat.propertyGroup("def").set("density", "1000[kg/m^3]")
        mat.propertyGroup("def").set("dynamicviscosity", "0.001[Pa*s]")
        mat.propertyGroup("def").set("relpermeability", "1")
        mat.propertyGroup("def").set("relpermittivity", "80")
        log["steps"].append("water_material_created")

        heartbeat("[5] Creating Laminar Flow physics")
        if "spf" not in tags(comp.physics()):
            spf = comp.physics().create("spf", "LaminarFlow", "geom1")
        else:
            spf = comp.physics("spf")
        spf.label("Laminar Flow")
        log["steps"].append("laminar_flow_created")

        heartbeat("[6] Configuring inlet/outlet boundaries")
        for tag in ("inl1", "inl2", "out1"):
            remove_if_exists(spf.feature(), tag)

        boundary_config = {
            "configuration": "single_inlet_single_outlet_non_adjacent",
            "inlets": [1],
            "outlets": [6],
            "inlet_velocity": "v_in",
            "outlet_pressure": "0",
            "selection_note": "Boundary 1 is the lower left branch end face; boundary 6 is the upper left branch end face. Boundary 2 is a side wall, not an outlet.",
        }
        for index, boundary in enumerate(boundary_config["inlets"], start=1):
            inlet = spf.feature().create(f"inl{index}", "InletBoundary", 2)
            inlet.selection().set([boundary])
            prop = set_first_available(inlet, ["U0in", "U0", "Uav"], "v_in")
            inlet.label(f"Inlet {index} (Boundary {boundary})")
            boundary_config[f"inlet_{index}_property"] = prop

        outlet = spf.feature().create("out1", "OutletBoundary", 2)
        outlet.selection().set(boundary_config["outlets"])
        prop = set_first_available(outlet, ["p0"], "0")
        outlet.label("Outlet (Boundary 6)")
        boundary_config["outlet_property"] = prop
        log["boundary_config"] = boundary_config
        log["steps"].append("flow_boundaries_configured")

        heartbeat("[7] Creating stationary study")
        if "std1" not in tags(jm.study()):
            study = jm.study().create("std1")
        else:
            study = jm.study("std1")
        if "stat" not in tags(study.feature()):
            study.feature().create("stat", "Stationary")
        log["steps"].append("stationary_study_created")

        heartbeat("[8] Solving stationary study")
        study.run()
        log["steps"].append("stationary_study_solved")

        heartbeat("[9] Creating default velocity and pressure plots")
        result = jm.result()
        for tag in ("pg_vel", "pg_pres"):
            remove_if_exists(result, tag)

        pg_vel = result.create("pg_vel", "PlotGroup3D")
        pg_vel.label("Laminar Flow - Velocity")
        surf_vel = pg_vel.feature().create("surf1", "Surface")
        surf_vel.set("expr", "spf.U")
        surf_vel.set("descr", "Velocity magnitude")
        pg_vel.run()

        pg_pres = result.create("pg_pres", "PlotGroup3D")
        pg_pres.label("Laminar Flow - Pressure")
        surf_pres = pg_pres.feature().create("surf1", "Surface")
        surf_pres.set("expr", "p")
        surf_pres.set("descr", "Pressure")
        pg_pres.run()
        log["steps"].append("velocity_pressure_plots_created")
        log["plots"] = ["pg_vel", "pg_pres"]

        heartbeat("[10] Evaluating velocity and pressure")
        evaluations = {}
        for expr, unit in (("spf.U", "m/s"), ("p", "Pa")):
            try:
                values = model.evaluate(expr, unit=unit)
                evaluations[expr] = {
                    "unit": unit,
                    "min": float(values.min()),
                    "max": float(values.max()),
                    "mean": float(values.mean()),
                    "count": int(values.size),
                }
            except Exception as exc:
                evaluations[expr] = {"unit": unit, "error": str(exc)}
        log["evaluations"] = evaluations

        heartbeat("[11] Saving model")
        model.save(str(version_file))
        model.save(str(latest_file))
        log["status"] = "success"
        log["steps"].append("model_saved")

        run_log_file.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        if error_file.exists():
            error_file.unlink()
        print(json.dumps(log, ensure_ascii=False, indent=2))

        client.clear()
        return 0

    except Exception as exc:
        log["status"] = "failed"
        log["error"] = str(exc)
        error_file.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        run_log_file.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(log, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
