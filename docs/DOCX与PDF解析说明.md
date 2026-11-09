# DOCX / PDF 结构化解析

本模块针对文档处理提供“提取—核对—入库”的入口。当前不调用 PaddleOCR、Qwen-VL 或其他外部视觉服务，不能把图片占位符、扫描页预览或解析器成功返回当作识别成功。

## 已实现的处理

| 输入 | 提取结果 | 限制与显式警告 |
|---|---|---|
| DOCX | 按正文顺序提取段落、标题样式、表格行/单元格、合并信息，保存媒体文件 | 自动编号只保存 numId/层级而不猜测显示序号；嵌套表、页眉页脚、批注/修订、文本框、图表等提示待核对 |
| PDF | 按页提取文字行与坐标、检测有边框表格并保留矩阵，排除表格区域重复文字，生成页面 PNG 预览 | 复杂阅读顺序、无边框/跨页表格、矢量图和图片需核对；文字很少的页面进入 OCR 待处理列表 |
| Markdown/TXT | 延续原有严格元数据、原文区间与父子切片 | 原有索引和导入规则保持兼容 |

DOCX 不虚构页码，因为没有 Word 排版引擎时无法可靠确定分页；来源采用正文块编号、表格与媒体部件。PDF 坐标为页面点坐标，页码从 1 开始。

解析是局部、确定性的结构提取，不保证覆盖全部 Office/PDF 特性；读者必须检查输出。来源链接表示提取块对应的原件位置，提取文本中的行号不是二进制文件中的原始行号。

## 使用方法

安装可选解析依赖：

```powershell
uv sync --frozen --extra dev --extra local-models --extra readers
```

`debug.docx` 或 `debug.pdf` 配套 `debug.meta.json`，字段与 TXT sidecar 一致，例如：

```json
{
  "source_key": "debug-panel-overview",
  "title": "Debug 面板说明",
  "app_snapshot": "debug-v1",
  "data_kind": "business",
  "feature_status": "delivered",
  "updated_at": "2026-11-03",
  "external_processing_allowed": false
}
```

`business` 只标明资料身份，不证明业务事实已核对。外发许可默认拒绝；应由资料所有者确认，不能仅为运行远程编码修改为 true。模拟资料使用 `simulated` 并与业务库分离。

```powershell
uv run --no-sync python -m debug_rag.cli parse --source materials/debug.pdf --output runtime/parsed
```

输出一个按原件与提取文本摘要命名的目录：

```text
document.md             含结构标记的提取草稿
document.origin.json    原件/文本摘要、块位置、警告、核对状态
original.pdf 或 .docx   原始二进制文件
assets/                 PDF 页面预览或 DOCX 媒体文件
```

输出目录已存在时不覆盖。`parse` 不创建知识库数据库，也不调用模型。

核对正文顺序、表格单元格、标题、原件页码/正文块和警告后：

```powershell
uv run --no-sync python -m debug_rag.cli review-parse --source runtime/parsed/实际目录/document.md
```

如存在明确可接受的缺失/不确定性，可在检查后增加 `--accept-incomplete`。这一标记保留所有警告；不会执行 OCR，也不证明文档已被完整识别。纯扫描件没有提取到正文时，即使使用该参数仍拒绝入库。

然后复用已有导入与发布：

```powershell
uv run --no-sync python -m debug_rag.cli ingest --kb debug-documents --source runtime/parsed
uv run --no-sync python -m debug_rag.cli build-index --kb debug-documents --backend local
```

完整目录导入仍以输入集合为准。公司文件中的 `.pdf/.docx` 如果没有先处理，系统显式返回 `binary_requires_parse_review`，不会在目录扫描时静默忽略。导出的原件只作为绑定资产，不重复当成待解析输入。

## 原件与引用的一致性

- 新增 `document_origins` 表，保存二进制原件和审核后的块映射；是新增表，不通过重建旧表迁移数据。
- 原件、提取文本和映射参与 revision 身份。改动任何绑定内容会校验失败或产生新 revision。
- 丢失 `.origin.json`、路径指向包外、原件摘要不符、块位置篡改、资产变化时拒绝导入。
- 检索从 SQLite 中保存的内容生成 `source_locations`、`original_sha256`、`extraction_warnings`，不依赖输入文件还留在原目录。
- 提示词会告知模型解析警告；页面原文弹窗区分提取文本位置与 PDF 页码/坐标或 Word 正文块。

输入限制：二进制文件最多 20MiB；DOCX 展开总量 100MiB、XML 8MiB、部件数量 10000；PDF 最多 100 页并限制页面像素；提取文本最多 2MiB。加密 PDF 明确拒绝，不尝试猜密码。解析器只读取本地文件，不执行 Office 宏、外部图片链接或文档内指令。

## 后续

实际公司文档尚未提供。收到后需要独立核对其文字层、表格/图片类型，再选择 PaddleOCR 版面流水线或视觉模型；当前没有完成扫描件 OCR、图片语义、复杂跨页表格识别或实际业务资料验收。

参考：[PyMuPDF 页面与表格接口](https://pymupdf.readthedocs.io/en/latest/page.html)。软件测试使用生成的独立样本，不代表任意 PDF/DOCX 的效果。
