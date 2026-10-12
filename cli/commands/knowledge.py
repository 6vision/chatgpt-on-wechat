"""cow knowledge - Knowledge base management commands."""

import os

import click

from cli.utils import get_knowledge_dir, get_project_root


def _get_knowledge_dir():
    """Resolve the knowledge directory path from config or default."""
    return get_knowledge_dir()


def _get_knowledge_enabled():
    try:
        import sys
        sys.path.insert(0, get_project_root())
        from config import conf
        return conf().get("knowledge", True)
    except Exception:
        return True


@click.group(invoke_without_command=True)
@click.pass_context
def knowledge(ctx):
    """Manage CowAgent knowledge base."""
    if ctx.invoked_subcommand is None:
        click.echo(_stats())


@knowledge.command("list")
def knowledge_list():
    """Display knowledge base file tree."""
    click.echo(_tree())


def _stats() -> str:
    knowledge_dir = _get_knowledge_dir()
    if not os.path.isdir(knowledge_dir):
        return "Knowledge base directory not found."

    enabled = _get_knowledge_enabled()
    total_files = 0
    total_bytes = 0
    cat_count = {}

    for root, dirs, files in os.walk(knowledge_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        rel_root = os.path.relpath(root, knowledge_dir)
        category = rel_root.split(os.sep)[0] if rel_root != "." else "root"
        for f in files:
            if f.lower().endswith(".md") and f not in ("index.md", "log.md"):
                total_files += 1
                total_bytes += os.path.getsize(os.path.join(root, f))
                cat_count[category] = cat_count.get(category, 0) + 1

    status_icon = click.style("enabled", fg="green") if enabled else click.style("disabled", fg="red")
    lines = [
        f"\n  Knowledge Base  [{status_icon}]",
        "",
        f"  Pages:  {total_files}",
        f"  Size:   {total_bytes / 1024:.1f} KB",
        "",
    ]
    if cat_count:
        lines.append("  Categories:")
        for cat in sorted(cat_count.keys()):
            lines.append(f"    {cat}/  ({cat_count[cat]} pages)")
        lines.append("")

    lines.append(f"  Path: {knowledge_dir}")
    lines.append("")
    return "\n".join(lines)


def _tree() -> str:
    knowledge_dir = _get_knowledge_dir()
    if not os.path.isdir(knowledge_dir):
        return "Knowledge base directory not found."

    tree_lines = ["  knowledge/"]

    def scan(directory, is_root=False, ancestors=()):
        names = sorted(os.listdir(directory))
        # Keep directory links bounded to their existing shallow display:
        # recursively following them can revisit a parent indefinitely.
        children = []
        canonical = os.path.normcase(os.path.realpath(directory))
        if (is_root or not os.path.islink(directory)) and canonical not in ancestors:
            for name in names:
                path = os.path.join(directory, name)
                if not name.startswith(".") and os.path.isdir(path):
                    child = scan(path, ancestors=(*ancestors, canonical))
                    children.append((name, child))
        files = [
            name for name in names
            if name.lower().endswith(".md") and not name.startswith(".")
            and os.path.isfile(os.path.join(directory, name))
            and not (is_root and name in ("index.md", "log.md"))
        ]
        count = len(files) + sum(child[2] for _, child in children)
        return children, files, count

    def render(tree, prefix):
        children, files, _ = tree
        max_show = 15
        items = [(name, child) for name, child in children]
        items.extend((name[:-3], None) for name in files[:max_show])
        if len(files) > max_show:
            items.append((f"... +{len(files) - max_show} more", None))
        for index, (name, child) in enumerate(items):
            is_last = index == len(items) - 1
            branch = "└── " if is_last else "├── "
            suffix = f"/ ({child[2]})" if child is not None else ""
            tree_lines.append(f"{prefix}{branch}{name}{suffix}")
            if child is not None:
                render(child, prefix + ("    " if is_last else "│   "))

    tree = scan(knowledge_dir, is_root=True)
    if tree[0] or tree[1]:
        render(tree, "  ")
    else:
        tree_lines.append("  (empty)")

    return "\n" + "\n".join(tree_lines) + "\n"
