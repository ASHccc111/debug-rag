"""Generation-isolated FLAT/COSINE collections. No automatic collection deletion."""

import math
from contextlib import contextmanager

from debug_rag.diagnostics import new_milvus_client
from debug_rag.errors import RagError


class MilvusVectors:
    def __init__(self, settings):
        self.settings = settings

    @contextmanager
    def client(self):
        client = None
        try:
            client = new_milvus_client(self.settings)
            yield client
        except RagError:
            raise
        except Exception:
            raise RagError(
                "vector_service_unavailable", "Milvus 操作失败，请检查容器和索引状态。"
            ) from None
        finally:
            if client is not None:
                client.close()

    def build(self, name: str, rows: list[dict], dimension: int):
        return self._build(name, rows, dimension, hybrid=False)

    def build_hybrid(self, name: str, rows: list[dict], dimension: int):
        return self._build(name, rows, dimension, hybrid=True)

    def _build(self, name, rows, dimension, *, hybrid):
        from pymilvus import DataType, MilvusClient

        with self.client() as client:
            if client.has_collection(name):
                raise RagError("collection_collision", "新索引名称已存在，未覆盖已有集合。", 409)
            schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=100)
            for field in ("chunk_id", "revision_id", "kb_id", "generation_id", "app_snapshot"):
                schema.add_field(field, DataType.VARCHAR, max_length=100)
            schema.add_field("feature_status", DataType.VARCHAR, max_length=30)
            schema.add_field("data_kind", DataType.VARCHAR, max_length=20)
            schema.add_field("dense", DataType.FLOAT_VECTOR, dim=dimension)
            if hybrid:
                schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
            indexes = client.prepare_index_params()
            indexes.add_index(field_name="dense", index_type="FLAT", metric_type="COSINE")
            if hybrid:
                indexes.add_index(
                    field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="IP"
                )
            client.create_collection(
                collection_name=name,
                schema=schema,
                index_params=indexes,
                consistency_level="Strong",
            )
            for start in range(0, len(rows), 100):
                client.insert(collection_name=name, data=rows[start : start + 100])
            client.flush(collection_name=name)
            client.load_collection(collection_name=name)

    def validate(self, name: str, expected: list[dict], dimension: int):
        """Check schema, exact scalar membership and read-after-write visibility."""
        return self._validate(name, expected, dimension, hybrid=False)

    def validate_hybrid(self, name: str, expected: list[dict], dimension: int):
        """Verify both vector payloads as well as all source mappings before publication."""
        return self._validate(name, expected, dimension, hybrid=True)

    def validate_existing(self, name: str, expected: list[dict], dimension: int, *, hybrid=False):
        """Recheck an immutable generation without calling an embedding provider."""
        return self._validate(name, expected, dimension, hybrid=hybrid, payload_expected=False)

    def _validate(self, name, expected, dimension, *, hybrid, payload_expected=True):
        with self.client() as client:
            description = client.describe_collection(name)
            field = next((f for f in description["fields"] if f["name"] == "dense"), {})
            if int(field.get("params", {}).get("dim", -1)) != dimension:
                raise RagError("index_dimension_mismatch", "索引向量维度不匹配。", 409)
            if hybrid:
                from pymilvus import DataType

                sparse_field = next((f for f in description["fields"] if f["name"] == "sparse"), {})
                if sparse_field.get("type") != DataType.SPARSE_FLOAT_VECTOR:
                    raise RagError("index_sparse_schema_mismatch", "稀疏索引字段不匹配。", 409)
            count = client.query(
                collection_name=name,
                filter="",
                output_fields=["count(*)"],
                consistency_level="Strong",
            )[0]["count(*)"]
            if count != len(expected):
                raise RagError("index_count_mismatch", "索引记录数量不匹配，未发布。", 409)
            fields = [
                "id",
                "chunk_id",
                "revision_id",
                "kb_id",
                "generation_id",
                "app_snapshot",
                "feature_status",
                "data_kind",
            ]
            for start in range(0, len(expected), 100):
                batch = expected[start : start + 100]
                found = client.get(
                    collection_name=name,
                    ids=[r["id"] for r in batch],
                    output_fields=fields + (["dense", "sparse"] if hybrid else []),
                    consistency_level="Strong",
                )
                actual = {r["id"]: {f: r[f] for f in fields} for r in found}
                wanted = {r["id"]: {f: r[f] for f in fields} for r in batch}
                if actual != wanted:
                    raise RagError("index_mapping_mismatch", "向量与原文映射不完整，未发布。", 409)
                if hybrid:
                    expected_by_id = {row["id"]: row for row in batch}
                    for record in found:
                        dense, sparse = record.get("dense"), record.get("sparse")
                        if (
                            not isinstance(dense, list)
                            or len(dense) != dimension
                            or any(
                                isinstance(value, bool)
                                or not isinstance(value, (int, float))
                                or not math.isfinite(value)
                                for value in dense
                            )
                            or sum(value * value for value in dense) <= 0
                            or not isinstance(sparse, dict)
                            or not sparse
                            or any(
                                type(key) is not int
                                or key < 0
                                or isinstance(weight, bool)
                                or not isinstance(weight, (int, float))
                                or not math.isfinite(weight)
                                or weight <= 0
                                for key, weight in sparse.items()
                            )
                        ):
                            raise RagError(
                                "index_vector_payload_invalid", "索引向量内容无效。", 409
                            )
                        if payload_expected:
                            wanted_row = expected_by_id[record["id"]]
                            if (
                                any(
                                    not math.isclose(x, y, rel_tol=1e-5, abs_tol=1e-7)
                                    for x, y in zip(dense, wanted_row["dense"])
                                )
                                or sparse.keys() != wanted_row["sparse"].keys()
                                or any(
                                    not math.isclose(
                                        weight,
                                        wanted_row["sparse"][key],
                                        rel_tol=1e-5,
                                        abs_tol=1e-7,
                                    )
                                    for key, weight in sparse.items()
                                )
                            ):
                                raise RagError(
                                    "index_vector_payload_mismatch",
                                    "索引向量与编码结果不一致。",
                                    409,
                                )

    def search(
        self,
        name: str,
        vector: list[float],
        generation_id: str,
        kb_id: str,
        limit: int = 5,
        delivered_only: bool = True,
    ) -> list[dict]:
        return self._search(name, vector, generation_id, kb_id, limit, delivered_only, sparse=False)

    def search_sparse(
        self,
        name: str,
        vector: dict[int, float],
        generation_id: str,
        kb_id: str,
        limit: int = 5,
        delivered_only: bool = True,
    ) -> list[dict]:
        if not vector:
            return []
        return self._search(name, vector, generation_id, kb_id, limit, delivered_only, sparse=True)

    def _search(self, name, vector, generation_id, kb_id, limit, delivered_only, *, sparse):
        import json

        # Names/filters never come from model output; JSON quoting handles user KB IDs.
        filters = f"generation_id == {json.dumps(generation_id)} && kb_id == {json.dumps(kb_id)}"
        if delivered_only:
            filters += ' && feature_status == "delivered"'
        with self.client() as client:
            result = client.search(
                collection_name=name,
                data=[vector],
                anns_field="sparse" if sparse else "dense",
                filter=filters,
                limit=limit,
                search_params={"metric_type": "IP" if sparse else "COSINE"},
                output_fields=["chunk_id", "revision_id", "generation_id", "kb_id"],
                consistency_level="Strong",
            )
            return [
                {"representation_id": str(h["id"]), "score": float(h["distance"]), **h["entity"]}
                for h in result[0]
            ]
