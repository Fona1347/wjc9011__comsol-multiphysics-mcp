TL;DR：本次会话围绕“让 COMSOL MCP 具备通用几何认知与边界条件设置逻辑”完成了方案审查、topology 能力落地、边界条件计划机制、正方体验收案例，以及对 Codex 沙盒中 COMSOL 启动失败问题的诊断与防卡死处理。核心变化是：MCP 不再只给 AI 一个边界编号列表，而是提供结构化 `GeometryGraph`、语义候选 `SemanticCandidate`、可校验 `BoundaryPlan`，让 AI 基于 COMSOL 几何事实推理边界条件。

# Topology Geometry Cognition and Boundary Plan Changelog

Date: 2026-05-25

Repository: `E:\hycodespace\Forks\COMSOL_Multiphysics_MCP`

Related goal:

```text
AI 构建 COMSOL MCP，能够在三维仿真中具备通用几何认知，与边界条件设置逻辑。
```

## 1. 背景与目标

用户提出的核心目标是：让 AI/MCP 在 COMSOL 三维建模和仿真中理解空间几何实体，而不是依靠人工观察或猜测边界编号设置边界条件。

需要认知的 COMSOL 几何语义包括：

- `domain=3`：由多个 boundary 包围的三维空间/域。
- `boundary/face=2`：由多条 edge 围合的面。
- `edge=1`：由 vertex 连接形成的边。
- `vertex=0`：几何顶点。

初始设计判断：

- 不能让 LLM 直接根据文本或截图猜 `boundary_number`。
- 必须先从 COMSOL Java API 中抽取确定性的几何事实。
- AI 的任务应变为：基于结构化几何图和物理场规则生成边界条件计划。
- 边界条件不应立即写入 COMSOL，而应先形成可解释、可验证的 `BoundaryPlan`。

最终采用的核心中间表示：

```text
COMSOL Geometry -> GeometryGraph -> SemanticCandidate -> BoundaryPlan -> Validate -> Apply
```

## 2. 对既有方案的审查结论

会话早期先审查了 repo 和历史测试流程，特别是：

- `README.md` 中的代码结构。
- `src/server.py` 中的 MCP tool 注册方式。
- `src/tools/geometry.py` 中现有几何工具。
- `src/tools/physics.py` 中现有物理场与边界条件工具。
- micromixer 历史报告和测试日志。

当时发现：

- repo 的工具注册结构清晰：`src/server.py` 统一注册 `src/tools/*.py`。
- topology 能力最适合落在 `src/tools/geometry.py`。
- 边界条件计划能力最适合落在 `src/tools/physics.py`。
- 可测试纯逻辑应拆到 `src/tools/topology_utils.py`。
- 旧的 `geometry_get_boundaries` 只返回边界数量和编号，不足以支撑通用几何认知。
- 旧的 `physics_boundary_selection` 中存在错误引用 `inlet_boundaries/outlet_boundaries` 的检查，需要修复。

因此调整后的实现方向是：

- 不新增服务框架。
- 不重做 MCP server 架构。
- 保持现有 tool registration 风格。
- 在现有 geometry/physics 工具层上增加 topology、semantics 和 boundary plan。

## 3. Topology 几何认知实现

新增/确认的核心能力：

- `geometry_analyze_topology`
- `geometry_classify_semantics`
- `unit_cube_topology`

相关实现位置：

- `src/tools/geometry.py`
- `src/tools/topology_utils.py`
- `tests/test_topology_utils.py`

### 3.1 `GeometryGraph`

`geometry_analyze_topology` 的目标是从 COMSOL 几何中构建结构化拓扑图。

它表达的内容包括：

- `entities_by_dimension`
- `counts`
- `vertices`
- `edges`
- `boundaries`
- `domains`
- `diagnostics`

核心实体关系：

```text
domain -> boundaries
boundary -> adjacent_domains
boundary -> edges
boundary -> vertices
edge -> vertices
vertex -> coord
```

这使 MCP 能回答：

- 一个三维域由哪些面包围？
- 一个面属于外表面还是内部界面？
- 一个面由哪些边、哪些顶点构成？
- 一条边连接哪两个顶点？
- 一个边界面位于空间中的哪一侧？

