# BGE-M3 远程服务采购调研

核查日期：2026-11-01。范围是公开官方模型页、价格页及接口定义；没有登录采购账号、充值或执行付费推理。价格与可用性仍需在开通时核对。

## 结论与推荐

**同日补充：中国大陆支付与国内平台。**用户进一步要求国内可付款的 BGE-M3 候选，现补查到火山引擎 VikingDB 的 `bge-m3` 接口明确支持 dense/sparse。此前 DeepInfra 推荐只覆盖技术输出能力，不能据此认定付款可行；国内候选的比较见文末补充，尚未改动项目或选定厂商。

当前项目已经有本地 bge-small 的 dense 检索。这里要采购的是未来替换编码器所需的 **BGE-M3 远程 dense＋learned sparse 编码服务**，不是向量数据库，也不是单独的 Reranker。

建议优先试用 **DeepInfra 的 `BAAI/bge-m3-multi-8k` 原生推理接口**。公开页面及其原生接口定义同时列出 dense、sparse 输出，且输入上限为 8192 tokens；本次核查标价为 **0.01 美元/百万输入 tokens**。这使其成为最接近既定路线的候选；还没有凭真实账户响应确认可直接接入。参见 [官方模型/API 页](https://deepinfra.com/BAAI/bge-m3-multi-8k/api)。

如果希望先使用国内服务试验远程 dense，硅基流动也提供 BGE-M3，价格页将普通版本标为免费。但本次未确认其公开接口可返回 learned sparse，不能将其作为完整 dense＋sparse 服务采购。参见 [国内价格页](https://www.siliconflow.cn/pricing)。

## 服务对比

| 平台及型号 | 本次核实到的能力 | 长度与价格 | 对本项目的判断 |
|---|---|---|---|
| DeepInfra `BAAI/bge-m3-multi-8k` | 原生请求定义包含 `dense`、`sparse`、`colbert`，响应定义包含 `embeddings`、`sparse` | 8192 tokens；$0.01/百万输入 tokens | 优先候选，先用少量模拟文本检验实际 sparse 格式 |
| DeepInfra `BAAI/bge-m3-multi` | 同类多表示服务 | **超过 512 tokens 会截断**；$0.01/百万输入 tokens | 不优先，必须另管输入窗口，不能按模型本身的 8K 能力使用 |
| 硅基流动 `BAAI/bge-m3` | 已确认模型在国内价格目录；公开 Embeddings 示例为向量数组，未确认 sparse 输出契约 | 普通版本标为免费；账户限额与实际可调用资格须查控制台 | 可作为远程 dense 候选；完整双表示路线需先向官方核实 |
| Novita `baai/bge-m3` | 官方 `/openai/v1/embeddings` 文档返回 `data[].embedding`，未列出 sparse 开关或返回字段 | 模型页标注 8K；输入 $0.01/百万 tokens | 可提供 dense；当前证据不足以认定满足 dense＋sparse |
| 阿里云百炼 `text-embedding-v4` | DashScope 原生 API 明确支持 `output_type="dense&sparse"` | 费用、地域以该账户对应目录为准，本表不混用不同地域报价 | 国内双表示替代方案，**不是 BGE-M3**；采用前需确认变更模型 |

表格依据：[DeepInfra 8K API](https://deepinfra.com/BAAI/bge-m3-multi-8k/api)、[DeepInfra 512 API](https://deepinfra.com/BAAI/bge-m3-multi/api)、[硅基流动国内价格](https://www.siliconflow.cn/pricing)、[硅基流动公开 Embeddings 规范（国际站）](https://docs.siliconflow.com/en/api-reference/embeddings/create-embeddings)、[Novita 模型页](https://novita.ai/models/model-detail/baai-bge-m3)、[Novita API 规范](https://docs.novita.ai/api-reference/model-apis-llm-create-embeddings)、[百炼原生 API](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api/)。

硅基流动中国站的新版 API 文档本次读取返回错误；国际站规范只能帮助说明公开接口形状，不能替代中国站账户的实际能力确认。没有找到 sparse 契约不等于断言厂商任何产品都不支持；这里只是不将未证实能力算作满足采购要求。

## DeepInfra 接入时具体要核对什么

目标地址为 `https://api.deepinfra.com/v1/inference/BAAI/bge-m3-multi-8k`。查看官方页面时应切换到 **DeepInfra API**，其 OpenAI Embeddings 示例只展示普通 dense 返回。

原生协议定义中，输入文本字段为 `inputs`；`dense` 默认开启，`sparse` 默认关闭，使用双表示时需显式打开；`colbert` 本阶段无需开启。接口定义返回 `embeddings`、`sparse` 和输入 token 用量。

本次进一步读取了同一官方网页内嵌的静态接口定义，而非仅根据模型介绍判断。定义中的 sparse 是数值数组，示例也不足以解释真实词项索引语义。因此接入时仍要核实它是按全局词表展开的权重数组，还是其他压缩格式；确认后转换成 Milvus 接受的非零维度与权重。不能把句内位置当全局词项 ID。

还要验证返回顺序、dense 维度、归一化行为、批量限制、超长行为、限流、用量，以及服务版本能否固定。接口定义不等于已经通过真实调用验收。服务缺少可固定版本时，要明确记录提供方、型号、编码设置与构建批次，不能把新旧模型表示混进同一索引。

## 你需要准备什么

1. 在选定平台注册自己的账号，确认模型可开通；保留准确型号和文档链接。
2. 确认本机访问目标地址的网络、支付方式及最低充值金额。这些账户条件本次没有核实。
3. 创建自己的 API Key，后续仅在本机 `.env` 中配置，不发到聊天或提交仓库。BGE-M3 适配器尚未实现，暂时不虚构一套已经可用的环境变量。
4. 先允许少量模拟文本做接口验证，再安排全库重建和评测。当前仍保持外部调用关闭。

DeepInfra 官方说明服务需绑卡或预付，并可设置消费上限；公开说明未给出本次可确认的最低充值金额。参见 [计费说明](https://deepinfra.com/pricing)。本项目已确认的总预算为每月 50 元人民币，包含生成、重排、改写、重试和评测，不能把 Embedding 报价当作整个项目的费用。

按当前 8K 版公开单价，100 万输入 tokens 的编码费用为 $0.01；这是用量算例，不是月费预测，也没有计入其他服务。建库需发送文档子片段，查询时还要发送问题；切换 BGE-M3 后必须新建索引，现有 bge-small 的 512 维向量不能直接复用。后续远程编码同样受文档外发许可约束。

## Query 改写需要另外买吗

通常不需要。改写使用生成式模型，可以复用回答生成所用的 DeepSeek 账号与 API Key；BGE-M3 负责把文本编码成表示，不负责生成改写后的问题。

本机安全核查只读取配置是否存在，没有输出密钥：

| 项目 | 当前状态 |
|---|---|
| DeepSeek 生成 API 适配器 | 已有，地址 `https://api.deepseek.com/chat/completions` |
| 本机模型配置 | `deepseek-flash` |
| DeepSeek Key 是否配置 | 否 |
| 外部调用是否开启 | 否 |
| Query 改写逻辑 | 后续同日已实现，默认关闭，模拟 API 测试通过 |
| 独立 Reranker | 后续同日已实现百炼适配与链路，真实联调待 API |

采购调研后，用户要求先实现改写和独立重排，相关代码已补齐，见 [接入说明](Query改写与独立重排接入说明.md)。尚未提供 Key、未核价和未完成真实联调仍是事实。填入 Key 后还需显式启用功能并通过预算及许可检查。

目标调用关系：用户问题 → DeepSeek 改写 → 原始/改写问题各由远程 BGE-M3 编码 → Milvus dense/sparse 召回 → 统一融合 → 独立 Reranker → 原文证据 → DeepSeek 生成回答。此处是目标链路，不能计为现有实现。

## 中国大陆支付与新增国内候选

补查日期：2026-11-01，仍仅核查公开官方资料，未注册、充值或付费调用。

| 平台 | BGE-M3 与付款证据 | dense/sparse 判断 |
|---|---|---|
| 火山引擎 VikingDB | `embedding_v2` 文档列出 `bge-m3`、1024 维、8192-token 上限与 dense/sparse 参数；资金文档支持支付宝/微信 | 文档能力匹配，优先核查国内开通条件；还未实际调用 |
| 硅基流动 | `BAAI/bge-m3` 普通版价格页标为免费；官方财务说明支持支付宝/微信充值 | 已知可用作远程 dense 候选；learned sparse 的公开契约尚未确认 |
| PPIO 派欧云 | 官方模型页提供 `baai/bge-m3`，输入标价 ¥0.07/百万 tokens；官方模型服务协议列出支付宝/微信等支付方式 | 公开调用示例为普通 Embeddings，未确认 sparse 开关/返回字段 |
| AutoDL 租服务器后自行部署 | 官方支持支付宝/微信，实例按开机时长计费 | 这是租算力、自建服务；使用官方 FlagEmbedding 可控制两种输出，需要部署与维护，不是现成模型 API |

火山引擎官方说明：[BGE-M3 编码参数](https://docs.volcengine.com/docs/vector-database-vikingdb/embedding-v2-1?lang=zh)、[账户充值方式](https://docs.volcengine.com/docs/billing-center/funding-faq?lang=zh)、[向量库计费](https://docs.volcengine.com/docs/vector-database-vikingdb/billing-of-a-vector-database?lang=en)。其文本向量模型公开标价为 0.0005 元/千 tokens，即 0.5 元/百万 tokens。数据库索引计算与存储另计费，不能把模型单价当作整套云数据库费用。

针对当前项目，应先确认该账号能否**仅使用 Embedding 接口、无需创建云端付费索引**，以及真实响应中两种表示的结构；本次未确认这项开通条件。目标仍是把编码结果交给本机 Milvus，不自动将数据库换成 VikingDB。选型号应为 `bge-m3`；`bge-large-zh-and-m3` 的 dense 使用另一种 BGE 模型，不能当作相同编码空间。

其他官方依据：[硅基流动价格](https://www.siliconflow.cn/pricing)、[硅基流动充值](https://docs.siliconflow.cn/docs/userguide/faqs/misc_finance)、[PPIO 模型页](https://ppio.com/model/embedding/baai/bge-m3)、[PPIO 模型服务协议](https://ppio.com/legal/model-terms-of-service)、[AutoDL 充值与计费](https://www.autodl.com/docs/price/)、[BGE-M3 官方双表示使用方法](https://bge-model.com/bge/bge_m3)。

支付便利优先时可以选择国内平台，但普通 dense API 不能冒充完整 BGE-M3 learned sparse。此次国内调研增加了火山引擎这一能力更匹配的候选，没有执行采购或改写当前模型配置。
