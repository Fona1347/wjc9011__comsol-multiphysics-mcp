TL;DR：没有放进初版，不是因为它们不重要，而是因为它们会把“先修到可用”变成“重做一套 RAG 系统”。当前知识库还没稳定构建，`pdf_search_status` 还会超时，仓库里还有被跟踪的 `.pyc` 噪声；先修基础设施更划算。那些增强项应进 **第二阶段**，其中“章节/标题结构切块”我已经保留了轻量版。

逐项解释：

| 改进                | 为什么没放进初版核心                                                                                    | 什么时候做                                                               |
| ------------------- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| 换 BGE/E5 embedding | 换模型意味着必须重建整个 `knowledge_base/`；还要处理模型下载、维度变化、速度、缓存路径、中文/英文权衡 | 等当前库能稳定 build/search 后，用同一批 query 对比质量                  |
| 加 BM25             | 需要新增关键词索引、持久化方式、融合策略，比如 vector score + BM25 score 怎么合并                       | 第二阶段优先做，尤其适合 COMSOL API 名、属性名、错误码                   |
| 加 reranker         | 需要新增 cross-encoder 模型、额外推理时间、失败回退逻辑；MCP 调用可能变慢                               | 等召回质量稳定后再加，否则 rerank 也救不了召回不到的内容                 |
| 按章节/标题结构切块 | 完整结构化切块需要更可靠的 PDF 目录/标题解析；但轻量 metadata 可以先做                                  | 初版做轻量 `chapter` metadata，第二阶段再做真正 section-aware chunking |

我把它们拆开的逻辑是：

```text
第 0/1 阶段：让系统稳定可用
  - status 不超时
  - 小样本能构建
  - pdf_search 能返回
  - .pyc 不污染 git
  - chunk 带基本 chapter metadata

第 2 阶段：提升检索质量
  - BM25
  - reranker
  - 更强 embedding
  - 更好的章节切块

第 3 阶段：平台化/长期维护
  - 可配置模型
  - 增量索引
  - 评测集
  - Docling/Qdrant/LlamaIndex 等替换方案
```

最核心原因：**现在还没有可靠 baseline**。如果还没确认当前 `all-MiniLM + ChromaDB` 对 2 个 PDF 能正常建库和查询，就直接引入 BM25/reranker/BGE，会很难判断问题来自哪里。像调实验一样，先让最小系统跑起来，再逐个加变量，比较稳。

但我同意：如果你的目标是“做一个长期好用的 COMSOL 文档助手”，第二阶段至少应该包含：

1. **BM25 hybrid search**：必要性最高。
2. **reranker**：质量提升明显。
3. **可配置 embedding 模型**：先不默认切换，但允许配置。
4. **section-aware chunking**：比单纯 page sliding window 更适合手册。

可以把修正版计划再升级成“两阶段计划”：第一阶段修稳定性，第二阶段加质量增强。
---

# P0: 合并 Managed 与 Shared COMSOL 会话模式

## TL;DR

下一阶段最高优先级任务是把当前 MCP 的 **managed 自动化模式** 与 `Cowork-COMSOL-Codex` 的 **shared GUI 协作模式** 合并到同一套会话架构中。

核心目标不是替换现有启动方式，而是让 MCP 明确支持两种 profile：

```text
模式 A: managed
MCP 自己启动 comsolmphserver，自己创建/加载模型，断开时负责清理。
适合批处理、无人值守、测试、自动建模。

模式 B: shared
用户或 MCP 启动 comsolmphserver -multi on -port 2037。
GUI 和 MCP 同时连接同一个 COMSOL Server。
MCP 不自动 clear server，不自动 stop 外部 server。
MCP 提供 attach/list existing models 工具，把 GUI 中已有模型纳入管理。
```

当前两套方法不本质冲突，但默认行为不同：当前 repo 偏 managed，`Cowork-COMSOL-Codex` 偏 shared。合并时必须显式区分 server ownership 与 cleanup policy，否则最危险的问题是 MCP 在 shared 会话中误调用 `client.clear()`，导致 GUI/server 中的模型被清空。

## 1. 现状与冲突点

### 当前 MCP managed pipeline

