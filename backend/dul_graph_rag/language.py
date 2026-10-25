"""Programming-language enum used by the recursive text splitter.

`recursive_text_splitter.py` was copied from the `chunking_evaluation`
repository, whose only use of that package here is this enum. The upstream
package is *not* on PyPI and, once installed from GitHub, pulls `chromadb`,
`openai` and `anthropic` in just to define a list of language names.

The enum below is the upstream definition (MIT licensed) kept local, so the
splitter stays importable with no extra dependency::

    from dul_graph_rag.language import Language

    RecursiveTokenChunker.get_separators_for_language(Language.PYTHON)
"""

from __future__ import annotations

from enum import Enum

__all__ = ["Language"]


class Language(str, Enum):
    """Enum of the programming languages."""

    CPP = "cpp"
    GO = "go"
    JAVA = "java"
    KOTLIN = "kotlin"
    JS = "js"
    TS = "ts"
    PHP = "php"
    PROTO = "proto"
    PYTHON = "python"
    RST = "rst"
    RUBY = "ruby"
    RUST = "rust"
    SCALA = "scala"
    SWIFT = "swift"
    MARKDOWN = "markdown"
    LATEX = "latex"
    HTML = "html"
    SOL = "sol"
    CSHARP = "csharp"
    COBOL = "cobol"
    C = "c"
    LUA = "lua"
    PERL = "perl"
