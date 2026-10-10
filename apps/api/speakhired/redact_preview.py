"""See exactly what the AI would receive from a file:  uv run python -m speakhired.redact_preview path/to/resume.pdf

Everything happens on this computer. Use it to check that your own details are removed, and to spot any over-removal.
"""
import sys
from pathlib import Path

from .ingest.documents import extract_text
from .privacy import Redactor, describe


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m speakhired.redact_preview <resume.pdf|resume.docx|resume.txt>")
    path = Path(sys.argv[1])
    red = Redactor()
    clean = red.clean(extract_text(path.name, path.read_bytes()))
    print(clean)
    print("\n--- removed (counts only):", describe(red.summary()) or "nothing")


if __name__ == "__main__":
    main()
