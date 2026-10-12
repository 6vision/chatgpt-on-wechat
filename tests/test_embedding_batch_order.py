# encoding:utf-8
"""embed_batch returns vectors in input order, using each response item's `index`."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.embedding.provider import OpenAIEmbeddingProvider


class ScriptedProvider(OpenAIEmbeddingProvider):
    def __init__(self, responses, max_batch_size=64):
        super().__init__(model="text-embedding-3-small", api_key="test-key", max_batch_size=max_batch_size)
        self.responses = list(responses)

    def _call_api(self, input_data):
        return self.responses.pop(0)


def _item(index, vector_id):
    return {"object": "embedding", "index": index, "embedding": [float(vector_id), 0.0, 1.0]}


def test_out_of_order_pages_are_reordered_by_index():
    # Each page has its own index space starting at 0.
    provider = ScriptedProvider([
        {"data": [_item(1, 1), _item(0, 0)]},
        {"data": [_item(1, 3), _item(0, 2)]},
    ], max_batch_size=2)
    vectors = provider.embed_batch([f"text {i}" for i in range(4)])
    assert [v[0] for v in vectors] == [0.0, 1.0, 2.0, 3.0]


def test_items_without_index_keep_response_order():
    data = [_item(0, 0), _item(0, 1)]
    for item in data:
        del item["index"]
    vectors = ScriptedProvider([{"data": data}]).embed_batch(["a", "b"])
    assert [v[0] for v in vectors] == [0.0, 1.0]
