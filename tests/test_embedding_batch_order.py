# encoding:utf-8
"""
Regression tests for input-order alignment of batched embeddings.

`embed_batch` documents "Order of returned vectors matches the input order", and
every caller depends on that: memory sync zips the returned vectors onto the
chunk texts positionally (`zip(chunks, embeddings)` in MemoryManager), so a
vector that lands against the wrong text is stored as that chunk's embedding and
silently poisons semantic search for it — the count still matches, so nothing
raises.

The /embeddings response carries an explicit `index` per item, its position in
the request, precisely so a client does not have to assume the reply arrives in
order. The batch loop ignored that field and consumed `data` in response order,
so any proxy or gateway that reordered items returned vectors bound to the wrong
texts.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.embedding.provider import OpenAIEmbeddingProvider


class ScriptedProvider(OpenAIEmbeddingProvider):
    """Answers each /embeddings call from a fixed script of responses.

    The last item of a text gets a distinctive vector, so a mis-bound batch is
    visible as a wrong vector rather than merely a wrong order.
    """

    def __init__(self, responses, max_batch_size=64):
        super().__init__(
            model="text-embedding-3-small",
            api_key="test-key",
            max_batch_size=max_batch_size,
        )
        self.responses = list(responses)
        self.calls = []

    def _call_api(self, input_data):
        texts = [input_data] if isinstance(input_data, str) else list(input_data)
        self.calls.append(texts)
        return self.responses.pop(0)


def _item(index, vector):
    """One /embeddings response item, as the API returns it."""
    return {"object": "embedding", "index": index, "embedding": vector}


class TestEmbedBatchResponseOrder(unittest.TestCase):
    """Returned vectors line up with the input texts, whatever order the
    response used."""

    def _texts(self, count):
        return [f"text {i}" for i in range(count)]

    def _vector(self, index):
        """A vector that identifies which text it was computed for."""
        return [float(index), 0.0, 1.0]

    def test_out_of_order_response_is_reordered_by_index(self):
        texts = self._texts(3)
        provider = ScriptedProvider([{
            "data": [
                _item(2, self._vector(2)),
                _item(0, self._vector(0)),
                _item(1, self._vector(1)),
            ]
        }])

        vectors = provider.embed_batch(texts)

        self.assertEqual(vectors, [self._vector(0), self._vector(1), self._vector(2)])

    def test_reversed_response_is_reordered_by_index(self):
        texts = self._texts(3)
        provider = ScriptedProvider([{
            "data": [_item(i, self._vector(i)) for i in (2, 1, 0)]
        }])

        vectors = provider.embed_batch(texts)

        self.assertEqual(vectors, [self._vector(0), self._vector(1), self._vector(2)])

    def test_alignment_holds_across_paginated_batches(self):
        # embed_batch splits by max_batch_size, so every page carries its own
        # index space starting at 0 — page 2's index 0 is text 2, not text 0.
        texts = self._texts(5)
        provider = ScriptedProvider([
            {"data": [_item(1, self._vector(1)), _item(0, self._vector(0))]},
            {"data": [_item(1, self._vector(3)), _item(0, self._vector(2))]},
            {"data": [_item(0, self._vector(4))]},
        ], max_batch_size=2)

        vectors = provider.embed_batch(texts)

        self.assertEqual(provider.calls, [texts[0:2], texts[2:4], texts[4:5]])
        self.assertEqual(vectors, [self._vector(i) for i in range(5)])

    def test_in_order_response_is_unchanged(self):
        texts = self._texts(3)
        provider = ScriptedProvider([{
            "data": [_item(i, self._vector(i)) for i in range(3)]
        }])

        self.assertEqual(
            provider.embed_batch(texts),
            [self._vector(0), self._vector(1), self._vector(2)],
        )

    def test_response_without_index_fields_keeps_response_order(self):
        # A provider that omits `index` leaves nothing to sort by; the answer
        # must stay what it always was rather than raising or reordering.
        texts = self._texts(2)
        provider = ScriptedProvider([{
            "data": [
                {"object": "embedding", "embedding": self._vector(0)},
                {"object": "embedding", "embedding": self._vector(1)},
            ]
        }])

        self.assertEqual(provider.embed_batch(texts), [self._vector(0), self._vector(1)])

    def test_empty_input_short_circuits(self):
        provider = ScriptedProvider([])

        self.assertEqual(provider.embed_batch([]), [])
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