### 3.2 派生几何属性

在 `topology_utils.py` 中新增纯 Python helper，用于从基本拓扑中派生几何认知字段：

- `bbox`
- `centroid`
- `global_bbox`
- `is_exterior`
- `is_interface`
- `position_tags`

`position_tags` 示例：

```text
min_x
max_x
min_y
max_y
min_z
max_z
```

这些标签使 AI 可以表达“左侧面”“右侧面”“顶面”“底面”等空间关系，而不需要依赖 COMSOL 的边界编号顺序。

### 3.3 外边界与内部界面

判定逻辑：

- `adjacent_domains` 长度为 1：`is_exterior=true`
- `adjacent_domains` 长度大于 1：`is_interface=true`

这点对物理边界条件很关键：

- 外边界可以设置 inlet/outlet/wall/temperature/fixed/load。
- 内部界面通常不应被误设为外部 wall。
- 对 micromixer、装配体、多域模型尤其重要。

## 4. 几何语义候选

新增/确认的语义分类能力：

- `geometry_classify_semantics`
- `classify_semantics`

输出形式是语义候选，而不是最终决定：

```text
SemanticCandidate
```

候选标签包括：

- `wall_candidate`
- `inlet_candidate`
- `outlet_candidate`
- `symmetry_candidate`
- `interface_candidate`
- `fixed_support_candidate`
- `load_face_candidate`
- `thermal_boundary_candidate`

每个候选包含：

- `entity_dim`
- `entity_id`
- `label`
- `confidence`
- `evidence`
- `warnings`

设计意图：

- MCP 给出“这个面可能是入口”的可解释理由。
- AI 根据用户意图、物理场类型和候选证据再生成计划。
- 低置信度或多个等价候选时，应请求确认，而不是盲写 COMSOL。

## 5. 边界条件设置逻辑

新增/确认的三步式边界计划：

- `physics_recommend_boundary_plan`
- `physics_validate_boundary_plan`
- `physics_apply_boundary_plan`

相关实现位置：

- `src/tools/physics.py`
- `src/tools/topology_utils.py`

### 5.1 `BoundaryPlan`

边界条件现在先表达为计划：

```text
BoundaryPlan
```

最小结构包括：

- `physics_tag`
- `component`
- `geometry`
- `features`
- `validation`
- `requires_user_confirmation`

每个 feature 包括：

- `feature_tag`
- `type`
- `boundary_ids`
- `properties`
- `reason`
- `confidence`

### 5.2 Laminar Flow 示例逻辑

以 `spf` / Laminar Flow 为例，v1 推荐逻辑是：

- `min_x` 外边界可推荐为 `InletBoundary`
- `max_x` 外边界可推荐为 `OutletBoundary`
- 其他外边界默认推荐为 `Wall`
- 内部 interface 不应被推荐为 wall/inlet/outlet

示例 intent：

```json
{
  "type": "laminar_flow",
  "flow_axis": "x",
  "inlet": "min_x",
  "outlet": "max_x",
  "inlet_velocity": "1[mm/s]",
  "outlet_pressure": "0"
}
```

### 5.3 校验逻辑

`physics_validate_boundary_plan` 检查：

- boundary 编号是否存在。
- 同一个 boundary 是否被多个冲突条件占用。
- 内部 interface 是否被误设为外部边界条件。
- Laminar Flow 是否至少有 inlet 和 outlet。
- Solid Mechanics 是否缺少固定支撑并产生刚体漂移风险。

### 5.4 应用逻辑

`physics_apply_boundary_plan` 默认只应用 `valid` plan。

这避免了：

- LLM 直接写错误边界编号。
- 内部界面被误设为 wall。
- 同一面同时被设为 inlet/outlet/wall。
- 不完整的物理场设置进入 COMSOL 求解阶段才失败。

## 6. 正方体验收案例

新增/确认的验收脚本：

```text
client_script/create_cube_topology_acceptance.py
```

该脚本提供两种模式：

```powershell
.\.venv\python.exe client_script\create_cube_topology_acceptance.py --offline-fixture
.\.venv\python.exe client_script\create_cube_topology_acceptance.py --force-comsol --timeout 300
```