```text
MCP Client
  -> python -m src.server
  -> FastMCP 注册 tools/resources
  -> comsol_start()
  -> SessionManager.start()
  -> ManagedComsolServer 启动 comsolmphserver
  -> mph.Client(port=server.port)
  -> 后续工具通过 SessionManager._models 操作 COMSOL model
```

特点：

- MCP 自己启动 server，默认 `port=0` 让 COMSOL 选择空闲端口。
- MCP 自己维护 `_client`、`_server`、`_models`、`_current_model`。
- `comsol_disconnect()` 会清理 client、models，并停止 MCP-owned server。
- 适合自动化，但不适合 GUI 共享会话直接复用。

### Cowork shared pipeline

```text
start_clientserver.bat
  -> comsolmphserver.exe -multi on -port 2037
  -> COMSOL GUI 连接同一个 server
  -> Codex/Python 用 mph.Client(port=2037)
  -> GUI 与 MCP 共同操作 server 内存中的模型对象
```

特点：

- server 是外部共享资源，通常由用户脚本或 GUI 工作流管理。
- 必须使用 `-multi on`，否则 GUI 与 Python 作为两个 client 会互斥。
- Python 不应随意保存或 clear server 中的模型，避免文件锁和 GUI 状态丢失。
- 需要把 GUI 已打开的模型 attach 到 MCP 的 tracking 表。

### 必须处理的冲突点

| 冲突点 | managed 合理行为 | shared 合理行为 |
|---|---|---|
| server owner | MCP-owned | external 或 shared-owned |
| disconnect | clear models + stop server | detach only |
| port | 可随机 | 通常固定 2037 |
| `-multi on` | 可选 | 必须 |
| model source | MCP create/load | GUI/server 现有模型 |
| save | 可直接保存/版本保存 | 默认避免覆盖 GUI 打开的原文件 |
| cleanup | 自动清理 | 保守，不误伤共享 server |

## 2. P0 设计原则

1. **向后兼容**：现有 `comsol_start()` 默认仍是 managed，不破坏自动化流程。
2. **显式会话模式**：`SessionManager` 必须知道当前是 `managed` 还是 `shared`。
3. **显式 ownership**：区分 `server_owner="mcp"` 与 `server_owner="external"`。
4. **显式 cleanup policy**：shared 默认 `detach_only`，不调用 `client.clear()`。
5. **shared 模式先安全后便利**：默认不覆盖保存，不杀进程，不清空 server。
6. **GUI 模型可挂接**：提供 list/attach 工具，把 server 现有模型纳入 MCP。

## 3. 具体实施计划

### 3.1 SessionManager 状态扩展

在 `src/tools/session.py` 中为 `SessionManager` 增加会话元信息：

```python
_session_mode: str | None      # "managed" | "shared"
_server_owner: str | None      # "mcp" | "external"
_cleanup_policy: str | None    # "clear_and_stop" | "detach_only"
_host: str | None
_port: int | None
_shared: bool
```

并提供内部 helper：

```python
_set_session_metadata(...)
_reset_session_metadata()
_server_visible_models()
```

`comsol_status()` 返回新增字段：

```json
{
  "session_mode": "managed/shared",
  "server_owner": "mcp/external",
  "cleanup_policy": "clear_and_stop/detach_only",
  "tracked_models": [],
  "server_visible_models": []
}
```

### 3.2 保留 managed 默认行为

现有 `comsol_start()` 保持默认 managed：

```python
comsol_start(
    mode="client-server",
    port=0,
    redirect_user_dirs=True,
    login_mode="auto"
)
```

成功后设置：

```python
session_mode = "managed"
server_owner = "mcp"
cleanup_policy = "clear_and_stop"
```

断开时保持当前语义：

```text
client.clear()
client.disconnect()
server.stop()
_models.clear()
```

### 3.3 新增 shared 启动入口

新增 MCP tool：

```python
comsol_start_shared(
    port: int = 2037,
    host: str = "localhost",
    version: str | None = None,
    start_server: bool = False,
    timeout_seconds: int = 120,
    login_mode: str = "auto",
    redirect_user_dirs: bool = True
) -> dict
```

行为分两类：

