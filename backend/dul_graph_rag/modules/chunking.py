"""Long context in, coreference-resolved *disjoint* chunks out.

This is the stage that runs before anything else in the extract endpoint::

    raw long text
        -> coreference resolution   (fastcoref + spaCy demonstrative fallback)
        -> ONE rewrite of the text  (each chain annotated exactly once: `it <AI technology>`)
        -> disjoint chunks          (RecursiveTokenChunker, overlap = 0 by design)

Why resolution comes *first*: a chunk boundary that lands between "it" and the
sentence it refers to destroys the very relation the extractor is supposed to
find. Resolving first means every chunk carries its referent inline, so the
LLM extraction and the Jev mapping see complete facts inside one window.

Why the chunks are disjoint: the endpoint contract is "one piece of text lives
in exactly one chunk". Duplicated text would write duplicate facts, inflate
recall with the same sentence twice and make `no overlap` untestable. There is
deliberately no overlap knob here — `split_no_overlap()` cannot produce it.

Everything tunable lives in `settings` (``.env``): ``DUL_CHUNK_SIZE``,
``DUL_COREF_MAX_CHARS``, ``DUL_COREF_DEVICE``, ``DUL_COREF_ENABLED``.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .settings import Settings, get_settings


# %% transformers >= 5 patch (fastcoref 2.1.6)
#
# fastcoref 2.1.6 finishes its models' `__init__` with the legacy
# `init_weights()` and never calls `post_init()`. transformers >= 5 sets
# `all_tied_weights_keys` inside `post_init()`, so `from_pretrained` then
# crashes with an AttributeError. The wrapper below makes `__init__` end with
# `post_init()` — the modern transformers contract — and is a no-op on
# transformers < 5.

def patch_fastcoref_for_transformers5() -> bool:
    """Make fastcoref's model classes import-safe under transformers >= 5."""
    import transformers
    from packaging.version import parse

    if parse(transformers.__version__) < parse("5"):
        return False
    from fastcoref.coref_models.modeling_fcoref import FCorefModel
    from fastcoref.coref_models.modeling_lingmess import LingMessModel

    for cls in (FCorefModel, LingMessModel):
        if getattr(cls, "_post_init_patched", False):
            continue
        original_init = cls.__init__

        def patched_init(self: Any, config: Any, _original: Any = original_init) -> None:
            _original(self, config)
            if not hasattr(self, "all_tied_weights_keys"):
                self.post_init()

        cls.__init__ = patched_init
        cls._post_init_patched = True
    return True


# %% Models (public results of this stage)


