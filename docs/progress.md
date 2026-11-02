# 阶段进度

## 2026-11-02 最新增量：迁移、工程可靠性、远程 dense/sparse

- 项目已复制至 `C:\Users\15853\DEBUG_RAG`，原目录保留；独立环境按锁文件重建，SQLite 在线备份与完整性检查通过，历史索引/费用记录保留，Milvus 使用原命名卷。
- 本轮新增持久化索引任务、进度、失败/中断识别、重试、发布确认对账、页面维护入口与目录归属明确的启停脚本。完整会话与条件继承暂缓。
- VikingDB 双表示适配、独立 hybrid 索引、固定 sparse 词项映射、每 Query dense/sparse TopK、一次全局 RRF 已加入，沿用独立重排与父片段扩展。旧本地基线保留。
- 离线单测 188 项通过，真实 Milvus 集成 2 项通过，新目录四题 HTTP 本地检索与引用通过。**未执行本轮付费调用，尚未完成真实远程 BGE-M3 联调或质量评测。**
- 迁移后付费相关开关关闭；远程调用需明确许可、核价和预算。首次回归发现继承进程配置污染并导致旧断言展开凭据，已告知轮换并补单测环境隔离。
- 详情以 [迁移与本轮验收](迁移与本轮验收-2026-11-02.md) 为准。以下旧记录保留历史时间范围。

学习入口：[项目全景与学习路线](项目全景与学习路线.md)、[P2 原理与代码导读](P2原理与代码导读.md)。本文的阶段记录按当时日期保留，历史服务启动记录不代表现在仍在运行。

## 已确认的协作基线

- 用户已整体确认技术方案；P0 完成后，明确授权“来接着 P1”。
- 采用普通 Python 模块，不使用 LangChain/LangGraph；Docker 先数据库、后应用。
- 本地 bge-small，生成与重排 API 后续按方案接入，项目月预算合计 50 元。
- 分阶段交付与讲解。P0/P1 不调用付费 API，不实现聊天或文档问答。

## P0：已完成（2026-10-25）

### 实际交付

- 独立 `.venv`、`pyproject.toml` 和 `uv.lock`，CPU 推理作为 local-models extra；没有修改课程环境。
- 配置校验、50 元预算配置上限、凭据字段保护和忽略 Git 的本机 `.env`。
- SQLite 初始化、发布快照检查与跨连接重启保留数据的测试。
- FastAPI 应用生命周期、存活/就绪接口、OpenAPI 文档。
- doctor、init-db、model-smoke 命令；P0 没有付费模型调用能力。
- Docker Desktop 已启动；Milvus 使用官方支持的 embedded etcd + 本地存储单容器部署。
- 环境与运行导读见 [P0 学习与验收](P0学习与验收.md)。

### 验收证据

| 检查 | 实际结果 |
|---|---|
| `pytest tests/unit -q` | 17 passed |
| 启用本地开关后的 `pytest tests/integration -q` | 1 passed；真实 Milvus dense/sparse 写读、删除和临时集合清理 |
| `ruff check src tests` | All checks passed |
| `ruff format --check src tests` | 11 files already formatted |
| doctor | foundation_ready=true；SQLite 与 Milvus 2.6.4 可连接；ready=false，符合当前无知识库的状态 |
| model-smoke（新独立环境） | 已有 bge-small 离线 CPU 编码成功，形状 `[3,512]` |
| 真实 HTTP | `/health/live` 200；`/health/ready` 503 且列出缺失知识库/模型流程；`/docs` 与 `/openapi.json` 200 |
| Docker | `debug-rag-p0-standalone-1` healthy，仅宿主机 loopback 19530 开放 |
| 付费调用 | 0 次，0 元 |

单元测试输出有当前 Starlette 对 httpx TestClient 的弃用提示；真实集成测试输出有混合执行权限导致的 pytest 缓存写入提示。均不影响测试断言通过，未将提示隐藏，也没有据此引入无关依赖。

### 锁定与运行信息

- Python 3.12.13，FastAPI 0.162.0，Pydantic 2.14.1，SQLAlchemy 2.1.6。
- PyMilvus 2.6.2，Milvus 2.6.4（官方发布说明列出的版本配对）。
- Torch 2.8.0+cpu，sentence-transformers 5.7.0，transformers 4.57.6。
- 镜像摘要：`milvusdb/milvus@sha256:27f1732a6668c813ee96d21364e3ba220ce1dd1d6e07660106d646dc33d1c654`。
- 空库时容器瞬时内存观察约 137.8MiB，Docker 可见总内存约 7.621GiB；不是实际业务负载的容量保证。
- 新环境模型初始化（包含库导入）约 96.10 秒，3 条短句三次编码约 201.76/32.60/46.44ms；不当作完整 RAG 延迟或召回质量证据。
- API 目前在 `127.0.0.1:8000` 运行。停止方式见 README；数据库使用命名卷，不把清理卷作为停止步骤。