```text
start_server=False
  -> 连接用户已启动的 comsolmphserver -multi on -port 2037
  -> server_owner="external"
  -> cleanup_policy="detach_only"

start_server=True
  -> MCP 启动 comsolmphserver -multi on -port 2037
  -> server_owner="mcp"
  -> session_mode="shared"
  -> cleanup_policy 默认仍为 detach_only
```

注意：shared/MCP-started server 是否停止，必须交给 `comsol_disconnect(stop_shared_server=True)` 显式控制。

### 3.4 扩展 ManagedComsolServer

给 `ManagedComsolServer` 增加参数：

```python
multi: bool = False
extra_arguments: list[str] | None = None
```

当 `multi=True` 时启动命令必须包含：

```text
-multi on
```

shared 固定端口启动前做端口检查：

```text
如果 2037 已占用：
  - 不盲目启动第二个 server
  - 返回明确提示：端口已占用，可 comsol_connect(shared=True) 或换端口
```

### 3.5 扩展 comsol_connect

修改现有：

```python
comsol_connect(port: int, host: str = "localhost", shared: bool = False)
```

当 `shared=False`：

```text
保持普通外部连接语义。
```

当 `shared=True`：

```python
session_mode = "shared"
server_owner = "external"
cleanup_policy = "detach_only"
```

这会直接兼容 `Cowork-COMSOL-Codex/start_clientserver.bat`。

### 3.6 修改 comsol_disconnect

扩展参数：

```python
comsol_disconnect(
    stop_shared_server: bool = False,
    clear_shared_models: bool = False
) -> dict
```

分支逻辑：

```text
managed:
  clear client models
  disconnect client
  stop MCP-owned server
  clear tracking

shared external:
  默认只 disconnect Python client
  不调用 client.clear()
  不 stop server
  clear MCP tracking only

shared MCP-owned:
  默认 detach only
  如果 stop_shared_server=True，停止 MCP 启动的 shared server
  只有 clear_shared_models=True 时才允许 client.clear()
```

shared 模式下任何 destructive 操作都必须显式 opt-in。

### 3.7 新增 server 模型发现与 attach

新增 MCP tools：

```python
model_list_server() -> dict
```

用途：

- 读取当前 COMSOL server 中可见的模型。
- 不要求这些模型已经被 MCP tracking。
- 优先使用 `client.names()`；如可行，再补充 `client.models()` 元信息。

```python
model_attach_existing(
    name: str | None = None,
    index: int | None = None,
    set_current: bool = True
) -> dict
```

用途：

- 从 server 当前模型列表中找到 GUI 已打开/已有模型。
- 加入 `SessionManager._models`。
- 设置 `_current_model`。
- attach 后复用现有 geometry/physics/mesh/study/results tools。

```python
model_refresh_tracking() -> dict
```

用途：

- 同步 MCP tracking 与 server 当前模型。
- 移除失效 tracking。
- 可选补充未 tracking 但 server 可见模型。

### 3.8 shared 保存保护

修改 `model_save()`：

```text
如果 session_mode == "shared":
  - 默认拒绝覆盖 model.file() 原路径
  - 返回提示：shared 模式建议 GUI 保存或使用 model_save_version()
  - 只有 allow_shared_overwrite=True 才允许覆盖
```

新增参数：

```python
allow_shared_overwrite: bool = False
```

`model_save_version()` 保持可用，因为它写入新版本文件，不直接覆盖 GUI 打开的源文件。

### 3.9 文档与脚本迁移

新增文档：

```text
docs/shared_session.md
```

内容包括：

- managed/shared 对比。
- 如何运行 `start_clientserver.bat`。
- GUI 如何连接 localhost:2037。
- MCP 如何 `comsol_connect(shared=True)`。
- 如何 `model_list_server()`、`model_attach_existing()`。
- shared 模式保存与文件锁注意事项。

新增脚本模板：

```text
scripts/start_shared_server_64_2037.bat
```

内容：

```bat
"D:\Softwares_02\COMSOL64\Multiphysics\bin\win64\comsolmphserver.exe" -multi on -port 2037
```

README 增加简短入口说明：

```text
Mode A: managed automation
Mode B: shared GUI collaboration
```

## 4. 测试计划

### 4.1 单元测试

新增/更新 `tests/test_basic.py`：

