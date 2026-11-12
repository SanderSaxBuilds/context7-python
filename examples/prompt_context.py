"""Print a prompt block with current docs for a question about a library.

    python examples/prompt_context.py fastapi "How do I add a dependency to every route?"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from context7_client import Context7  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    name, question = sys.argv[1], " ".join(sys.argv[2:])
    c7 = Context7()
    libs = c7.search_library(question, name)
    if not libs:
        sys.exit(f"No Context7 library found for {name!r}")
    lib = libs[0]
    text = c7.get_context(question, lib.id, type="txt")
    print(f"<docs library=\"{lib.id}\" title=\"{lib.title}\">\n{text.strip()}\n</docs>")
    print(f"\n{question}")
    rl = c7.last_rate_limit
    if rl and rl.remaining is not None:
        print(f"\n(rate limit left: {rl.remaining}/{rl.limit})", file=sys.stderr)


if __name__ == "__main__":
    main()
