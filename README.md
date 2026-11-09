# Debug RAG · 研发知识助手

一个面向研发与测试场景的 RAG 知识问答项目。系统将技术文档组织为可检索的知识库，结合语义检索、关键词检索、重排和大模型生成，回答功能说明、操作步骤、开发维护及验证方法，并提供可回查的原文引用。

项目使用独立编写的模拟资料，覆盖相机状态展示、应用内悬浮层、文件导出等场景，用于演示研发知识问答的完整流程，不代表公司实际部署成果。

## 功能特性

- **文档导入与原文定位**：支持 Markdown/TXT，并提供 DOCX/PDF 结构化提取与核对入口；保留标题、表格单元格、PDF 页码和坐标、Word 正文块与原件摘要。
- **解析质量门禁**：提取草稿、原文件与位置映射一起保存，核对后才能入库。图片、扫描页、自动编号和复杂表格显式列出待处理项，不静默视为已识别；纯扫描件在没有 OCR 文字时拒绝入库。
- **资料版本管理**：保存不可变文档修订；重复导入复用已有内容，新增、替换和移除文档通过完整快照构建与发布生效。
- **混合检索**：提供本地 bge-small 稠密向量＋BM25 基线，以及远程 BGE-M3 dense＋learned sparse 路径；各路候选去重后使用 RRF 融合。
- **Query 改写与独立重排**：可选使用 DeepSeek 生成一条检索改写；使用百炼 qwen3-rerank 对融合后的原文候选重排，增强失败时记录原因并回退。
- **父片段上下文扩展**：先检索较小片段，再按预算扩展同版本父章节，补齐步骤与前置条件；同父片段去重，超限回退子片段。
- **带引用的回答**：根据选定证据生成回答，校验引用标识并映射回原文；资料不足、部分回答和需要澄清等情况使用明确状态返回。
- **可靠的索引发布**：新索引独立构建，校验通过后事务切换发布指针；失败保留旧索引，支持校验后切回历史索引。
- **可恢复的构建任务**：持久化任务状态与执行阶段，提供同库互斥、中断识别、失败重试，以及发布成功后的任务状态对账。
- **可观测与费用控制**：展示召回排名、融合与重排轨迹、降级原因及外部调用记录；通过共享费用台账执行调用前预留、价格有效期检查和未知费用保留。
- **本地演示页面**：支持提问、检索、上下文预览、引用原文查看、索引构建进度和失败重试。

## 问答链路

系统将资料处理与在线问答分开：资料更新时构建索引，提问时只读取已经发布的知识库快照。

### 1. 文档处理与索引发布

```text
Markdown / TXT ＋ 元数据
  → 格式与许可校验
  → 章节解析、父子片段切分、原文位置映射
  → SQLite 保存原文、revision 和片段关系
  → 编码子片段，构建向量索引与词面检索产物
  → 校验数量、维度、原文映射及检索可见性
  → 发布新的 generation
```

每个 generation 是一份完整检索快照。构建过程中继续保留旧代；只有新代全部通过校验后，查询才切换到新代，避免读取半成品索引。

### 2. 默认链路：本地向量＋BM25

```text
用户问题 q0 ────────────────┐
可选检索改写 q1 ────────────┤
                           ↓
             每个问题分别执行：
             dense TopK ＋ BM25 TopK
                           ↓
             单路按原文 chunk 去重
                           ↓
                  一次全局 RRF
                           ↓
               可选独立 Reranker
                           ↓
           父片段扩展、去重及上下文裁剪
                           ↓
              DeepSeek 生成结构化回答
                           ↓
            引用校验 → 回答与原文来源
```

原问题始终保留。改写相同或失败时不增加重复召回；重排使用原问题及原文候选。检索和重排针对子片段，上下文组装阶段才扩展父片段。

### 3. 可选链路：远程 BGE-M3 dense＋sparse

```text
原问题 q0 → BGE-M3 → dense TopK ──┐
                  → sparse TopK ─┤
可选改写 q1 → BGE-M3 → dense TopK ┤
                    → sparse TopK┘
                                ↓
              单路去重 → 一次全局 RRF
                                ↓
           独立重排 → 父片段扩展 → 引用回答
```