class Chunk(BaseModel):
    """One disjoint piece of the *resolved* text."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(description="0-based position of the chunk in the document")
    text: str = Field(description="Chunk text, ready to embed and to extract from")
    start: int = Field(description="Inclusive char offset in the resolved text")
    end: int = Field(description="Exclusive char offset in the resolved text")
    n_chars: int = 0
    n_annotations: int = Field(
        default=0, description="Number of `<referent>` coreference tags in this chunk"
    )


class PreparedText(BaseModel):
    """Outcome of the resolve -> chunk stage (no I/O, no model writes)."""

    model_config = ConfigDict(extra="forbid")

    original_text: str = Field(default="", description="Exactly what the caller sent")
    resolved_text: str = Field(
        default="", description="Original text with one inline annotation per chain"
    )
    original_chars: int = 0
    resolved_chars: int = 0
    coref_blocks: int = Field(default=0, description="Pieces the long text was cut into")
    coref_chains: int = Field(default=0, description="Coreference chains found")
    annotations: int = Field(default=0, description="Annotations written into the text")
    resolution: str = Field(
        default="fastcoref+spacy",
        description="Which resolver ran: fastcoref+spacy, spacy or off",
    )
    chunks: list[Chunk] = Field(default_factory=list)

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


# %% Singletons (loaded once, used under `_MODEL_LOCK`)


_MODEL_LOCK = threading.Lock()
_COREF_MODEL: Any = None
_SPACY_NLP: Any = None


def get_coref_model(settings: Settings | None = None) -> Any:
    """Load `FCoref` once (weights come from the HuggingFace cache)."""
    global _COREF_MODEL
    if _COREF_MODEL is None:
        patch_fastcoref_for_transformers5()
        from fastcoref import FCoref

        s = settings or get_settings()
        _COREF_MODEL = FCoref(device=s.coref_device, enable_progress_bar=False)
    return _COREF_MODEL


def get_spacy(settings: Settings | None = None) -> Any:
    """Load the spaCy pipeline once (tagger + parser + morphology)."""
    _ = settings or get_settings()
    global _SPACY_NLP
    if _SPACY_NLP is None:
        import spacy

        _SPACY_NLP = spacy.load("en_core_web_sm")
    return _SPACY_NLP


def reset_models() -> None:
    """Drop the singletons (tests, or a changed `DUL_COREF_DEVICE`)."""
    global _COREF_MODEL, _SPACY_NLP
    _COREF_MODEL = None
    _SPACY_NLP = None


# %% Long-text blocking (coreference model sees one bounded piece at a time)


def coref_blocks(text: str, max_chars: int) -> list[tuple[int, int]]:
    """Cut `text` into ordered, non-overlapping, paragraph-aligned blocks.

    The blocks tile the text exactly (`start[0] == 0`, `end[-1] == len(text)`,
    `start[i] == end[i-1]`), so a mention address inside a block maps back to
    the original text by a single offset add. Long inputs are split because
    one 500k-character forward pass on CPU is neither bounded in time nor in
    memory; clusters cannot cross a block boundary, which is the price.
    """
    n = len(text)
    if n <= max_chars:
        return [(0, n)]
    cuts = [0]
    pos = 0
    # Boundaries are preferred in this order: paragraph, line, sentence, word.
    separators = ("\n\n", "\n", ". ", "? ", "! ", " ")
    while pos < n:
        nxt = min(pos + max_chars, n)
        if nxt < n:
            window = text[pos:nxt]
            best_at, best_sep = -1, ""
            for sep in separators:
                at = window.rfind(sep)
                if at > best_at:
                    best_at, best_sep = at, sep
            # Only take the boundary when it is near the middle or later, so
            # one block never collapses to a stub.
            if best_at >= max_chars // 2:
                nxt = pos + best_at + len(best_sep)
        if nxt <= pos:  # pathological text with no usable boundary
            nxt = min(pos + max_chars, n)
        cuts.append(nxt)
        pos = nxt
    return [(a, b) for a, b in zip(cuts, cuts[1:], strict=False) if b > a]


# %% Coreference stages (the notebook's functions, kept behaviour-compatible)


def link_demonstratives(doc: Any, clusters: list[list[tuple[int, int]]]) -> list[list[tuple[int, int]]]:
    """Fallback for anaphoric demonstratives the coref model leaves unlinked.

    'Demonstrative' comes from the tagger's morphology (`PronType=Dem`), not
    from a word list; determiner uses ('that book', dep=det) and already-linked
    tokens are skipped. Every mention that lands here gets attached to the
    nearest preceding noun phrase, which is what turns
    `unhappy with that` into `unhappy with that <current assistant>`.
    """
    chains = [[tuple(s) for s in chain] for chain in clusters]
    linked = {s for chain in chains for s in chain}

    candidates = [
        (c.start_char, c.end_char)
        for c in doc.noun_chunks
        if c.root.pos_ not in ("PRON", "DET")
    ]

    for tok in doc:
        if "Dem" not in (tok.morph.get("PronType") or []):
            continue
        if tok.dep_ == "det" or any(s <= tok.idx < e for s, e in linked):
            continue  # 'that book' / already resolved by the model
        preceding = [c for c in candidates if c[1] <= tok.idx]
        if not preceding:
            continue
        antecedent = max(preceding, key=lambda c: c[1])  # nearest NP before the pronoun
        mention = (tok.idx, tok.idx + len(tok))
        for chain in chains:
            if antecedent in chain:
                chain.append(mention)
                break
        else:
            chains.append([antecedent, mention])
        linked.add(mention)
    return chains


def resolve_coreferences_once(
    text: str,
    clusters: list[list[tuple[int, int]]],
    doc: Any,
    *,
    sep: str = " ",
    open_tag: str = "<",
    close_tag: str = ">",
) -> str:
    """Annotate each coreference chain exactly ONCE.

    The chain's *first referring* mention is tagged with the chain's referent:
    `I <Ayush Singh>`, `it <AI technology>`. Later mentions stay untagged, so
    the text is not littered and the extractor is not handed the same fact five
    times. The referent is the chain's longest mention (the full noun phrase),
    minus a leading possessive modifier found through its dependency relation
    (`dep=poss`: 'my current assistant' -> 'current assistant').

    Tags never nest: mentions are emitted in document order and a tag that
    would start inside the previous one is skipped.
    """
    text_out, _count = _resolve_with_count(
        text, clusters, doc, sep=sep, open_tag=open_tag, close_tag=close_tag
    )
    return text_out


def _resolve_with_count(
    text: str,
    clusters: list[list[tuple[int, int]]],
    doc: Any,
    *,
    sep: str,
    open_tag: str,
    close_tag: str,
) -> tuple[str, int]:
    """The annotation pass itself; returns (text, annotations written)."""
    from bisect import bisect_right

    token_starts = [t.idx for t in doc]
    tokens = list(doc)

    def display(span: tuple[int, int]) -> str:
        """The referent text, without a leading possessive (`my` -> dropped)."""
        start, end = span
        at = bisect_right(token_starts, start - 1)  # first token with idx >= start
        while at < len(tokens) and tokens[at].idx < end and tokens[at].dep_ == "poss":
            at += 1  # drop 'my' in 'my current assistant'
        if at >= len(tokens) or tokens[at].idx >= end:
            return text[start:end].strip()  # no token left: use the raw span
        return text[tokens[at].idx:end].strip()

    tags: list[tuple[int, int, str]] = []  # exactly one per chain
    for chain in clusters:
        chain = [tuple(s) for s in chain]
        if not chain:
            continue
        rep = min(chain, key=lambda s: (-(s[1] - s[0]), s[0]))  # longest = referent
        others = [s for s in chain if s != rep]
        if not others:
            continue
        first_ref = min(others, key=lambda s: (s[0], s[1]))  # the ONE tagged mention
        if first_ref[0] >= first_ref[1]:
            continue
        referent = display(rep)
        # A tag that repeats the mention verbatim (`They <They>`) teaches the
        # extractor nothing, so that chain stays unannotated.
        if referent == text[first_ref[0] : first_ref[1]].strip():
            continue
        tags.append((first_ref[0], first_ref[1], referent))

    out: list[str] = []
    written = 0
    cursor = 0
    for start, end, referent in sorted(tags):
        if start < cursor:  # tagged mentions of two chains must not nest
            continue
        out.append(text[cursor:start])
        out.append(text[start:end])
        out.append(f"{sep}{open_tag}{referent}{close_tag}")
        cursor = end
        written += 1
    out.append(text[cursor:])
    return "".join(out), written


# %% The resolver


def resolve_text(text: str, settings: Settings | None = None) -> PreparedText:
    """Run coreference resolution over the whole text and rewrite it once.

    Blocking (model inference); the async caller runs this in a worker thread.
    The two models are guarded by `_MODEL_LOCK`: spaCy and fastcoref are not
    safe to drive from two requests at the same time, and serialising keeps
    peak memory to a single model instance.
    """
    s = settings or get_settings()
    prepared = PreparedText(
        original_text=text,
        resolved_text=text,
        original_chars=len(text),
        resolved_chars=len(text),
    )
    if not text.strip():
        prepared.resolution = "off"
        return prepared

    with _MODEL_LOCK:
        clusters: list[list[tuple[int, int]]] = []
        blocks = coref_blocks(text, s.coref_max_chars)
        prepared.coref_blocks = len(blocks)
        nlp = get_spacy(s)
        if s.coref_enabled:
            model = get_coref_model(s)
            for block_start, block_end in blocks:
                block = text[block_start:block_end]
                preds = model.predict(texts=[block])
                for chain in preds[0].get_clusters(as_strings=False):
                    if chain:
                        clusters.append(
                            [(start + block_start, end + block_start) for start, end in chain]
                        )

        doc = nlp(text)
        chains = link_demonstratives(doc, clusters)
        resolved, annotations = _resolve_with_count(
            text, chains, doc, sep=" ", open_tag="<", close_tag=">"
        )

    prepared.coref_chains = len(chains)
    prepared.annotations = annotations
    prepared.resolved_text = resolved
    prepared.resolved_chars = len(resolved)
    prepared.resolution = "fastcoref+spacy" if s.coref_enabled else "spacy"
    return prepared


# %% Disjoint chunking


def _split_plain_run(text: str, start: int, end: int, chunk_size: int) -> list[tuple[int, int]]:
    """Split a tag-free run into (start, end) windows of at most `chunk_size`.

    Uses `RecursiveTokenChunker` (paragraph -> line -> sentence -> word), with
    the overlap pinned to 0, then re-derives each window's char offsets by
    walking forward through the source — the splitter returns text, not spans.
    """
    from ..recursive_text_splitter import RecursiveTokenChunker

    run = text[start:end]
    if len(run) <= chunk_size:
        return [(start, end)]
    splitter = RecursiveTokenChunker(chunk_size=chunk_size, chunk_overlap=0)
    pieces = splitter.split_text(run)
    spans: list[tuple[int, int]] = []
    cursor = start
    for piece in pieces:
        found = text.find(piece, cursor)
        if found < 0:  # whitespace stripped by the splitter; fall back to scan
            found = text.find(piece, start)
        if found < 0:  # cannot happen for splitter output; keep the piece anyway
            found = cursor
        spans.append((found, found + len(piece)))
        cursor = found + len(piece)
    return spans


def _segments(text: str) -> list[tuple[int, int, bool]]:
    """Atomic pieces as (start, end, is_annotation).

    `<...>` annotations are never cut; plain runs may be. A `<` without a
    closing `>` (angle brackets that were already in the source text) is plain
    text, not an annotation, and is therefore still allowed to be split.
    """
    segments: list[tuple[int, int, bool]] = []
    cursor = 0
    n = len(text)
    while cursor < n:
        opened = text.find("<", cursor)
        if opened < 0:
            segments.append((cursor, n, False))
            break
        closed = text.find(">", opened + 1)
        if closed < 0:
            segments.append((cursor, n, False))
            break
        if opened > cursor:
            segments.append((cursor, opened, False))
        segments.append((opened, closed + 1, True))
        cursor = closed + 1
    return [(a, b, tag) for a, b, tag in segments if b > a]


def _annotation_count(text: str) -> int:
    """How many `<...>` annotations a piece of text carries."""
    total = 0
    cursor = 0
    while True:
        opened = text.find("<", cursor)
        if opened < 0:
            return total
        closed = text.find(">", opened + 1)
        if closed < 0:
            return total
        total += 1
        cursor = closed + 1


def split_no_overlap(text: str, chunk_size: int) -> list[Chunk]:
    """Pack `text` into ordered chunks that never overlap and never split a tag.

    Greedy first-fit: a chunk grows until the next atomic segment would not
    fit, then the next chunk starts. Plain runs longer than `chunk_size` are
    cut by `RecursiveTokenChunker` first, so no chunk is forced over the limit
    except a single annotation that is itself longer than `chunk_size`.
    """
    if not text:
        return []
    chunk_size = max(1, chunk_size)

    pieces: list[tuple[int, int]] = []
    for seg_start, seg_end, is_annotation in _segments(text):
        if not is_annotation and seg_end - seg_start > chunk_size:
            pieces.extend(_split_plain_run(text, seg_start, seg_end, chunk_size))
        else:
            pieces.append((seg_start, seg_end))

    chunks: list[Chunk] = []
    current: list[tuple[int, int]] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if not current:
            return
        start, end = current[0][0], current[-1][1]
        # Trim the whitespace the greedy packer may have swallowed; offsets
        # point at the trimmed span, so chunks stay strictly ordered and apart.
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        body = text[start:end]
        if body:
            chunks.append(
                Chunk(
                    index=len(chunks),
                    text=body,
                    start=start,
                    end=end,
                    n_chars=len(body),
                    n_annotations=_annotation_count(body),
                )
            )
        current, current_len = [], 0

    for start, end in pieces:
        length = end - start
        if current and current_len + length > chunk_size:
            flush()
        current.append((start, end))
        current_len += length
    flush()
    return chunks


# %% Async entry point


async def prepare_text(text: str, settings: Settings | None = None) -> PreparedText:
    """Resolve coreferences, then chunk — model inference off the event loop."""
    return await asyncio.to_thread(resolve_text, text, settings)


def verify_no_overlap(text: str, chunks: list[Chunk]) -> list[str]:
    """Self-check used by the endpoint and the tests: disjoint and complete.

    Returns a list of problems (empty = the chunks are an exact, non-overlapping
    partition of `text` when whitespace is ignored).
    """
    issues: list[str] = []
    previous_end = 0
    covered: list[str] = []
    for chunk in chunks:
        if chunk.start < previous_end:
            issues.append(
                f"chunk {chunk.index} overlaps the previous one "
                f"({chunk.start} < {previous_end})"
            )
        if chunk.end < chunk.start or text[chunk.start : chunk.end] != chunk.text:
            issues.append(f"chunk {chunk.index} offsets do not match its text")
        previous_end = max(previous_end, chunk.end)
        covered.append(chunk.text)
    if previous_end and previous_end < len(text) and text[previous_end:].strip():
        issues.append("some non-whitespace text was not covered by any chunk")
    squashed = "".join("".join(part.split()) for part in covered)
    source = "".join(text.split())
    if squashed != source:
        issues.append("the chunks are not a partition of the text (content differs)")
    if chunks and chunks[0].start > 0 and text[: chunks[0].start].strip():
        issues.append("text before the first chunk was dropped")
    return issues


__all__ = [
    "Chunk",
    "PreparedText",
    "coref_blocks",
    "link_demonstratives",
    "patch_fastcoref_for_transformers5",
    "prepare_text",
    "resolve_coreferences_once",
    "resolve_text",
    "split_no_overlap",
    "verify_no_overlap",
]