### 6.1 离线 fixture 验收

由于 Codex 沙盒不能可靠启动 COMSOL，新增了 `--offline-fixture`。

它不启动 COMSOL，而是使用 `unit_cube_topology()` 验证 MCP topology 逻辑。

已生成报告：

```text
comsol_models/cube_topology_acceptance/offline_topology_report_20260521_195950.json
```

报告结果：

```json
{
  "acceptance": {
    "passed": true,
    "errors": []
  },
  "counts": {
    "vertices": 8,
    "edges": 12,
    "boundaries": 6,
    "domains": 1
  },
  "global_bbox": {
    "x": [0.0, 1.0],
    "y": [0.0, 1.0],
    "z": [0.0, 1.0]
  }
}
```

### 6.2 正方体验收标准

验收标准：

- `domains = 1`
- `boundaries/faces = 6`
- `edges = 12`
- `vertices = 8`
- 每个 boundary 有 4 条 edge。
- 每个 boundary 有 4 个 vertex。
- 每条 edge 连接 2 个 vertex。
- domain 1 被 6 个 boundary 包围。
- global bbox 为 `[0,0,0]` 到 `[1,1,1]`。
- 6 个面分别对应 `min_x/max_x/min_y/max_y/min_z/max_z`。

特别说明：

COMSOL 的 boundary 编号可能随版本、构造顺序或几何布尔操作变化，因此正方体验收不以具体 boundary number 为准，而以拓扑关系和空间位置为准。

## 7. COMSOL 沙盒执行问题

在测试真实 COMSOL 正方体验收脚本时，最初命令长时间卡住。

首次裸跑命令形态：

```powershell
& '.venv\python.exe' client_script\create_cube_topology_acceptance.py
```

观察结果：

- 命令在 `mph.start()` 阶段卡住。
- 没有生成 cube `.mph`。
- 没有生成成功 topology report。
- stderr 出现 COMSOL Tomcat log 写入权限问题。

相关日志：

```text
dev_log/2026-05-21_cube_topology_acceptance_timeout.md
dev_log/20260521_195204_cube_topology_acceptance_timeout.json
dev_log/20260521_195958_cube_topology_preflight_blocked.json
```

关键报错：

```text
java.io.FileNotFoundException:
C:\Users\Huayun\.comsol\v64\tomcat\logs\mphservercatalina.2026-05-21.log
(拒绝访问。)
```

以及后续 timeout 清理报告：

```json
{
  "cleanup": {
    "command": ["taskkill", "/PID", "...", "/T", "/F"],
    "returncode": 1,
    "stderr": "ERROR: Access denied",
    "communicate_timeout_after_kill": true
  }
}
```

诊断结论：

- 这不是 topology 代码失败。
- 卡点在 COMSOL/MPh 启动阶段。
- Codex 沙盒无法可靠写入 COMSOL user-profile runtime/log 目录。
- Codex 沙盒也不能保证可以清理启动出来的 COMSOL/Java 子进程树。

## 8. 防卡死与预检策略

为避免后续任务再次长时间停滞，验收脚本加入了：

- 父进程级 timeout。
- worker 子进程。
- timeout report。
- dev_log report。
- COMSOL 启动前 preflight。
- `--offline-fixture`。
- `--force-comsol --timeout 300`。

默认模式现在会先做 preflight。

在当前 Codex 沙盒中，preflight 结果为：

```json
{
  "success": false,
  "stage": "preflight_blocked",
  "preflight": {
    "success": false,
    "log_dir": "C:\\Users\\Huayun\\.comsol\\v64\\tomcat\\logs",
    "errors": [
      "Cannot write COMSOL Tomcat log directory before mph.start().",
      "[Errno 13] Permission denied: 'C:\\\\Users\\\\Huayun\\\\.comsol\\\\v64\\\\tomcat\\\\logs\\\\codex_preflight_8956.tmp'"
    ]
  }
}
```

这说明脚本不会再直接进入无保护的 `mph.start()`。

## 9. 后续会话延伸：COMSOL 启动修复

后续会话继续围绕 COMSOL 启动黑盒 timeout 做了 foundation 修复。

相关报告：

