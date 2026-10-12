# Topology Dimension Profile and Physics Feature Listing Fixes

Date: 2026-05-26

Repository: `E:\hycodespace\Forks\COMSOL_Multiphysics_MCP`

## TL;DR

本次变更是在前一轮 `GeometryGraph + SemanticCandidate + BoundaryPlan` 的基础上继续修复 topology 兼容性：让几何拓扑分析不再默认所有模型都是 3D，增加 1D/2D 坐标归一化、维度画像 `dimension_profile`、COMSOL 几何 API fallback，并修复 `physics_list_features` 对物理场接口和 feature 的解析方式。同时补充了 2D 矩形、1D 线段、Heat Transfer 多温度边界、vertex 坐标 fallback、physics tag/label 解析等测试。

## 1. 背景

上一轮 topology 能力已经可以表达 3D COMSOL 模型中的 domain、boundary、edge、vertex 拓扑关系，并基于 `position_tags` 推荐边界条件计划。但继续测试和审查后发现：

- 旧实现隐含了 3D 假设，例如 boundary 固定按 entity dimension 2 处理。
- 1D/2D 模型的坐标可能只有 `[x]` 或 `[x, y]`，旧的 bbox/centroid 会丢弃不足 3 维的点。
- 不同 COMSOL 几何对象对 vertex 和 entity adjacency 的 Java API 返回方式不完全一致，需要 fallback。
- Heat Transfer 边界计划只能表达单个温度边界，难以直接生成 hot/cold 两端温度条件。
- `physics_list_features` 旧实现依赖 `model / "physics" / physics_name` 和 `children()`，在当前项目中不如统一的 `_resolve_physics_interface` 稳定。

## 2. `topology_utils.py` 变更

核心改动：

- 新增 `normalize_point(point, coordinate_dim=3)`。
- 新增 `normalize_points(points, coordinate_dim=3)`。
- `bbox_from_points()` 和 `centroid_from_points()` 改为接受 1D、2D、3D 坐标，并统一补齐为 3D 表示。
- `boundary_position_tags()` 新增 `axes` 参数，只在当前空间维度对应的轴上判断 `min_x/max_x/...`。
- `enrich_topology()` 读取 `dimension_profile`：
  - `space_dim`
  - `boundary_dim`
  - active axes
- `enrich_topology()` 会归一化 vertex 坐标，并在 boundary 缺少 `adjacent_domains` 时尝试从 domain 的 boundary 列表反推。
- boundary 会写入正确的 `entity_dim`，不再固定为 2。
- `classify_semantics()` 输出候选时使用 topology 的 `boundary_dim`，支持 1D/2D/3D 模型。
- `recommend_boundary_plan()` 在结果中回传 `space_dim` 和 `boundary_dim`，便于调用方判断边界计划适用于几维实体。
- Heat Transfer 推荐逻辑支持 `temperature_boundaries` 列表，可一次生成多个温度边界 feature。

行为影响：

- 1D 线段模型的边界实体可以表示为 `entity_dim=0`。
- 2D 面模型的边界实体可以表示为 `entity_dim=1`。
- 3D 体模型继续保持 boundary/face 为 `entity_dim=2`。
- `min_z/max_z` 不会再被强行用于 1D/2D 模型的边界位置推断。

## 3. `geometry.py` 变更

核心改动：

- 引入 `normalize_point`。
- 新增 `_call_entity_vertices()`，按优先级尝试：
  - adjacency 查询到 vertex。
  - `getStartEnd(entity_dim, entity_id)`。
  - `getStartEnd(entity_id)`。
  - `getVertex(entity_dim, entity_id)`。
- 新增 `_geometry_dimension_profile()`，用于推断几何维度：
  - 优先使用 `geom.getSDim()`。
  - 其次根据 `entities_by_dimension` 中非零维度推断。
  - 最后根据 domains/boundaries/edges 数量兜底。
- 新增 `_get_vertex_coord()`，按优先级尝试：
  - `getVtxCoord(vertex_id)`。
  - `getVertexCoord(vertex_id)`。
  - `getVertex(vertex_id)`。
- 新增 `_entity_count_for_dim()`，根据目标维度读取对应 entity count。
- `_analyze_geometry_topology()` 现在会：
  - 生成并返回 `dimension_profile`。
  - 将 `dimension_profile` 写入 diagnostics。
  - 按 `domain_dim/boundary_dim/edge_dim` 查询实体关系。
  - 对 edge、boundary、domain 写入 `entity_dim`。
  - 在 2D 模型中避免把 boundary 当作 3D face 查询。

