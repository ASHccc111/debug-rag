# Milvus 本机部署（P0）

- 服务镜像：`milvusdb/milvus:v2.6.4`；Python SDK：`pymilvus==2.6.2`。
- 官方版本配对：[v2.6.4 发布说明](https://github.com/milvus-io/milvus/releases/tag/v2.6.4)。
- 部署参考：[官方 embedded standalone 脚本](https://github.com/milvus-io/milvus/blob/v2.6.4/scripts/standalone_embed.sh)。没有直接执行该脚本。
- 采用内嵌 etcd、本地对象存储，减少笔记本上独立服务的数量。官方脚本中的旧镜像 tag 已显式改为 2.6.4，以真实验收为准。
- 只开放 `127.0.0.1:19530`，不对宿主机开放内嵌 etcd 或管理端口。
- 数据保存在 Compose 命名卷 `debug-rag-p0_milvus-data`。普通 stop/restart 或重建容器不删除数据；不要使用 `down -v` 或卷清理命令。
- 初次尝试官方三容器模板时，MinIO 镜像拉取失败，因此改用官方也支持的单容器方式；没有更换数据库或修改 Docker 全局镜像配置。

从项目根目录运行：

```powershell
docker compose -f infra/milvus/compose.yaml up -d --wait --wait-timeout 180
docker compose -f infra/milvus/compose.yaml ps
docker compose -f infra/milvus/compose.yaml logs --tail 100 standalone
docker compose -f infra/milvus/compose.yaml stop
```

应用当前在宿主机运行，因此连接 `http://127.0.0.1:19530`。后续把应用加入 Compose 时，容器内应改用 `http://standalone:19530`，不能继续连接容器自身的 localhost。
