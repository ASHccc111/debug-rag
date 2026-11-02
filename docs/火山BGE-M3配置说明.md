# 火山引擎 BGE-M3 配置入口

核对日期：2026-11-02。用户已创建火山引擎 API Key，现在准备接口和本机配置。本轮只补配置校验，不执行收费请求，不切换已有索引，也没有完成远程向量适配器。

## 北京地域填什么

打开项目根目录 `.env`，填写：

```dotenv
RAG_VIKING_API_KEY=仅在本机填写你的火山APIKey
RAG_VIKING_EMBEDDING_ENDPOINT=https://api-vikingdb.vikingdb.cn-beijing.volces.com/api/vikingdb/embedding
RAG_VIKING_EMBEDDING_MODEL=bge-m3
```

这三个字段已加入 Settings 与 `.env.example`；本机 `.env` 追加缺少的字段，已有密钥和配置不覆盖。不要把密钥填到 `.env.example`、百炼字段或聊天里。

## 地址从哪里来

官方 [数据面调用说明](https://docs.volcengine.com/docs/vector-database-vikingdb/data-surface-api-call-flow?lang=en) 的北京公网 Host 是 `api-vikingdb.vikingdb.cn-beijing.volces.com`，Embedding 路径为 `/api/vikingdb/embedding`，请求使用 `Authorization: Bearer <API Key>`。

地址是地域共享的服务入口，不需要生成一个个人推理接入点。服务开通状态和 Key 的 VikingDB 权限仍需实际验证。若使用上海或广州地域，应使用 [SDK 初始化与地域说明](https://docs.volcengine.com/docs/vector-database-vikingdb/installation-and-client-initialization-4?lang=en) 中对应的 Host，模型权限与服务也需对应地域。

新数据面接口采用 `dense_model`、`sparse_model` 和 `data` 结构。当前文档中另有旧 `embedding_v2` 接口及 `EmbModel` SDK 写法，不能只换地址后混用请求格式。后续适配会在两种模型配置中均选择 BGE-M3，避免误用官方示例中的 Doubao dense＋BGE sparse 组合。

## 填完后的状态

填写完成不等于远程调用已经通过，也不会自动把本地 512 维 bge-small 向量换成 1024 维 BGE-M3。当前 main/components 继续使用本地编码器。

下一步先用独立模拟文本验证服务、权限、dense/sparse 格式、用量和费用；再接编码适配、Milvus sparse 字段与召回，并构建独立的新索引。当前已通过的演示索引继续保留，远程服务没通过时不发布替换。