- BGE-M3 在远程服务运行；dense 与 learned sparse 分别召回，sparse 不等同于 BM25。
- 远程返回的字符串词项通过每代固定词表映射为 Milvus 稀疏维度，避免词项错配。
- 本地基线与远程路径使用独立索引，查询编码器必须与索引的模型身份一致。
- 每路 TopK 独立配置，默认 5，当前范围 1–5；有效改写最多增加为四路，合计最多 20 个候选。
- 跨路相同 chunk 合并为一个候选并保留各路排名；融合只执行一次，不直接相加不同检索器的原始分数。

远程适配器、索引及四路召回代码已有模拟接口测试。**真实火山 BGE-M3 编码、Milvus 独立建库、dense/sparse 双路召回、RRF 与父片段扩展已在模拟资料上验证通过**；与改写、独立重排和生成的真实联合验收仍待完成。本地基线已有真实运行验证。

## 架构与技术栈

采用普通 Python 模块显式组织流程，FastAPI 提供 HTTP 接口和静态页面，SQLite 管理原文与状态，Milvus 管理向量检索。

| 组件 | 职责 |
|---|---|
| Python 3.12 / uv | 项目环境、依赖与锁文件 |
| FastAPI / Pydantic | HTTP 服务、请求校验、配置管理 |
| SQLite / SQLAlchemy | 文档修订、片段关系、发布指针、任务和费用台账 |
| Milvus / PyMilvus | 稠密与稀疏向量存储、过滤与召回 |
| bge-small-zh-v1.5 / BM25 | 默认本地语义及关键词检索 |
| 远程 BGE-M3 | 可选 dense / learned sparse 编码 |
| DeepSeek / 百炼 qwen3-rerank | 回答生成、Query 改写与独立重排 |
| Docker Compose | 本地 Milvus 服务与数据持久化 |
| pytest / HTTPX MockTransport / Ruff | 行为测试、协议模拟与静态检查 |

## 项目结构

```text
src/debug_rag/
├── main.py                 # HTTP 接口与应用生命周期
├── cli.py                  # 命令行入口
├── settings.py             # 配置读取与校验
├── components.py           # 组件创建与连接
├── jobs.py                 # 构建任务、阶段反馈与恢复
├── budget.py               # 费用台账
├── diagnostics.py          # 健康与就绪检查
├── errors.py               # 结构化错误
├── ingestion/              # 文档解析、切片与导入
├── retrieval/              # 编码、建索引、召回、融合、改写与重排
├── generation/             # 模型调用、证据组装与引用校验
├── storage/                # SQLite、Milvus 适配
└── web/                    # 本地演示页面
fixtures/documents/         # 模拟知识库资料
tests/                     # 单元测试与数据库集成测试
infra/milvus/              # Milvus Compose 配置
scripts/                   # 启停及验收脚本
docs/                      # 设计、协议与代码导读
```

## 快速开始

准备 Python 3.12、uv、已启动的 Docker Desktop，以及完整的本地 bge-small 模型文件。在仓库根目录执行：

```powershell
uv sync --frozen --extra dev --extra local-models --extra readers
# 首次使用时创建配置；已有 .env 时保留原配置。
Copy-Item .env.example .env
```

在 `.env` 中设置 `RAG_EMBEDDING_MODEL_PATH`，指向已有的本地模型目录。默认使用本地检索，外部模型调用关闭；生成、改写及重排需另外配置自己的 API 和有效核价。密钥与运行数据不提交到 Git。

```powershell
# 启动 Milvus 与本地 API
.\scripts\start-local.ps1

# 导入模拟资料、构建并发布本地索引
uv run --no-sync python -m debug_rag.cli ingest --kb demo-debug --source fixtures/documents
uv run --no-sync python -m debug_rag.cli build-index --kb demo-debug --backend local

# 仅检索原文，不调用生成模型
uv run --no-sync python -m debug_rag.cli search --kb demo-debug --question '文件导出取消后需要清理什么？'
```

