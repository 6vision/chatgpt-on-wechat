from agent.knowledge.service import KnowledgeService

def test_directory_cycle_does_not_break_knowledge_listing(tmp_path):
    root = tmp_path / "knowledge"
    (root / "notes").mkdir(parents=True)
    (root / "notes/doc.md").write_text("# Local document")
    (root / "notes/loop").symlink_to(root, target_is_directory=True)
    svc = KnowledgeService(str(tmp_path))
    tree = svc.list_tree()
    assert tree["stats"]["pages"] == 1
    assert tree["tree"][0]["children"] == []

def test_external_symlink_titles_are_not_exposed(tmp_path):
    root = tmp_path / "knowledge"
    root.mkdir()
    external = tmp_path / "outside"
    external.mkdir()
    (external / "secret.md").write_text("# Private title")
    (root / "external").symlink_to(external, target_is_directory=True)
    (root / "secret.md").symlink_to(external / "secret.md")
    tree = KnowledgeService(str(tmp_path)).list_tree()
    assert tree["tree"] == []
    assert tree["root_files"] == []
