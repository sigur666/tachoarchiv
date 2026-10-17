"""Bedienungsanleitung als PDF setzen – mit denselben Mitteln wie die Berichte.

    python tools/manual_pdf.py [ziel.pdf]

Braucht python3-markdown und PySide6.
"""
import os, sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import markdown
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QApplication

src = str(Path(__file__).resolve().parents[1] / "doc" / "bedienungsanleitung.md")
import re
body = markdown.markdown(open(src, encoding="utf-8").read(),
                         extensions=["tables", "sane_lists", "fenced_code"])


def fix_pre(match):
    """Qt bricht in <pre> nicht um – die Zeilen also selbst setzen."""
    text = match.group(1)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [l for l in text.split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    return ("<table class='code'><tr><td>"
            + "<br>".join(l.replace(" ", "&nbsp;") for l in lines) + "</td></tr></table>")


body = re.sub(r"<pre><code[^>]*>(.*?)</code></pre>", fix_pre, body, flags=re.S)
html = ("<html><head><meta charset='utf-8'><style>"
        "body{font-family:'Noto Sans','DejaVu Sans',sans-serif;font-size:10pt;color:#1a1a1a}"
        "h1{font-size:20pt;margin:0 0 6pt 0;color:#1f4e8c}"
        "h2{font-size:14pt;margin:16pt 0 4pt 0;border-bottom:1px solid #9ab;color:#1f4e8c}"
        "h3{font-size:11.5pt;margin:12pt 0 3pt 0}"
        "code{font-family:'DejaVu Sans Mono',monospace;font-size:9pt}"
        "table.code td{background:#f2f4f6;padding:6pt;font-family:'DejaVu Sans Mono',monospace;"
        "font-size:8.5pt;border:0}"
        "table{border-collapse:collapse;width:100%} td,th{padding:3pt 5pt;border-bottom:1px solid #ddd;"
        "vertical-align:top} th{text-align:left;background:#eef1f4}"
        "blockquote{background:#fbf0dc;padding:6pt;margin:8pt 0}"
        "li{margin-bottom:2pt}"
        "</style></head><body>" + body + "</body></html>")
app = QApplication(sys.argv)
doc = QTextDocument()
doc.setHtml(html)
printer = QPrinter(QPrinter.PrinterMode.HighResolution)
printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
printer.setOutputFileName(sys.argv[1] if len(sys.argv) > 1
                          else "TachoArchiv-Bedienungsanleitung.pdf")
doc.print_(printer)
print("ok")