### 已处理的问题

- Docker 初始未启动，通过已安装的 Docker Desktop 启动后确认 Linux Engine 可连接。
- 沙箱无法访问依赖仓库或本机服务时，按授权使用相应执行权限；没有绕过配置或使用课程账号。
- GitHub 发布 API 触发公共限流，改查官方版本发布页和版本固定的部署源码，未申请或读取 GitHub 凭据。
- 三容器模板的 MinIO 镜像拉取失败，改用官方 embedded 方案；只保留本项目 Milvus 容器，不修改全局镜像源。

## P1：已完成（2026-10-25）

### 实际交付

- 8 份独立模拟资料：7 份 Markdown + 1 份 TXT；TXT 有独立同名 `.meta.json`。
- 严格元数据：来源身份、标题、业务快照、资料类别、功能状态、更新时间、外发许可。
- UTF-8/BOM、LF/CRLF 原文保存；Markdown token 行映射划分章节，TXT 按普通段落处理。
- 默认父片段 1600、子片段 600 字符上限；原文不改写，保存行号、字符区间、章节路径、父子关联、超长块续片标志。
- SQLite 新增资料、不可变 revision、chunk、generation 成员与准备指针表；P0 原表结构不变，无删除重建。
- 批次校验与事务写入；重复导入/重命名复用，内容或元数据变化产生新 revision；切片配置或解析器版本变化产生新 generation。
- `ingest` 与 `inspect` CLI。只准备、不发布；API 阶段字段更新为 P1，ready 仍为 false。
- [P1 学习与验收](P1学习与验收.md)。

### 验收证据

| 检查 | 实际结果 |
|---|---|
| `pytest tests/unit -q` | 46 passed，包含 P0 原有测试与 P1 新增测试 |
| 最终 `pytest -q` | 46 passed、1 skipped；真实 Milvus 测试未开启开关，明确跳过 |
| `ruff check src tests` / `ruff format --check src tests` | 全部通过，18 个 Python 文件符合格式 |
| 真实 CLI 导入最终资料 | 8 文档，33 父片段、34 子片段；prepared，published=false |
| 同一目录再次导入 | generation 不变，新增 revision=0，新增 chunk=0 |
| 实际原文核对 | 本地 SQLite 中包含开发期间历史版本的 77 个 chunk，全部等于原文对应字符区间 |
| 历史保存 | 开发期间补充相机资料产生 1 个新 revision，旧版本仍可查看；本机累计 9 个 revision，当前快照使用 8 个 |
| 发布隔离 | active_generation_id 仍为空；测试另外覆盖已发布旧指针不受成功/失败导入影响 |
| 数据库故障回滚 | 测试注入 chunk 写入故障后，文档、revision、chunk、generation 与准备/发布指针均保持原状态 |
| 原文定位 | 单元测试覆盖 BOM、LF/CRLF、超长中文、代码块内伪标题、表格、列表、TXT 与父子区间 |
| 付费调用 | 0 次，0 元 |

当前资料的准备快照为 `760f5d793b1d4641bb58f97491b79f5f`；ID 为本机运行记录，新环境生成其他 ID 正常。完整本机检查结果保存在忽略 Git 的 `runtime/P1-inspect.json`。单元测试仍有 P0 已记录的 Starlette/httpx 弃用提示。

本阶段没有改动 Milvus 部署或模型推理代码，因此复用 P0 的真实 Milvus/model-smoke 证据，没有重复加载模型或运行数据库写删冒烟。此前启动的 API 进程不带自动重载，查看 P1 阶段字段前需按 README 停止并重新启动；本阶段 HTTP 验证使用应用测试客户端。

### 当前范围与实现约定

- generation 在 P1 可以以 `prepared` 状态存在；只有 P2/P3 校验检索产物后才可成为 ready 并发布。
- 当前快照与资料类别约束放在 generation manifest 中，并在同库新导入时检查。没有假设 `create_all()` 能给 P0 旧表补列；后续需要改列时另做迁移。
- 一篇文档只有一个 feature_status。模拟规划拆成独立 planned 文档；P1 不实现段落级状态标注。
- 同一知识库固定 app_snapshot/data_kind；不同业务快照或模拟/业务资料应使用不同库。资料修订保持同一快照标签；跨业务快照换代另行设计迁移。
- 路径重命名不改变文档身份或内容 revision；revision 保存创建时路径，原文查看使用保存的 revision，不依赖当前磁盘路径。
- 导入是完整输入集合；不自动扫描公司目录，不修改课程文件，不调用外部模型，也没有聊天功能。