行为影响：

- `geometry_analyze_topology` 更接近 COMSOL 的实际维度模型，而不是硬编码 3D。
- 2D 矩形这类模型可以得到 boundary=线、domain=面 的拓扑结构。
- 1D 线模型可以得到 boundary=端点、domain=线 的拓扑语义。
- COMSOL Java API 方法名差异导致的拓扑采集失败概率降低，并会通过 diagnostics 留下成功/失败痕迹。

## 4. `physics.py` 变更

核心改动：

- `physics_list_features()` 参数从只接受 `physics_name` 扩展为：
  - `physics_name`：兼容旧调用，可为 tag 或 label。
  - `physics_tag`：推荐的新参数。
  - `component_name`：限定组件。
  - `model_name`：目标模型。
- 使用 `_resolve_physics_interface()` 统一解析 component 和 physics interface。
- feature 枚举改为 `physics_node.feature()`。
- feature 输出包含：
  - `tag`
  - `label`
  - `type`
- 返回结果包含 component tag 和 physics tag/label，便于调试实际 COMSOL 模型中的 feature 层级。

行为影响：

- 调用者可以用 physics tag 或 label 查找物理场接口。
- 多 component 模型中可以显式指定 `component_name`。
- feature listing 不再依赖旧的路径式 node 访问和 `children()`。

## 5. 测试覆盖

`tests/test_topology_utils.py` 新增/扩展测试：

- `test_normalize_point_and_bbox_accept_1d_2d_3d`
  - 验证 1D/2D/3D 坐标归一化。
  - 验证 bbox/centroid 可以接受低维坐标。
- `test_enrich_rectangle_topology_2d_semantics`
  - 验证 2D 矩形的 global bbox。
  - 验证 4 条线边界分别识别为 `min_y/max_x/max_y/min_x`。
  - 验证 boundary `entity_dim=1`。
- `test_recommend_heat_transfer_rectangle_two_temperature_boundaries`
  - 验证 Heat Transfer 可同时推荐 hot/cold 两个温度边界。
  - 验证 plan 回传 `space_dim=2`、`boundary_dim=1`。
- `test_enrich_line_topology_1d_semantics`
  - 验证 1D 线段端点可识别为 `min_x/max_x`。
  - 验证 boundary `entity_dim=0`。
- `test_geometry_dimension_profile_2d_and_vertex_fallback`
  - 验证 `getSDim()` 推断 2D dimension profile。
  - 验证 `getVtxCoord` 失败时 fallback 到 `getVertexCoord`。
- `test_resolve_physics_interface_by_tag_and_label`
  - 验证 `_resolve_physics_interface` 可通过 tag 和 label 找到物理场接口。

已有 cube topology、Laminar Flow boundary plan、interface wall conflict 测试继续保留，用来防止 3D v1 能力回退。

## 6. 当前 git diff 摘要

```text
src/tools/geometry.py        | 151 ++++++++++++++++++++++++++----
src/tools/physics.py         |  43 ++++++---
src/tools/topology_utils.py  | 107 +++++++++++++++------
tests/test_topology_utils.py | 218 +++++++++++++++++++++++++++++++++++++++++++
```

总计约：

```text
462 insertions, 57 deletions
```

## 7. 验证建议

推荐在提交前运行：

```powershell
.\.venv\python.exe -m pytest tests\test_topology_utils.py
```

本次实际运行结果：

```text
10 passed
```

备注：pytest 尝试写入 `.pytest_cache` 时出现 `WinError 5` 权限警告，但不影响测试通过。

如需只做语法检查：

```powershell
.\.venv\python.exe -m py_compile src\tools\topology_utils.py src\tools\geometry.py src\tools\physics.py tests\test_topology_utils.py
```

## 8. 后续注意

- `dimension_profile` 现在是 topology 语义的重要部分，后续新增 geometry/physics 工具时应继续传递。
- 对 2D/1D 模型，不应再假设 boundary 一定是 face，也不应强制使用 z 轴位置标签。
- Heat Transfer 的 `temperature_boundaries` 当前覆盖了多温度边界场景，后续可继续扩展到 heat flux、convection、radiation 等 feature 类型。
- COMSOL API fallback 虽然提高了兼容性，但真实 COMSOL 版本差异仍应通过 diagnostics 和实际模型验收继续确认。
