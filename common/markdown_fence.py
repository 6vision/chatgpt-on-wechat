"""Fenced code block scanning shared by the channels' markdown converters."""

import re

_FENCE_OPEN_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")


def replace_fenced_blocks(text: str, render) -> str:
    """Replace each closed fenced code block with ``render(info, code, block)``.

    ``info`` is the text after the opening fence, ``code`` the body with a
    trailing newline per line, and ``block`` the original lines, fences
    included. A block opens on a ``` or ~~~ line (a backtick fence's info
    string cannot contain a backtick) and closes on a line holding only a run
    of the same character that is at least as long, so ~~~ fences work and a
    ```` fence can show a ``` example. Unclosed fences are left as they are.
    """
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        match = _FENCE_OPEN_RE.match(lines[i])
        if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            fence_run = match.group(1)
            for j in range(i + 1, len(lines)):
                closing = lines[j].strip()
                if closing == fence_run[0] * len(closing) and len(closing) >= len(fence_run):
                    code = "".join(line + "\n" for line in lines[i + 1:j])
                    out.append(render(match.group(2), code, "\n".join(lines[i:j + 1])))
                    i = j + 1
                    break
            else:
                out.append(lines[i])
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)
