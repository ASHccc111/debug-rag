import math


class FakeEmbedder:
    identity = {"model": "fake-test-only", "dimension": 3, "revision": "1"}

    def windows(self, text):
        return [(i, min(len(text), i + 180)) for i in range(0, len(text), 180)]

    def encode(self, texts, query=False):
        result = []
        for text in texts:
            vector = [float(text.count(word)) + 0.01 for word in ("相机", "文件", "悬浮")]
            norm = math.sqrt(sum(x * x for x in vector))
            result.append([x / norm for x in vector])
        return result


class FakeVectors:
    def __init__(self):
        self.collections = {}
        self.fail_validation = False
        self.foreign_hit = False

    def build(self, name, rows, dimension):
        self.collections[name] = rows

    def validate(self, name, rows, dimension):
        if self.fail_validation:
            raise RuntimeError("injected vector visibility failure")
        assert self.collections[name] == rows

    def search(self, name, vector, generation_id, kb_id, limit=5, delivered_only=True):
        rows = [
            r
            for r in self.collections[name]
            if not delivered_only or r["feature_status"] == "delivered"
        ]
        ranked = sorted(rows, key=lambda r: -sum(x * y for x, y in zip(r["dense"], vector)))
        return [
            {
                "representation_id": r["id"],
                "chunk_id": r["chunk_id"],
                "revision_id": r["revision_id"],
                "kb_id": r["kb_id"],
                "generation_id": "foreign" if self.foreign_hit else r["generation_id"],
                "score": sum(x * y for x, y in zip(r["dense"], vector)),
            }
            for r in ranked[:limit]
        ]