## P2：实现及本地索引验证已推进，端到端验收待补齐

- 用户于 2026-10-26 明确选择先完成本地检索与 API 适配，暂不执行付费验证。
- 已实现离线 BGE、Milvus FLAT/COSINE、BM25、RRF、生成适配、引用校验、费用预留台账、API 与最简本机页面。
- 本机实际发布索引 `e3724e2f525b499d991eb5456d4266c5`：34 个原文子片段、34 个向量窗口；该次构建外部调用 0 次。
- 2026-10-26 的单元测试记录为 74 passed。生成接口仅使用模拟响应，不能称为真实 DeepSeek 问答验证通过。
- 原定四题本地 HTTP 检索验收及浏览器流程在会话中断前未获得完整结果；不计为通过。完整 RAG 与业务质量验收仍未完成。

### 2026-10-31：页面 Failed to fetch 排查

- 实测 8001 无监听，GET `/health/live` 返回连接被拒绝；浏览器保留页面，但后端进程已不在运行。
- Docker Desktop/引擎也未运行，Milvus 需随开发环境恢复。
- 增加 `scripts/start-local.ps1`：复用已存活后端或启动独立后台进程，记录 PID 与日志；默认先启动本项目 Milvus。启动脚本已通过 PowerShell 语法解析。
- 页面网络失败改成可操作的中文提示，另行区分非 JSON 响应和业务 HTTP 错误。
- 启动服务的授权被拒绝，未启动新进程，因此本次不能声称已恢复在线检索。用户可先启动 Docker Desktop，再在项目目录执行脚本。

### 2026-10-31：全景核对与教学文档

- 只读核对当前 SQLite：active 指针仍指向上述 P2 generation，manifest 为 8 文档、33 父片段、34 子片段/窗口，512 维 CPU 本地模型；api_calls 为 0 条。
- 已核对本机实际依赖版本、主链路调用方式与阶段范围，新增完整总览和 P2 代码导读。
- README 更新到当前 P2 状态，统一常用端口为 8001，说明当前 `--publish` 已接入以及 P1 文档的历史范围。
- 本轮未启动后台服务、未执行付费验证，也未把文档整理当作 HTTP 或问答验收结果。

### 2026-11-01：small-to-big 与远程模型决定

- 用户明确要求实现“命中子片段后扩展父片段”。现已接入：同 generation/revision 回查父片段，核对元数据、章节与原文区间；同父段去重；父段超过输入预算时回退完整子片段；引用指向实际提供的原文区间。
- 默认 `RAG_PARENT_EXPANSION_ENABLED=true`，支持关闭做对照。检索仍针对子片段，只有生成上下文准备阶段扩展；不需要修改已有向量或重建索引。
- 新增 `context` CLI、`POST /api/v1/context` 与页面本地证据预览按钮。不调用生成模型；禁止外发的资料可在本地预览，进入生成接口前仍会被许可检查拦截。
- 原文查看接口支持当前已发布快照内的父、子片段，跨库仍拒绝。
- 最终回归：85 passed、1 skipped；真实 Milvus 测试未开启，明确跳过。`ruff check src tests` 通过，格式检查通过；保留既有 Starlette/httpx 弃用提示。这里是临时库、模拟向量/生成依赖的验证，不是新增真实问答质量验收。
- 用户明确 BGE-M3 不在笔记本运行，采用服务器或 API；目前未准备服务，先整理 [远程接口要求](BGE-M3远程接口要求.md)。没有接通远程模型、没有下载 BGE-M3、没有执行付费调用。
- 新增 [原文、向量与 BM25 的数据关系](原文向量与BM25的数据关系.md)，解释 source_key、映射、分词与索引 JSON。
- 后台服务没有自动重启；页面加载新代码需要重启应用。P2 真实 HTTP/浏览器和付费生成的整体验收仍待补齐。

### 2026-11-01：远程服务采购调研

- 新增 [BGE-M3 远程服务采购调研](BGE-M3远程服务采购调研.md)，区分普通 dense API 与真正暴露 dense/sparse 的原生接口；记录 DeepInfra 8K/512 版本差异、硅基流动与 Novita 的能力证据，以及百炼的其他模型替代路线。
- 只核查官方公开资料，没有充值、下载模型、调用付费推理或启动后台服务；尚未选定并接通供应商。
- 本机配置只核查布尔状态：DeepSeek Key 未配置、外部调用关闭、总预算 50 元/月。Query 改写与独立 Reranker 仍未实现；已有生成 API 适配器不能当作改写已经完成。

