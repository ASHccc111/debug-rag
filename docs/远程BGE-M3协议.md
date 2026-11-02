# 远程 BGE-M3 编码协议与当前边界

核对日期：2026-11-02。本文描述新增适配器和官方公开协议；没有发起新的真实付费调用。

## 数据如何流动

原文子片段或完整查询 → `VikingEmbedder.encode_hybrid()` → 火山编码服务 → dense 与 sparse → 本机 Milvus。VikingDB 只承担远程编码，本项目不创建云数据库或云索引。

请求为 `POST /api/vikingdb/embedding`，通过本机密钥 Bearer 鉴权；不在请求日志中输出凭据或正文。

```json
{
  "dense_model": {"name": "bge-m3", "version": "default", "dim": 1024},
  "sparse_model": {"name": "bge-m3", "version": "default"},
  "data": [{"text": "独立模拟文本"}]
}
```

成功响应 `code` 必须为 `Success`；编码结果位于 `result.data`，按输入顺序返回。每个结果包含 `dense` 数组和 `sparse` 字典。没有可依赖的 `index` 字段，因此适配器严格检查数量，再按位置关联原文。请求和响应字段依据[官方 Python SDK 模型](https://github.com/volcengine/vikingdb-python-sdk/blob/main/vikingdb/vector/models/embedding.py)，路径及认证依据[官方数据面说明](https://docs.volcengine.com/docs/vector-database-vikingdb/data-surface-api-call-flow?lang=en)。

## 表征与截断

适配器严格检查 1024 维、有限且非零 dense，并统一 L2 归一化。Sparse 必须是非空的字符串词项到正有限权重的映射。字符串键是服务返回的词项身份，不能假定为整数，也不把词在本句话中的位置当作维度。本机索引负责保存不碰撞的词项到整数映射，并与 generation 一起校验。

BGE-M3 的公开上限为 8192 tokens，超长会被服务截断。适配器采取保守短字符窗，额外限制 UTF-8 字节数与特殊 token 余量，拒绝超窗编码，不依赖静默截断。默认每批 4 条，不自动重试；新接口的公开批量硬上限尚未核实，不能照搬旧 `embedding_v2` 的限制。模型信息见[官方 BGE-M3 说明](https://docs.volcengine.com/docs/vector-database-vikingdb/embedding-v2-1?lang=zh)。

`default` 是提供方服务版本别名，不能证明底层权重不可变。`viking_embedding_revision` 是本项目人工维护的配置修订标识，不是伪造的模型权重 revision。服务改变后应更新配置标识，重新建立独立 generation；旧本地 bge-small 索引保持独立。

## 费用与失败

适配器复用项目共享 `BudgetLedger`，在网络请求之前执行外部调用开关、密钥、输入大小、核价有效期和月预算检查。默认不具备可用价格上界，因此不能因填入密钥而自动付费。

当前公开协议将 `result.token_usage` 定义为任意字典，尚未核实真实内层结构、dense/sparse 联合编码的计费方式，以及具体账户的费用。启用前必须人工核对一个请求在所设批量与输入限制内的**最大费用上界**，填写 `viking_request_upper_bound_cny`、`viking_price_verified_on`、`viking_price_valid_through`。它必须覆盖整个请求，而不是一个文本、一千 tokens 或单种向量。

每个请求先按此上界预留；预算台账中的该适配器计价单位是“请求”，不是已观测 token。未知用量保持 `unknown`，保留全部预留并跨月计入额度，不按照零费用结算。即使响应带 token 统计，也不会在费率和结构未核实前推算实际扣款。轨迹只保留可识别的非负整数统计，禁止回显供应商任意文本。后续真实联调与账单核实后，才可以实现更精确的结算。

超时、限流、非法 JSON、数量错误、空或非法向量都返回维护过的错误码，不包含原始响应体、正文、密钥或底层异常文本。失败批次保留费用预留；前面已成功的批次同样有独立台账。协议模拟测试只能证明这些软件行为，不能当作远程服务已验证或检索质量提升的证据。
