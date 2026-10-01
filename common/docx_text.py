"""Shared Word body extraction, preserving paragraph/table ordering."""


def iter_docx_body_text(document):
    """Yield paragraphs and table rows in the order they occur in the body.

    Constructing the existing python-docx block objects also supports versions
    predating Document.iter_inner_content(). Imports stay optional and lazy.
    """
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for element in document.element.body.iterchildren():
        if element.tag == qn("w:p"):
            yield Paragraph(element, document).text
        elif element.tag == qn("w:tbl"):
            for row in Table(element, document).rows:
                yield "\t".join(cell.text for cell in row.cells)