```text
dev_log/2026-05-22_comsol_mcp_start_timeout_implementation_report.md
dev_log/2026-05-22_comsol_mcp_start_timeout_followup_report.md
dev_log/2026-05-25_hy_comsol_mcp_foundation_repair.md
```

### 9.1 2026-05-22 启动 timeout 修复

主要变化：

- `comsol_start` 增加 hard timeout。
- 新增 MCP-owned client-server 启动路径。
- 增加 `.comsol_runtime` 重定向。
- 新增 `comsol_startup_preflight`。
- 增加 startup failure category。
- 增加 timeout JSON report。
- 增加 COMSOL server diagnostics。

关键诊断：

- 不重定向用户目录时，COMSOL 卡在 user-profile write permission。
- 重定向 `.comsol_runtime` 后，server 能启动到 port-ready 阶段。
- client-server 模式进一步遇到 COMSOL server login failure。
- stand-alone mode 曾成功启动。

### 9.2 2026-05-25 foundation repair

主要变化：

- 新增 session state：
  - `disconnected`
  - `connected`
  - `model_active`
  - `recoverable_error`
- `comsol_connect` 变为幂等：
  - 重复连接同一 `host:port` 不重复实例化 `mph.Client`
  - 连接不同 server 时返回结构化错误
- 增加 structured tool envelope：
  - `success`
  - `error_code`
  - `message`
  - `session_state`
  - `current_model`
  - `data`
  - `artifacts`
- 新增 `tool_registry_check`
- foundation tests 达到：

```text
31 passed
```

## 10. 验证记录

本轮 topology 相关验证包括：

```powershell
.\.venv\python.exe -m py_compile src\tools\topology_utils.py src\tools\geometry.py src\tools\physics.py client_script\create_cube_topology_acceptance.py tests\test_topology_utils.py
```

结果：

```text
passed
```

纯 Python helper 测试：

```powershell
.\.venv\python.exe -c "from tests.test_topology_utils import test_enrich_cube_topology_invariants,test_classify_cube_semantics,test_recommend_and_validate_laminar_flow_cube_plan,test_validate_rejects_interface_wall_conflict; [f() for f in (test_enrich_cube_topology_invariants,test_classify_cube_semantics,test_recommend_and_validate_laminar_flow_cube_plan,test_validate_rejects_interface_wall_conflict)]; print('topology helper tests passed')"
```

结果：

```text
topology helper tests passed
```

离线正方体验收：

```powershell
.\.venv\python.exe client_script\create_cube_topology_acceptance.py --offline-fixture
```

结果：

```text
Offline acceptance passed.
```

真实 COMSOL 验收：

```powershell
.\.venv\python.exe client_script\create_cube_topology_acceptance.py --force-comsol --timeout 300
```

状态：

```text
Not completed inside Codex sandbox due to COMSOL user-profile write permissions and process-control restrictions.
```

## 11. 对“通用几何认知”的意义

本次 topology 改造让 MCP 的几何理解从“边界编号列表”升级为“空间拓扑图”。

旧能力：

```text
boundaries: [1, 2, 3, ...]
```

新能力：

```text
boundary 1:
  vertices: [...]
  edges: [...]
  adjacent_domains: [...]
  bbox: ...
  centroid: ...
  is_exterior: true/false
  is_interface: true/false
  position_tags: [...]
```

这带来的变化：

- AI 可以知道某个面在哪里。
- AI 可以知道某个面是否属于外表面。
- AI 可以知道某个面是否是两个域之间的内部界面。
- AI 可以把用户意图“左侧入口、右侧出口”映射到 `min_x/max_x`。
- AI 可以在设置边界条件前检查冲突。
- AI 可以在低置信度时说明原因，而不是盲目执行。

## 12. 对“边界条件设置逻辑”的意义

边界条件设置被拆成三步：

```text
Recommend -> Validate -> Apply
```

这比直接调用 `physics_configure_boundary` 更稳：

- 推荐阶段可解释。
- 校验阶段可阻止明显错误。
- 应用阶段只执行已通过的计划。

尤其适合：

- Laminar Flow 的 inlet/outlet/wall。
- Heat Transfer 的 temperature/heat flux/convection。
- Solid Mechanics 的 fixed/load。
- 多域模型中的 interface 排除。

