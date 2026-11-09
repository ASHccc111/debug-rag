# Debug 业务评测数据集 v1 草稿

本目录交付单轮业务问答评测数据、来源记录和离线校验工具。状态为 **draft**。这是 Agent 生成且经程序检查的草稿，尚未完成人工审核，也未执行 RAG 效果评测。不能称为正式金标、已冻结测试集或严格盲测。

本目录为首轮人工审核工作副本。原始交付在同级 debug-business-v1。审核结论保存在 review_decisions.jsonl，case_content_sha256 对排除 review 字段后的 case 按 UTF-8、排序键、紧凑 JSON 编码计算。0025 已按意见修订，0059 和 0060 已记录人工通过。整体仍按草稿校验流程审核。

## 来源与适用范围

固定输入为仓库 `note/` 中的 24 份 DOCX 和 6 份 PDF，共 30 份、PDF 29 页。只使用 `corpus_manifest.json` 列出的文件，未扩充其他语料。PDF 是另外六个专题，与 DOCX 不是同文双格式。

文档声明的业务范围为 OBSBOT_Live `business/debug` 及必要的 App 接入边界；声明分支为 `p/caijiamin/feat_debug_2th`，提交为 `9010928ca51c6e766f75414c49c748338e0b7ecb`，资料日期为 2026-11-03。这些是原件声明，逐篇声明与摘录见清单。本次工作区未提供该业务提交，源码交叉核对统一为 `not_available`。未以 RAG 仓库的提交或工作区外源码代替它，也未编译或运行 Android 工程。

来源身份由 `doc_id + 原始二进制 SHA-256` 固定；原文证据进一步绑定 `block_id + Python 字符跨度`。资料路径相对 `note/`，采用 `/`。本机绝对路径仅保存在任务本地运行说明 `tmp/eval-authoring/run_environment.json`，不作为证据身份。

已读取主要正文、表格与图示。DOCX 使用原生 XML 子元素位置，已有 python-docx 交叉核对；PDF 使用 pdfplumber 0.11.9 的真实页面/bbox，并用 pypdf 6.10.0 交叉提取，Poppler 渲染全部页面核对布局。实际版本、逐篇核对数和页几何见 `extraction_audit.json` 与清单。PDF 坐标为左上角原点的点坐标 `x0,top,x1,bottom`；本批全部 rotation=0、cropbox=mediabox，没有额外裁切变换。

长标识符的单元格内换行保留，不静默拼写修复。关系与顺序标注依赖明确正文或已核对图示，不由节点提取顺序推断。源码依据附录和导读中的生产文件索引不作为正文证据；仅保留必要版本声明。原文块中的资料日期行仅作版本元数据，未作为业务答案依据。

## 数量与划分

| 类别 | 总数 | dev | test |
|---|---:|---:|---:|
| fact | 15 | 10 | 5 |
| operation | 15 | 10 | 5 |
| cross_document | 10 | 6 | 4 |
| status | 10 | 7 | 3 |
| boundary | 10 | 7 | 3 |
| 合计 | 60 | 40 | 20 |

状态为 answered 50、insufficient_evidence 4、out_of_scope 3、clarify 3。boundary 在 dev/test 内分别为 3/1、2/1、2/1。没有 partial。answered 中 33 题在 dev、17 题在 test。

正向证据覆盖 29 份文档，包含全部 6 份 PDF；43 道 answered 题含需要准确保留的标识符。导读 DOC-00 已阅读、记录版本，未为凑覆盖强行编写目录题。

| answered 主专题 | 题数 |
|---|---:|
| overview_initialization | 6 |
| phone_performance | 5 |
| camera | 10 |
| registry_state | 7 |
| field_selection_overlay | 6 |
| hotspot_detection | 3 |
| export_share | 6 |
| host_build_maintenance | 4 |
| phase2_verification | 3 |

这些是文档支持的合成任务，没有真实用户日志分布或生产效益含义。

先按主要意图、决定性事实和适用条件建立 60 个问题族，每族一个代表。类别优先级为 boundary > status > cross_document > operation > fact。再按 category 分层，boundary 再按子状态分层。种子固定为 20261104：计算 `SHA256(UTF8(str(seed) + ":" + family_id))`，每层按摘要、family_id 升序，前指定 dev 配额入 dev，其他入 test。算法实现见校验器 `allocation()`，排序键、名次、分配与分组理由见 `split_manifest.json`。