访问演示页面：<http://127.0.0.1:8001/>，接口文档：<http://127.0.0.1:8001/docs>。

已有发布索引无需每次启动都重建。文档更新后先重新导入完整集合，再通过 CLI 或页面构建发布。页面维护入口只执行本地构建；远程编码需满足额外费用许可和配置条件。

```powershell
# 查看状态与费用记录
uv run --no-sync python -m debug_rag.cli doctor
uv run --no-sync python -m debug_rag.cli budget

# 停止服务，保留数据库与索引
.\scripts\stop-local.ps1
docker compose -f infra/milvus/compose.yaml stop
```

`/health/live` 表示进程存活；`/health/ready` 区分检索可用与完整问答配置。关闭外部生成时，本地检索仍可使用，完整问答就绪检查可能返回 503。

## DOCX / PDF 资料处理

原始文件配套同名 `.meta.json` 元数据，经提取与核对后再进入现有索引链路：

```text
DOCX / PDF ＋ 元数据
→ 正文、表格与位置提取 → 草稿＋原件＋映射＋页面/图片预览
→ 人工检查解析内容与警告 → 明确接受已知缺失（如适用）
→ 入库：SQLite 保存二进制原件和提取文本
→ 父子切片 → 原文位置随候选和引用返回
```

```powershell
uv run --no-sync python -m debug_rag.cli parse --source materials/debug.docx --output runtime/parsed
# 对照原件完成核对后，指定命令输出的 document.md：
uv run --no-sync python -m debug_rag.cli review-parse --source runtime/parsed/实际目录/document.md
uv run --no-sync python -m debug_rag.cli ingest --kb debug-documents --source runtime/parsed
```

有解析警告时默认拒绝核对确认，只有检查并接受已知局限后才能使用 `--accept-incomplete`；它不会执行 OCR。扫描页、图片语义与复杂版面仍需后续 OCR/视觉适配或人工补充。实际公司文件尚未用于本项目验收。详见 [DOCX/PDF 解析说明](docs/DOCX与PDF解析说明.md)。

## 测试与验证

```powershell
uv run --no-sync pytest tests/unit -q
uv run --no-sync ruff check src tests scripts
uv run --no-sync ruff format --check src tests scripts

# 真实 Milvus 集成测试：仅操作自有临时集合
$env:RAG_RUN_MILVUS_TESTS='1'
uv run --no-sync pytest tests/integration -q
Remove-Item Env:RAG_RUN_MILVUS_TESTS
```

测试覆盖原文定位、索引发布、快照一致性、四路召回、重排映射、引用、费用保护和中断恢复。数据库集成、本地 HTTP 检索、页面维护和少量真实生成链路已有验证；模拟接口测试不代表真实远程模型可用，也不代表业务准确率。

## 当前边界

- 提供单轮问答；多轮记忆、条件继承和会话管理尚未实现。
- 文档维护采用 CLI 全量导入及快照发布，尚无独立上传管理台。
- 远程 BGE-M3 的历史 403 已在服务开通及密钥更新后解除；独立模拟库真实建库与双路检索通过。可用 `uv run --no-sync python scripts/verify_bge_remote.py --allow-paid` 做受控探测，增加 `--build` 会重新收费编码并发布模拟库新代，不启用生成或重排。默认演示仍使用本地基线。
- 固定评测集、系统性对照实验、扫描件 OCR/视觉识别、辅助摘要检索、应用容器化和公司真实资料接入待完成。

## 进一步阅读

- [RAG 数据流与代码导读](docs/P2原理与代码导读.md)
- [原文、向量与 BM25 的数据关系](docs/原文向量与BM25的数据关系.md)
- [Query 改写与独立重排](docs/Query改写与独立重排接入说明.md)
- [工程可靠性设计](docs/工程可靠性说明.md)
- [远程 BGE-M3 接口与限制](docs/远程BGE-M3协议.md)
- [文档解析与远程编码验收](docs/文档解析与远程编码验收-2026-11-04.md)
- [BGE-M3 真实建库验收](docs/BGE-M3真实建库验收-2026-11-04.md)
- [Milvus 部署说明](infra/milvus/README.md)
