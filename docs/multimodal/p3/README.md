# P3 本地图文问答

P3 在 P2 的文字检索和上下文组装后增加 PDF 原页证据。用户可以先查看本次选出的文字和原页，也可以把两者一起交给本机视觉模型。答案里的图片引用可以回查到相同知识库、索引版本和 PDF 原页。

## 证据路径

1. 本地 bge-small 和 BM25 召回后由 RRF 融合，沿用 P2 的结构化召回与上下文组装配置。
2. 从已选文字证据的来源映射里找 PDF 页。当文字上下文有 PDF 证据时，也从 RRF Top 5 补选带表格、图像或连线定位的候选页。按原件修订和页码去重，结构化定位优先，再按来源和排名排序，单次最多两张。
3. 从已审核版本保留的原件字节渲染 PNG，校验原件 SHA-256。单页最长边为 1280 像素，PNG 上限为 2 MiB。文字证据和原页使用各自的引用 ID。
4. 使用 Ollama 的 loopback 接口请求本机已安装的 Qwen3-VL。程序校验回答格式和引用 ID，失败时用相同证据重试一次。请求记录模型名称、摘要、耗时和调用次数。事实、方向和条件是否正确需要结合原件判断。

页面提供“查看图文证据 · 本地”和“本地图文问答”。P3 的视觉范围是能由已发布索引定位的 PDF 原页，文字范围包含已入库的 DOCX 内容。

## 接口和复跑

| 接口 | 用途 |
| --- | --- |
| `POST /api/v1/vision/context` | 返回文字与图片的证据定位，生成调用数为 0 |
| `POST /api/v1/vision/chat` | 通过本机模型生成有引用的回答 |
| `GET /api/v1/sources/{generation_id}/{chunk_id}/pages/{page_number}?kb_id=...` | 查看引用对应的 PDF 原页 |

生成前，在 Ollama 中预装 `qwen3-vl:2b-instruct`，用 `OLLAMA_NO_CLOUD=1` 启动仅监听 loopback 的服务。为 API 进程配置以下变量，再用项目的正常方式启动 API。P3 的隔离运行使用 11436，项目配置默认端口为 11434。

```powershell
$env:RAG_LOCAL_VISION_MODEL = 'qwen3-vl:2b-instruct'
$env:RAG_LOCAL_VISION_PORT = '11436'
$env:RAG_ALLOW_EXTERNAL_CALLS = 'false'
$env:RAG_EMBEDDING_BACKEND = 'local'
```

两种输入共用请求格式。对照组将 `include_images` 设为 `false`。图文接口要求本机访问和 `allow_paid=false`。

```json
{
  "kb_id": "example-local-kb",
  "question": "原页流程图中，出发节点的箭头指向哪里？",
  "allow_paid": false,
  "include_images": true
}
```

## 验收

业务样本来自审核后的 dev，正文、表格、流程图各两题。模拟题的目标编码只放在 PDF 内嵌的栅格图上，文字层只保留检索定位提示。对照沿用同一版本、同一问题、同一上下文、同一模型和生成参数，切换是否附带原页。

证据预览使用真实本地 bge-small 和 Milvus。仅从最终文字上下文取页时，4 道图表题有 2 道送达标注原页。补选融合 Top 5 中的结构化页面后，原页覆盖变为 4/4，其中流程图 2/2、表格 2/2。两道正文题使用 DOCX 文字证据。

推理使用 Ollama 0.40.15 本机导入的 Qwen3-VL-2B-Instruct。语言权重为 Q4_K_M，视觉投影为 Q8_0。两份 GGUF 从 Qwen 官方魔搭镜像下载，并与发布者给出的 SHA-256 比对。本机标签为 `qwen3-vl:2b-instruct`，模型清单摘要为 `58777065f915d8ec5819b810e9501617fa01d31f3cd0dc798b242cb4b43c98c2`。[Qwen 官方权重](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF) · [Ollama 导入接口](https://docs.ollama.com/api/create)

2026-11-11 最终对照运行 ID 为 `a10cc35ed8fd4f04839447aa96a1722a`。7 道题的证据预览和两种回答请求全部返回 HTTP 200。14 次回答请求产生了 22 次本机推理，其中 8 次为格式重试。外部调用为 0，9 张原页的回查图像均通过 SHA-256 比对。217 项单元测试通过。

模拟流程图只有栅格图包含目标编码。纯文本组的回答被格式校验拦下。图文组答出箭头指向 `K47`，并以 `E2` 引用 PDF 第 1 页。

| 业务样本检查项 | 纯文本 | 图文 |
| --- | --- | --- |
| 通过输出格式和引用 ID 校验 | 2/6 | 3/6 |
| 有精确字面要求的必答点命中 | 1/7 | 4/7 |
| 四道图表题的标注原页随请求送达 | 未附图 | 4/4 |
| 四道图表题的回答引用标注原页 | 未附图 | 0/4 |

两道业务流程图题在图文组命中了 3 个有字面要求的必答点。两道表格题的图文输出仍被格式校验拦下。字面检查只记录标注术语是否出现，业务事实和图表关系的完整正确性留待 P4 按原件复核。

本地任务目录 `.debug-rag-multimodal-p3` 保存模型启动脚本 `start_p3_model.ps1`、复跑脚本 `run_p3.py`、评分检查脚本 `audit_p3.py`、单测结果和逐题原始记录。以项目根目录为工作目录，用主项目虚拟环境运行两个 Python 脚本。只验收检索和原页链路时，给两个脚本传入 `--preview-only`。每次对照使用独立 SQLite 与运行目录。业务原页和逐题回答保存在本机。

```powershell
$p3 = Join-Path $env:USERPROFILE 'Documents/ChatGPT/Agent项目/.debug-rag-multimodal-p3'
& (Join-Path $p3 'start_p3_model.ps1')
& .\.venv\Scripts\python.exe -B -X utf8 (Join-Path $p3 'run_p3.py')
& .\.venv\Scripts\python.exe -B -X utf8 (Join-Path $p3 'audit_p3.py')
```

## P4 对照目标

P4 使用冻结的题集、语料版本和检索配置，对照纯文本与图文的必答点覆盖、引用支持和耗时。先核对目标页是否送达，再用原件复核模型的回答和证据不足时的处理。