## 13. 当前限制

仍然存在的限制：

- 曲面法向、曲面面积、复杂 CAD 的面分类仍依赖 COMSOL API 能否稳定返回。
- v1 的语义分类是规则型，不是完整 CAD feature recognition。
- Codex 沙盒不适合直接启动 COMSOL server 做真实集成验收。
- 真实 COMSOL 验收需要在普通本机终端或已确认权限的 MCP 环境中运行。

## 14. 推荐后续工作

建议下一阶段继续：

1. 在真实 COMSOL 环境运行：

```powershell
.\.venv\python.exe client_script\create_cube_topology_acceptance.py --force-comsol --timeout 300
```

2. 对 micromixer 已保存 `.mph` 运行 topology/semantics report。

目标检查：

```text
domains = 3
boundaries = 18
edges = 34
vertices = 20
```

3. 加入更多标准几何验收：

- 单长方体
- 两个相连长方体
- 圆柱管道
- 多域装配体

4. 增强 semantics：

- 面法向
- 面面积
- 圆形开口识别
- 对称面对识别
- 命名 selection 读取

5. 将 `BoundaryPlan` 输出格式固定成文档化 schema，便于其他 Agent/LLM 使用。

## 15. 会话脉络摘要

本次会话大致经历：

1. 用户提出：希望 AI 在 COMSOL 三维仿真中具备通用几何认知与边界条件设置逻辑。
2. 先审查 repo、README、历史 micromixer 测试流程。
3. 形成方案：`GeometryGraph + SemanticCandidate + BoundaryPlan`。
4. 在 Plan Mode 下完成可实施计划。
5. 退出 Plan Mode 后按计划实现 topology helper、geometry tools、physics boundary plan tools。
6. 添加正方体验收脚本和纯 Python 测试。
7. 测试真实 COMSOL 验收时发现 `mph.start()` 长时间卡住。
8. 将卡住原因记录到 `dev_log`。
9. 给验收脚本加入 timeout、worker、preflight。
10. 发现 Codex 沙盒无法写 COMSOL Tomcat log 目录。
11. 增加 `--offline-fixture`，在沙盒内验证 topology 逻辑。
12. 离线正方体验收通过。
13. 后续继续修复 COMSOL startup foundation，形成 5/22 与 5/25 的启动、连接、registry、structured envelope 报告。

## 16. 关键文件索引

Topology and boundary-plan implementation:

```text
src/tools/geometry.py
src/tools/topology_utils.py
src/tools/physics.py
tests/test_topology_utils.py
```

Acceptance script:

```text
client_script/create_cube_topology_acceptance.py
```

README updates:

```text
README.md
```

Topology acceptance reports:

```text
comsol_models/cube_topology_acceptance/offline_topology_report_20260521_195950.json
comsol_models/cube_topology_acceptance/timeout_report_20260521_195204.json
comsol_models/cube_topology_acceptance/preflight_blocked_20260521_195958.json
```

Related dev logs:

```text
dev_log/2026-05-21_cube_topology_acceptance_timeout.md
dev_log/20260521_195204_cube_topology_acceptance_timeout.json
dev_log/20260521_195958_cube_topology_preflight_blocked.json
dev_log/2026-05-22_comsol_mcp_start_timeout_implementation_report.md
dev_log/2026-05-22_comsol_mcp_start_timeout_followup_report.md
dev_log/2026-05-25_hy_comsol_mcp_foundation_repair.md
```

## 17. Final Status

Topology 几何认知方案已经具备 v1 可用基础：

- 能表达 COMSOL 几何实体层级。
- 能表达 domain/boundary/edge/vertex 邻接。
- 能识别外边界和内部界面。
- 能用空间位置标签支持入口/出口/壁面推理。
- 能生成、校验、应用边界条件计划。
- 能用正方体 fixture 做确定性验收。

真实 COMSOL 集成验收仍依赖可写用户目录、可用 license/login、以及可控 server 启动环境。当前 Codex 沙盒适合做静态验证、纯 Python topology 验证和 MCP foundation 单元测试；不适合作为唯一的 COMSOL 真实仿真验收环境。
