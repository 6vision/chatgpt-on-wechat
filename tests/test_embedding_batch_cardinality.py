import pytest
from agent.memory.embedding.provider import OpenAIEmbeddingProvider

def item(index):
    return {"index": index, "embedding": [float(index or 0), 1.0]}

@pytest.mark.parametrize("data", [[item(0)], [], [item(0), item(0)], [item(0), item(2)], [item(0), {"embedding": [1.0]}], [item("0"), item("1")]])
def test_invalid_batch_refuses_silent_chunk_loss_or_misalignment(monkeypatch, data):
    provider = OpenAIEmbeddingProvider(model="test", api_key="local-test")
    monkeypatch.setattr(provider, "_call_api", lambda texts: {"data": data})
    with pytest.raises(ValueError, match="Embedding batch"):
        provider.embed_batch(["first chunk", "second chunk"])

def test_complete_batch_maps_each_vector_to_its_text(monkeypatch):
    provider = OpenAIEmbeddingProvider(model="test", api_key="local-test")
    monkeypatch.setattr(provider, "_call_api", lambda texts: {"data": [item(1), item(0)]})
    assert provider.embed_batch(["first", "second"]) == [[0.0, 1.0], [1.0, 1.0]]