### 2026-11-01：用户授权先实现 Query 改写与独立 Reranker

- 新增 DeepSeek 单条改写器：保留原问题，校验 JSON、长度、标识符等；相同改写不重复投票；失败回退原问题。不实现多轮记忆，不宣称语义等价已经验证。
- 原问题/有效改写分别执行现有本地 dense 与 BM25 Top 5，单快照内一次全局 RRF 后交给独立百炼 `qwen3-rerank`。原文索引/分数校验通过才应用排序，之后再 small-to-big、分配证据 ID 并生成引用答案。仍未接入 BGE-M3 learned sparse。
- 百炼原生适配按自己的 endpoint/Key 配置，不自动切换其他供应商；改写复用 DeepSeek。两者默认关闭，CLI `--enhanced`、`/api/v1/search/advanced`、context/chat 显式增强字段与页面按钮已接入；本地 search 与本地证据预览保留无付费调用路径。
- 多供应商共用一份项目费用台账，单次调用保存独立核价记录。缺价/过期/余额不足在网络前阻止；未知费用保留预留，不自动重试。重排之前检查全部候选外发许可，失败保留 RRF 排序并记录 degraded/reason。
- 最终回归：118 passed、1 skipped（真实 Milvus）；Ruff check 与 format --check 通过，40 个 Python 文件格式通过；保留原有 Starlette/httpx 弃用提示。新增 33 项验证包括协议、四路融合、重排映射、引用生成、失败回退、许可、预算、配置与处理中发布新索引的快照一致性。
- 只使用 MockTransport 和临时测试库，不运行付费 API，不启动后台服务，不下载模型，不修改本机 `.env` 或重建已有业务索引。真实模型效果及端到端验收仍待 API 和服务恢复。
- 使用方法和教学流程见 [Query 改写与独立重排接入说明](Query改写与独立重排接入说明.md)；README 与现有学习文档已同步最新边界。

### 2026-11-02：本地服务与真实 API 链路通过

- 用户撤销先前付费测试暂缓，明确要求运行 Docker/API 并用当前百炼密钥测试。已启动健康的 Milvus 容器和本机 8001 API；仅处理已许可外发的独立模拟资料。
- 四题真实 HTTP 本地检索与引用/跨库隔离验收通过，费用为零；真实 Milvus 临时集合 dense/sparse 写读、删除与清理集成测试 1 passed。
- 两道真实增强问答通过，每题改写、独立重排、生成各一次，共 6 次模型调用；父片段扩展和引用回查通过，无降级、无未知费用。第一题形成四路，第二题改写保持原样，不重复投票。
- 台账新增费用上界 0.009703 元，剩余月预算 49.990297 元，均按保守上界记账，不能等同供应商实际扣款。
- 浏览器页面加载、本地检索、原文弹窗、父片段预览通过；未为浏览器检查重复增加付费调用。
- 今日复核并刷新 DeepSeek 价格卡至 2026-11-08；单价未变。更新预算测试的固定日期，避免测试依赖生产核价窗口；单元回归 118 passed，真实 Milvus 集成另有 1 passed。Ruff 静态和格式检查通过。
- 已按授权开启本机外部调用、改写和重排开关；后台服务保留运行。新增显式 `--allow-paid` 的固定两题真实验收脚本与本机 JSON 报告。
- 详情见 [P2 真实链路验收记录](P2真实链路验收-2026-11-02.md)。BGE-M3 远程 dense/sparse 仍未接入，多轮、业务质量评测等后续阶段未完成。

### 2026-11-02：准备火山引擎 BGE-M3 配置

- 用户已创建火山引擎 API Key，询问接口与 `.env` 写法。已核对新数据面北京公网 Host 及 `/api/vikingdb/embedding` 路径；使用 API Key Bearer 鉴权，区别于旧 `embedding_v2` SDK 协议。
- Settings、`.env.example` 和本机 `.env` 已补 `RAG_VIKING_API_KEY`、`RAG_VIKING_EMBEDDING_ENDPOINT`、`RAG_VIKING_EMBEDDING_MODEL`。本机只追加缺失字段，保留已有密钥和配置；新 Key 留空供用户本机填写。
- 配置测试 19 passed，Ruff 通过；未执行收费请求、未创建云数据库索引、未切换本地索引。此处仅为配置准备，编码适配、远程验证及业务 dense/sparse 链路仍待实现。
- 使用说明见 [火山 BGE-M3 配置说明](火山BGE-M3配置说明.md)。
