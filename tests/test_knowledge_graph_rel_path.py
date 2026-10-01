"""Knowledge graph paths must be "/"-separated on every platform.

The web console consumes ``build_graph()`` as forward-slash paths: it splits
the category off the first segment to pick a node color, and it looks a node
up in the file tree by ``data-path`` when a node is clicked (and expands its
ancestor groups only when the path ``includes("/")``). ``build_graph()`` built
those strings with ``str(relative_to(...))``, which keeps the OS separator, so
on Windows every nested page came back as ``concepts\\rag.md``.
"""

import os

import pytest

from agent.knowledge.service import KnowledgeService


class FakeStorage:
    def delete_by_path(self, path):
        pass


class FakeMemoryManager:
    def __init__(self):
        self.storage = FakeStorage()

    def mark_dirty(self):
        pass

    async def sync(self):
        pass


def make_service(tmp_path):
    (tmp_path / "knowledge").mkdir()
    return KnowledgeService(str(tmp_path), FakeMemoryManager())


def make_pages(root):
    (root / "concepts").mkdir()
    (root / "entities").mkdir()
    (root / "concepts/rag.md").write_text("# RAG\n", encoding="utf-8")
    (root / "entities/deepseek.md").write_text(
        "# DeepSeek\nsee [RAG](../concepts/rag.md)\n", encoding="utf-8"
    )
    (root / "notes.md").write_text("# Notes\n", encoding="utf-8")


def test_nested_pages_keep_their_category_and_forward_slash_ids(tmp_path):
    svc = make_service(tmp_path)
    make_pages(tmp_path / "knowledge")

    graph = svc.build_graph()
    nodes = {n["id"]: n for n in graph["nodes"]}

    assert set(nodes) == {"concepts/rag.md", "entities/deepseek.md", "notes.md"}
    assert nodes["concepts/rag.md"]["category"] == "concepts"
    assert nodes["entities/deepseek.md"]["category"] == "entities"
    # A page directly under knowledge/ has no category segment.
    assert nodes["notes.md"]["category"] == "root"
    for node_id in nodes:
        assert os.sep not in node_id or os.sep == "/"


def test_graph_links_are_named_like_their_nodes(tmp_path):
    svc = make_service(tmp_path)
    make_pages(tmp_path / "knowledge")

    graph = svc.build_graph()
    node_ids = {n["id"] for n in graph["nodes"]}
    endpoints = {l["source"] for l in graph["links"]} | {l["target"] for l in graph["links"]}

    assert ("entities/deepseek.md", "concepts/rag.md") in {
        (l["source"], l["target"]) for l in graph["links"]
    }
    # An edge that points at a string no node carries leaves an orphan in the
    # rendered graph, so both ends must be node ids.
    assert endpoints <= node_ids


def test_graph_ids_match_the_paths_the_file_tree_advertises(tmp_path):
    """A clicked graph node is opened by its id, so the id has to be a path
    the tree already uses (``list_tree`` builds those with "/")."""
    svc = make_service(tmp_path)
    make_pages(tmp_path / "knowledge")

    tree_paths = set()

    def walk(nodes, prefix):
        for node in nodes:
            here = f"{prefix}/{node['dir']}" if prefix else node["dir"]
            for f in node["files"]:
                if f["name"] in KnowledgeService.PROTECTED_FILES:
                    continue
                tree_paths.add(f"{here}/{f['name']}")
            walk(node["children"], here)

    tree = svc.list_tree()
    for f in tree["root_files"]:
        if f["name"] not in KnowledgeService.PROTECTED_FILES:
            tree_paths.add(f["name"])
    walk(tree["tree"], "")

    graph_ids = {n["id"] for n in svc.build_graph()["nodes"]}
    assert graph_ids == tree_paths


def test_protected_root_files_stay_out_of_the_graph(tmp_path):
    svc = make_service(tmp_path)
    root = tmp_path / "knowledge"
    make_pages(root)
    (root / "index.md").write_text("# Index\n- [Notes](./notes.md)\n", encoding="utf-8")
    (root / "log.md").write_text("# Log\n", encoding="utf-8")

    graph = svc.build_graph()
    ids = {n["id"] for n in graph["nodes"]}
    assert "index.md" not in ids
    assert "log.md" not in ids
    assert "notes.md" in ids


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
