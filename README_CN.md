# COMSOL MCP Server

用于通过 AI Agent 自动化 COMSOL Multiphysics 仿真的 MCP 服务器。

English | [中文](README_CN.md)

## Star History

[![GitHub stars](https://img.shields.io/github/stars/wjc9011/COMSOL_Multiphysics_MCP?style=social)](https://github.com/wjc9011/COMSOL_Multiphysics_MCP/stargazers)

[![Star History Chart](https://starchart.cc/wjc9011/COMSOL_Multiphysics_MCP.svg)](https://starchart.cc/wjc9011/COMSOL_Multiphysics_MCP)

## 项目目标

构建一个完整的 COMSOL MCP Server，使 AI Agent（如 Claude、opencode）能够通过 MCP 协议执行多物理场仿真：

1. **模型管理** - 创建、加载、保存、版本控制
2. **几何构建** - 块、圆柱、球体、布尔操作
3. **物理场配置** - 传热、流体流动、静电场、固体力学
4. **网格与求解** - 自动网格、稳态/瞬态研究
5. **结果可视化** - 表达式求值、导出绘图
6. **知识集成** - 内置指南 + PDF 语义搜索

## 环境要求

- **COMSOL Multiphysics**（5.x 或 6.x 版本）
- **Python 3.10+**（不要使用 Windows Store 版本）
- **Java runtime**（MPh/COMSOL 需要）

## 安装

```bash
# Clone repository
git clone https://github.com/Fona1347/wjc9011__comsol-multiphysics-mcp.git
cd wjc9011__comsol-multiphysics-mcp

# Install dependencies
python -m pip install -e .

# Test server
python -m src.server
```

## 构建 PDF 知识库

```bash
# Install additional dependencies
pip install pymupdf chromadb sentence-transformers

# Build knowledge base
python scripts/build_knowledge_base.py

# Check status
python scripts/build_knowledge_base.py --status
```

### PDF 知识库说明

PDF 向量知识库保存在本地 `knowledge_base/` 下，属于可重新生成的缓存，不提交到 Git。

检查知识库状态：

```bash
python scripts/build_knowledge_base.py --status
```

首次使用建议先做小样本构建：

```bash
python scripts/build_knowledge_base.py --limit 2 --rebuild
```

确认成功后，再构建完整 PDF 索引：

```bash
python scripts/build_knowledge_base.py --rebuild
```

状态检查只读取 ChromaDB 元信息，不加载 embedding 模型；只有构建和检索时才会初始化 embedding。

## 使用方法

### 方式 1：配合 opencode 使用

在项目根目录创建 `opencode.json`：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "comsol": {
      "type": "local",
      "command": ["python", "-m", "src.server"],
      "enabled": true,
      "environment": {
        "HF_ENDPOINT": "https://hf-mirror.com"
      },
      "timeout": 30000
    }
  }
}
```

### 方式 2：配合 Claude Desktop 使用

```json
{
  "mcpServers": {
    "comsol": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/comsol-mcp"
    }
  }
}
```

## 代码结构

```
comsol_mcp/
├── opencode.json                    # MCP server config for opencode
├── pyproject.toml                   # Python project config
├── README.md                        # This file
│
├── src/
│   ├── server.py                    # MCP Server entry point
│   ├── tools/
│   │   ├── session.py               # COMSOL session management (start/stop/status)
│   │   ├── model.py                 # Model CRUD + versioning
│   │   ├── parameters.py            # Parameter management + sweeps
│   │   ├── geometry.py              # Geometry creation (block/cylinder/sphere)
│   │   ├── physics.py               # Physics interfaces + boundary conditions
│   │   ├── mesh.py                  # Mesh generation
│   │   ├── study.py                 # Study creation + solving (sync/async)
│   │   └── results.py               # Results evaluation + export
│   ├── resources/
│   │   └── model_resources.py       # MCP resources (model tree, parameters)
│   ├── knowledge/
│   │   ├── embedded.py              # Embedded physics guides + troubleshooting
│   │   ├── retriever.py             # PDF vector search retriever
│   │   └── pdf_processor.py         # PDF chunking + embedding
│   ├── async_handler/
│   │   └── solver.py                # Async solving with progress tracking
│   └── utils/
│       └── versioning.py            # Model version path management
│
├── scripts/
│   └── build_knowledge_base.py      # Build PDF vector database
│
├── client_script/                   # Standalone modeling scripts (examples)
│   ├── create_chip_tsv_final.py     # Example: Chip thermal model
│   ├── create_micromixer_auto.py    # Example: Fluid flow simulation
│   ├── create_chip_thermal*.py      # Various chip thermal variants
│   ├── create_micromixer*.py        # Various micromixer variants
│   ├── visualize_*.py               # Result visualization scripts
│   ├── add_visualization.py         # Add plot groups to model
│   └── test_*.py                    # Integration tests
│
├── comsol_models/                   # Saved models (structured)
│   ├── chip_tsv_thermal/
│   │   ├── chip_tsv_thermal_20260216_*.mph
│   │   └── chip_tsv_thermal_latest.mph
│   └── micromixer/
│       └── micromixer_*.mph
│
└── tests/
    └── test_basic.py                # Unit tests

```

## 可用工具（总计 80+）

### 会话（4）

| Tool                  | Description            |
| --------------------- | ---------------------- |
| `comsol_start`      | 启动本地 COMSOL client |
| `comsol_connect`    | 连接远程 server        |
| `comsol_disconnect` | 清理会话               |
| `comsol_status`     | 获取会话信息           |

### 模型（9）

| Tool                   | Description      |
| ---------------------- | ---------------- |
| `model_load`         | 加载 .mph 文件   |
| `model_create`       | 创建空模型       |
| `model_save`         | 保存到文件       |
| `model_save_version` | 带时间戳保存     |
| `model_list`         | 列出已加载模型   |
| `model_set_current`  | 设置当前活动模型 |
| `model_clone`        | 克隆模型         |
| `model_remove`       | 从内存中移除     |
| `model_inspect`      | 获取模型结构     |

### 参数（5）

| Tool                  | Description    |
| --------------------- | -------------- |
| `param_get`         | 获取参数值     |
| `param_set`         | 设置参数       |
| `param_list`        | 列出所有参数   |
| `param_sweep_setup` | 设置参数化扫描 |
| `param_description` | 获取/设置描述  |

### 几何（14）

| Tool                            | Description   |
| ------------------------------- | ------------- |
| `geometry_list`               | 列出几何序列  |
| `geometry_create`             | 创建几何序列  |
| `geometry_add_feature`        | 添加通用特征  |
| `geometry_add_block`          | 添加矩形块    |
| `geometry_add_cylinder`       | 添加圆柱      |
| `geometry_add_sphere`         | 添加球体      |
| `geometry_add_rectangle`      | 添加 2D 矩形  |
| `geometry_add_circle`         | 添加 2D 圆    |
| `geometry_boolean_union`      | 对对象做并集  |
| `geometry_boolean_difference` | 从对象中相减  |
| `geometry_import`             | 导入 CAD 文件 |
| `geometry_build`              | 构建几何      |
| `geometry_list_features`      | 列出特征      |
| `geometry_get_boundaries`     | 获取边界编号  |

### 物理场（16）

| Tool                               | Description            |
| ---------------------------------- | ---------------------- |
| `physics_list`                   | 列出物理场接口         |
| `physics_get_available`          | 可用物理场类型         |
| `physics_add`                    | 添加通用物理场         |
| `physics_add_electrostatics`     | 添加静电场             |
| `physics_add_solid_mechanics`    | 添加固体力学           |
| `physics_add_heat_transfer`      | 添加传热               |
| `physics_add_laminar_flow`       | 添加层流               |
| `physics_configure_boundary`     | 配置边界条件           |
| `physics_set_material`           | 分配材料               |
| `physics_list_features`          | 列出物理场特征         |
| `physics_remove`                 | 移除物理场             |
| `multiphysics_add`               | 添加耦合               |
| `physics_interactive_setup_heat` | 交互式传热边界条件设置 |
| `physics_setup_heat_boundaries`  | 配置传热边界           |
| `physics_interactive_setup_flow` | 交互式流动边界条件设置 |
| `physics_boundary_selection`     | 通用边界设置           |

### 网格（3）

| Tool            | Description      |
| --------------- | ---------------- |
| `mesh_list`   | 列出网格序列     |
| `mesh_create` | 生成网格         |
| `mesh_info`   | 获取网格统计信息 |

### 研究与求解（8）

| Tool                   | Description |
| ---------------------- | ----------- |
| `study_list`         | 列出研究    |
| `study_solve`        | 同步求解    |
| `study_solve_async`  | 后台求解    |
| `study_get_progress` | 获取进度    |
| `study_cancel`       | 取消求解    |
| `study_wait`         | 等待完成    |
| `solutions_list`     | 列出解      |
| `datasets_list`      | 列出数据集  |

### 结果（9）

| Tool                        | Description  |
| --------------------------- | ------------ |
| `results_evaluate`        | 计算表达式   |
| `results_global_evaluate` | 计算标量     |
| `results_inner_values`    | 获取时间步   |
| `results_outer_values`    | 获取扫描值   |
| `results_export_data`     | 导出数据     |
| `results_export_image`    | 导出绘图图像 |
| `results_exports_list`    | 列出导出节点 |
| `results_plots_list`      | 列出绘图节点 |

### 知识（8）

| Tool                        | Description    |
| --------------------------- | -------------- |
| `docs_get`                | 获取文档       |
| `docs_list`               | 列出可用文档   |
| `physics_get_guide`       | 物理场快速指南 |
| `troubleshoot`            | 故障排查帮助   |
| `modeling_best_practices` | 最佳实践       |
| `pdf_search`              | 搜索 PDF 文档  |
| `pdf_search_status`       | PDF 搜索状态   |
| `pdf_list_modules`        | 列出 PDF 模块  |

## 示例案例

### 案例 1：带 TSV 的芯片热模型

对带有 Through-Silicon Via（TSV，硅通孔）的硅芯片进行 3D 热分析。

**几何**：60×60×5 µm 芯片，5 µm 直径 TSV 孔，10×10 µm 热源

```python
# Key steps:
# 1. Create chip block and TSV cylinder
# 2. Boolean difference (subtract TSV from chip)
# 3. Add Silicon material (k=130 W/m·K)
# 4. Add Heat Transfer physics
# 5. Set heat flux on top, temperature on bottom
# 6. Solve and evaluate temperature distribution
```

**脚本**：`client_script/create_chip_tsv_final.py`

**运行**：

```bash
cd /path/to/comsol-mcp
python client_script/create_chip_tsv_final.py
```

**结果**：在 1 MW/m² 热通量下相对环境温度的升温。

### 案例 2：微混合器流体流动

微流控通道中的 3D 层流仿真。

**几何**：600×100×50 µm 矩形通道

```python
# Key steps:
# 1. Create rectangular channel block
# 2. Add water material (ρ=1000 kg/m³, μ=0.001 Pa·s)
# 3. Add Laminar Flow physics
# 4. Set inlet velocity (1 mm/s), outlet pressure
# 5. Add Transport of Diluted Species for mixing
# 6. Solve and evaluate velocity profile
```

**脚本**：`client_script/create_micromixer_auto.py`

**运行**：

```bash
cd /path/to/comsol-mcp
python client_script/create_micromixer_auto.py
```

**结果**：速度分布、浓度混合剖面。

## 模型版本管理

模型会按结构化路径保存：

```besh
./comsol_models/{model_name}/{model_name}_{timestamp}.mph
./comsol_models/{model_name}/{model_name}_latest.mph
```

示例：

```
./comsol_models/chip_tsv_thermal/chip_tsv_thermal_20260216_140514.mph
./comsol_models/chip_tsv_thermal/chip_tsv_thermal_latest.mph
```

## 关键技术发现

### 1. mph 库 API 模式

```python
# Access Java model via property (not callable)
jm = model.java  # NOT model.java()

# Create component with True flag
comp = jm.component().create('comp1', True)

# Create 3D geometry
geom = comp.geom().create('geom1', 3)

# Create physics with geometry reference
physics = comp.physics().create('spf', 'LaminarFlow', 'geom1')

# Boundary condition with selection
bc = physics.create('inl1', 'InletBoundary')
bc.selection().set([1, 2, 3])
bc.set('U0', '1[mm/s]')
```

### 2. 边界条件属性名

| Physics       | Condition           | Property                         |
| ------------- | ------------------- | -------------------------------- |
| Heat Transfer | HeatFluxBoundary    | `q0`                           |
| Heat Transfer | TemperatureBoundary | `T0`                           |
| Heat Transfer | ConvectiveHeatFlux  | `h`, `Text`                  |
| Laminar Flow  | InletBoundary       | `U0`, `NormalInflowVelocity` |
| Laminar Flow  | OutletBoundary      | `p0`                           |

### 3. Client 会话限制

mph 库会创建单例 COMSOL client。每个 Python 进程中只能存在一个 Client：

```python
# This is handled in session.py - client is kept alive and models are cleared
client.clear()  # Clear models instead of full disconnect
```

### 4. 离线 Embedding 模型

PDF 搜索支持使用本地 HuggingFace 缓存离线运行：

```bash
# Set mirror for China
export HF_ENDPOINT=https://hf-mirror.com
```

## 开发状态

| Phase | Description            | Status      |
| ----- | ---------------------- | ----------- |
| 1     | 基础框架 + 会话 + 模型 | Done        |
| 2     | 参数 + 求解 + 结果     | Done        |
| 3     | 几何 + 物理场 + 网格   | Done        |
| 4     | 内置知识 + 工具文档    | Done        |
| 5     | PDF 向量检索           | Done        |
| 6     | 集成测试               | In Progress |

## 下一步

1. **完成第 6 阶段** - 使用正确边界条件进行完整集成测试
2. **可视化导出** - 从 plot group 生成 PNG 图像
3. **LSP 警告** - 修复 physics.py 中的类型提示
4. **更多示例** - 添加静电场、固体力学案例
5. **错误处理** - 改进错误信息和恢复能力

## 资源

| URI                                  | Description |
| ------------------------------------ | ----------- |
| `comsol://session/info`            | 会话信息    |
| `comsol://model/{name}/tree`       | 模型树结构  |
| `comsol://model/{name}/parameters` | 模型参数    |
| `comsol://model/{name}/physics`    | 物理场接口  |

## 许可证

MIT