两个 split 共享原知识文档；分离的是问题族。生成 Agent 为标注与校验读取过 test，不能声称严格盲测。人工批准后，方案开发只使用 dev；test 冻结后用于最终验收。未经审核两者均为草稿。

## 文件与字段

| 文件 | 用途 |
|---|---|
| corpus_manifest.json | 真实文件身份、摘要、声明版本、提取问题与草稿状态 |
| source_blocks.jsonl | 原生位置可回查的正文、表格和图示文字块 |
| dev.jsonl / test.jsonl | 按问题族划分的完整逐题标注 |
| dataset.schema.json | case 的必填、类型、枚举、条件与禁止额外字段约束 |
| split_manifest.json | 分层配额、种子、族理由、排序键与可复现分配 |
| review_queue.jsonl | 六份 PDF 的具体提取边界；当前均为非阻断记录 |
| review_checklist.md | 必须由人完成的逐题语义审核步骤与记录方法 |
| validate_dataset.py | 本数据封闭契约、来源、引用、划分及配额检查 |
| validation_report.json | 最近一次真实校验结果与剩余人工事项 |
| validator_self_test.json | 临时副本故障注入自测结果，不含 test 题目正文 |
| self_test_validator.py | 自测的可复现实现 |
| extraction_audit.json | 本次 Agent 的读取、原生位置和 PDF 视觉核对记录 |

case 的顶层字段全部固定，完整结构以 schema 为准。`required_points` 是必答事实/必要步骤；`critical` 表示遗漏或答反会误导。`required_literals` 大小写敏感。`forbidden_claims` 记录具体错误或未经支持的断言；没有直接反证时 `evidence_ids=[]`，表示不能凭资料断言，不表示现实中已经证伪。

`support_sets` 的内层为 AND、外层为 OR：一个集合内所有 G 引用都满足，才算该集合支持；任一完整集合满足即可覆盖该要点。answered 仅含 support 证据，全部被要点引用。`scope` 只解释不足证据的核对范围；`disambiguation` 只解释追问分支；两者都不是正向检索 gold。

quote 是 `source_blocks.text[char_start:char_end]` 的非空连续逐字片段，按 Python Unicode 字符计数，不按字节。跨行、跨单元格需要多个 G 引用。没有把 Milvus chunk_id、索引 generation、窗口或运行时 E1/E2 固化为 gold 身份。

`absence_check` 只用于 insufficient_evidence，说明本套资料缺少的具体事实与全文检查范围，不证明全部外部资料没有答案。`clarification` 只缺一个必要条件，保存恰好两个有来源、会产生不同回答的解释；不按追问句逐字评分。

`extraction_verified=true` 表示 Agent 已核对提取与原件；`machine_checked=true` 表示对应静态检查实际通过。这两个标志都不是人工语义审核。所有 `human_status` 保持 pending，审批人/时间为 null。schema 为未来人工流程保留 approved/rejected，但本次草稿校验器会拒绝它们；正式发布检查属于后续任务。

## 离线运行

从仓库根目录执行。使用本机已具备 pdfplumber 的解释器：

```powershell
# 使用本机已安装 pdfplumber 的 Python
python -X utf8 evaluation/debug-business-v1-review/validate_dataset.py --dataset-dir evaluation/debug-business-v1-review --corpus-root note --mark-machine-checked
python -X utf8 evaluation/debug-business-v1-review/validate_dataset.py --dataset-dir evaluation/debug-business-v1-review --corpus-root note
python -X utf8 evaluation/debug-business-v1-review/self_test_validator.py --dataset-dir evaluation/debug-business-v1-review --corpus-root note
```

移到其他环境后，使用已具备 pdfplumber 的 Python 运行同样参数即可；缺少本地 PDF 工具时记录读取缺口，不能跳过核对并宣称通过。本次未安装新依赖。校验器只对本数据使用的契约关键字实现检查，不是完整 JSON Schema 标准解释器。`--write-schema` 仅用于从内置契约重建 schema；正常校验不需要此选项。