- managed start 设置：
  - `session_mode == "managed"`
  - `server_owner == "mcp"`
  - `cleanup_policy == "clear_and_stop"`
- shared connect 设置：
  - `session_mode == "shared"`
  - `server_owner == "external"`
  - `cleanup_policy == "detach_only"`
- shared disconnect：
  - 不调用 `client.clear()`
  - 不 stop external server
  - 会清空 MCP tracking
- managed disconnect：
  - 仍调用 clear/disconnect/stop
- shared save overwrite：
  - 默认拒绝覆盖原文件
  - `allow_shared_overwrite=True` 时才允许
- `model_attach_existing()`：
  - fake client 中已有模型可加入 tracking
  - attach 后 current model 正确设置

### 4.2 真实 COMSOL smoke test

流程：

```text
1. 运行 start_shared_server_64_2037.bat
2. GUI 连接 localhost:2037
3. GUI 打开或创建一个简单模型
4. MCP 调用 comsol_connect(port=2037, shared=True)
5. MCP 调用 model_list_server()
6. MCP 调用 model_attach_existing()
7. MCP 读取参数/模型树/physics
8. MCP 修改一个参数
9. GUI 验证 server 内存模型变化
10. MCP comsol_disconnect()
11. GUI 模型仍存在，server 仍运行
```

### 4.3 managed 回归测试

确认现有流程不变：

```text
comsol_start()
model_create()
model_create_component()
geometry_create()
geometry_add_block()
geometry_build()
geometry_analyze_topology()
mesh_create()
study_create_stationary()
study_solve()
model_save_version()
comsol_disconnect()
```

### 4.4 异常场景测试

- shared 端口未启动：`comsol_connect(shared=True)` 返回明确连接失败。
- shared 端口被占用但不是目标 server：返回 port/connection 诊断。
- shared 模式误调用 disconnect：默认不 clear server 模型。
- GUI 打开 `.mph` 文件时 MCP 尝试覆盖保存：默认拒绝。
- MCP 进程重启：tracking 丢失，但可通过 `model_list_server()` + `model_attach_existing()` 恢复。

## 5. 风险与缓解

| 风险 | 后果 | P0 缓解 |
|---|---|---|
| shared disconnect 调用 `client.clear()` | GUI/server 模型被清空 | shared 默认 detach only |
| GUI 与 MCP 同时编辑 | 状态互相覆盖 | 文档规定单主控协作规则 |
| `.mph` 文件锁 | 保存失败或覆盖风险 | shared 默认禁止覆盖原文件 |
| 端口 2037 已占用 | 启动失败或连错 server | preflight/port check + 明确错误 |
| 外部 server 被误杀 | 用户 GUI 会话中断 | external owner 永不自动 stop |
| MCP 重启后丢 tracking | 找不到当前模型 | 提供 list/attach existing tools |
| `-multi on` 缺失 | GUI/Python 多 client 冲突 | shared 启动强制加 `-multi on` |

## 6. P0 Acceptance Criteria

P0 完成标准：

1. `comsol_start()` managed 默认行为保持兼容。
2. `comsol_connect(port=2037, shared=True)` 可连接 `Cowork-COMSOL-Codex` 启动的 shared server。
3. shared 模式下 `comsol_disconnect()` 不清空 GUI/server 模型。
4. MCP 能 list 并 attach server 中已存在的模型。
5. attach 后现有参数、几何、物理、网格、求解、结果工具可复用。
6. shared 模式默认禁止覆盖保存原 `.mph` 文件。
7. README 或 docs 中明确说明 managed/shared 使用方式。
8. 单元测试覆盖 session metadata、disconnect policy、attach、shared save protection。
9. `compileall src tests` 通过。
10. 若本机 COMSOL 登录/license 可用，完成一次 shared GUI smoke test。

## 7. 非 P0 范围

这些不放进 P0，避免把会话合并变成大重构：

- 多用户并发编辑锁。
- GUI dirty state 检测。
- 自动合并 GUI 与 MCP 的修改历史。
- 完整 model diff。
- Web dashboard。
- 长期 server daemon 管理器。
- 对所有 COMSOL 版本的启动脚本自动生成。

P0 只解决一件事：**让 managed 自动化与 shared GUI 协作在同一 MCP 架构下安全共存。**