首次允许 `machine_checked=false`。`--mark-machine-checked` 只有在来源/跨文件检查通过且该记录没有静态错误时才设为 true；人工字段始终不改。标记更新后必须再运行不带该选项的校验，确保最终文件再次检查。校验会更新清单草稿状态与报告，不会修改源文档。

A 组检查格式、身份、原生位置、精确引用、角色/要点/禁止项关联、独立编号、split 复现和草稿人工状态；B 组检查 30 份输入、阅读阻断、60/40/20 与细分配额和覆盖。退出码为 A 失败=1，A 通过但 B 失败=2，两组通过=0。人工 pending 本身不导致程序失败。

`corpus_digest` 的复算使用按 doc_id 排序、每项仅含 doc_id 和 sha256 的数组，`json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` UTF-8 编码后计算 SHA-256，见 `digest()`。

自测只在任务临时目录副本里故意损坏记录；校验器至少覆盖重复 case_id、跨 split family_id、错误 quote、伪造原始文件摘要、悬空 G 和配额不足，另检查重复 JSON 键、BOM、额外字段、错误类型、越界页码、未核实证据及越权人工审批。结果见自测报告。自测通过只证明列出的故障被检出。

## 后续评分口径

本次没有系统输出，不生成准确率、召回提升、时延或费用分数。

只有 50 道 answered 题参与正向检索分母。若未来有效题减少，必须报告实际分母和缺口。设前 K 结果映射回同版本原文后的命中证据集合为 H：

- Hit@K：H 至少命中一段正向 gold 为 1，否则 0；scope/disambiguation 不计。
- MRR@K：首个正向 gold 命中排名 r≤K 时为 1/r；未命中为 0。
- EvidenceCoverage@K：存在一个 support_set 完整包含于 H 的要点数 / 全部必答点数。AND 集合只命中一部分不能算覆盖。
- AllEvidenceCovered@K：所有要点各至少满足一个完整 support_set 才为 1。

整体可按有效题做宏平均，并按类别/专题报告分组。EvidenceCoverage 是本项目定义的必答点证据覆盖率，不冒充标准逐块 Recall@K。增加 Recall/NDCG 时需另外定义证据单位、替代来源、相关等级与分母。人工还要检查是否遗漏充分的替代来源。

本标注不绑定切片。后续执行器必须实现并验证“检索片段→同版本原文跨度”的映射和完整覆盖判定；同文件名或一个字符的重叠不能算充分支持。跨度合并、跨片段覆盖、父片段扩展和别名处理须在执行器中明确。本次没有实现该运行时映射或检索评分器。

原始各路召回、融合后、rerank 后、父片段扩展后必须分别说明阶段与 K，不能混用一个 TopK。系统答案按必答事实和必要顺序判断，允许表达不同，不以整段字符串相同为唯一标准。标识符准确不能代替语义正确；分别报告要点覆盖、critical 错漏、forbidden_claims 和引用支持。

程序只能验证结构与绑定，不能证明引文语义足以支持结论；语义审核由人完成，或后续使用经人工校准的模型评分器。insufficient_evidence、out_of_scope、clarify 单独评价状态及 response_requirements，不强算正向召回。服务错误、超时、预算拒绝和接口异常不能算正确拒答，也不能从结果中静默删除。

## 审核与更新

当前没有已知阻断冲突；六条 PDF 提取边界记录均保留具体位置。全部 60 题仍需人工检查事实、替代证据、近重复、跨文档必要性、追问必要性及图表关系。校验器的文档数量检查不能证明跨文档“缺一不可”。详见人工清单。

禁止将本目录或任务 authoring 临时数据交给知识库入库流程。题目、答案、必答点、证据标注不得生成检索伪文档或进入摘要库。没有调用被测 RAG 来选题、反推答案或调 test。

人工审批由真实审核人另行填写，正式批准时再生成批准记录和冻结标识。语料、题目或证据变更时建立新数据版本并保留旧版与变更理由；比较方案必须在同一冻结版本重跑。后续重新生成候选应使用同级带时间戳目录，不能覆盖已交付或已批准版本。
