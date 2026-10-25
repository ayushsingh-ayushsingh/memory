"""Lexicon and scoring helpers for the Jev ontology mapper.

Everything here is *derived* from the DOLCE export plus the settings: it
converts ontology terms into the option text Jev is offered, and scores how
strongly a natural-language predicate matches one of those properties.

It deliberately holds no mapping state and makes no Jev calls, so it can be
read (and tested) on its own -- which matters, because most of the mapper's
judgement lives in the IDF weighting and the option text.
"""

from __future__ import annotations

import math
from collections import Counter

from .jev import JevClient  # noqa: F401  (re-exported for type checkers)
from .mapper_types import _tokens
from .ontology import Ontology, OntologyProperty
from .settings import Settings


class OntologyLexicon:
    """Describes DUL terms to Jev and scores surface phrases against them."""

    def __init__(self, ontology: Ontology, settings: Settings) -> None:
        self.ontology = ontology
        self.settings = settings
        self._min_token_chars = max(1, settings.jev_affinity_min_token_chars)
        self._token_idf, self._function_words = self._build_idf()
        self._descendant_count = self._build_descendant_counts()
        self._property_depth = self._build_property_depth()
        self._root_property = self._build_root_property()

    # %% Text weighting (derived from the ontology, not hand-written)
    def _stem(self, token: str) -> str:
        """Collapse a token onto its first `jev_affinity_prefix_chars`.

        A light stemmer: `managed` and `manage` become the same token,
        `members` and `member` as well. It is what lets a natural-language
        predicate reach a DUL relation whose comment uses a different
        morphological form.
        """
        size = max(1, self.settings.jev_affinity_prefix_chars)
        if len(token) <= size:
            return token
        return token[:size]

    def _build_idf(self) -> tuple[dict[str, float], set[str]]:
        """Inverse document frequency over the property names + comments.

        The corpus is the ontology's own property descriptions, so the most
        frequent tokens are English function words ("of", "the", "relation",
        ...). They are dropped from the affinity computation — otherwise every
        relation phrase containing "of" would match every property containing
        "of" and the ordering would be meaningless.

        Tokens that are **DUL class names** ("agent", "person", "collection",
        ...) are *kept*: they carry the ontology's own meaning and a
        predicate that mentions them really does point at the relations that
        talk about them.
        """
        documents: list[set[str]] = []
        for prop in self.ontology.object_properties.values():
            documents.append(
                {self._stem(t) for t in _tokens(prop.name) | _tokens(prop.comment)}
            )
        total = max(1, len(documents))
        frequency: Counter[str] = Counter()
        for document in documents:
            frequency.update(document)
        ratio = self.settings.jev_affinity_stopword_ratio
        class_tokens: set[str] = set()
        for term in self.ontology.classes.values():
            # Only the *contentful* words of a class name count as ontology
            # vocabulary: camel-splitting 'UnitOfMeasure' also yields 'of',
            # and protecting that would leave 'of' in the corpus as a live
            # token, making every `is…Of` relation match every predicate
            # that contains the word 'of'.
            class_tokens |= {
                self._stem(t)
                for t in _tokens(term.name)
                if len(self._stem(t)) >= self._min_token_chars
            }
        function_words = {
            t for t, c in frequency.items() if c / total >= ratio and t not in class_tokens
        }
        idf = {
            token: math.log(1 + total / (1 + count))
            for token, count in frequency.items()
            if token not in function_words
        }
        return idf, function_words

    def _content_tokens(self, text: str) -> set[str]:
        """Meaningful, stemmed tokens of a text.

        Stem first, then drop: `function_words` holds *stems* too, so
        filtering the raw tokens would keep 'employees' while dropping its
        own stem. Grammatical particles ('of', 'in', 'is') are dropped a
        second time by their length — they are the whole reason a bare
        predicate can look like a DUL relation.
        """
        minimum = self._min_token_chars
        tokens: set[str] = set()
        for token in _tokens(text):
            stem = self._stem(token)
            if len(stem) < minimum or stem in self._function_words:
                continue
            tokens.add(stem)
        return tokens

    def _affinity(self, relation: str, prop: OntologyProperty, context: str = "") -> float:
        """How strongly a relation phrase matches a property.

        The relation phrase carries the meaning and weighs most (a hit in
        the relation *name* is worth twice a hit in the comment). The
        context — the ontology's own description of the two classes — weighs
        far less: it exists to break ties between the generic
        `Entity -> Entity` relations, never to outrank a relation that the
        class pair makes *specific*.
        """
        relation_tokens = self._content_tokens(relation)
        context_tokens = self._content_tokens(context)
        if not relation_tokens and not context_tokens:
            return 0.0
        name_tokens = self._content_tokens(prop.name)
        comment_tokens = self._content_tokens(prop.comment)
        fallback_weight = math.log(1 + len(self._token_idf) + 1)
        score = 0.0
        for token in relation_tokens:
            weight = self._token_idf.get(token, fallback_weight)
            if token in name_tokens:
                score += 2.0 * weight
            elif token in comment_tokens:
                score += 0.35 * weight
        for token in context_tokens:
            weight = self._token_idf.get(token, fallback_weight)
            if token in name_tokens:
                score += 0.15 * weight
            elif token in comment_tokens:
                score += 0.05 * weight
        return score

    # %% Ontology shapes
    def _build_descendant_counts(self) -> dict[str, int]:
        """How many classes sit below each class (a specificity proxy)."""
        counts: dict[str, int] = {uri: 0 for uri in self.ontology.classes}
        for uri in self.ontology.classes:
            for ancestor in self.ontology.ancestors_of(uri):
                if ancestor != uri:
                    counts[ancestor] = counts.get(ancestor, 0) + 1
        return counts

    def _build_property_depth(self) -> dict[str, int]:
        """How many superproperties a property has (a specificity proxy)."""
        return {
            uri: len(prop.superproperties)
            for uri, prop in self.ontology.object_properties.items()
        }

    def _build_root_property(self) -> str | None:
        """The unique object property with no superproperty.

        DUL declares exactly one such property and documents it as "a
        catch-all object property, useful for alignment and querying
        purposes"; every other object property hangs below it. That makes the
        root of the property hierarchy the ontology's own answer to "nothing
        here expresses this relation" — read from the export instead of being
        named, and used only if the export really does have a single root.
        """
        roots = [
            uri
            for uri, prop in self.ontology.object_properties.items()
            if not prop.superproperties
        ]
        return roots[0] if len(roots) == 1 else None

    def _ordered_children(self, parent_uri: str) -> list[str]:
        """Children of a class, most specific (most descendants) first."""
        children = self.ontology.children_of(parent_uri)
        return sorted(
            children,
            key=lambda uri: (
                -self._descendant_count.get(uri, 0),
                self.ontology.class_name(uri),
            ),
        )

    # %% Option helpers
    def _class_option(self, term_uri: str) -> str:
        """Option description for one class (never an invented definition)."""
        term = self.ontology.classes[term_uri]
        limit = self.settings.jev_option_comment_chars
        if not term.comment:
            # The export carries no definition for this term: say so instead
            # of inventing one.
            return f"{term.name} — (no definition in the ontology export)"
        description = term.comment
        if len(description) > limit:
            description = description[: limit - 1].rstrip() + "…"
        return f"{term.name} — {description}"

    def _unique_keys(self, uris: list[str], parent_name: str) -> dict[str, str]:
        """Option key -> class uri, disambiguated when names collide."""
        seen: Counter[str] = Counter()
        for uri in uris:
            seen[self.ontology.class_name(uri)] += 1
        mapping: dict[str, str] = {}
        for uri in uris:
            name = self.ontology.class_name(uri)
            key = name if seen[name] == 1 else f"{name} ({parent_name})"
            mapping[key] = uri
        return mapping

    def _property_option(self, uri: str) -> str:
        prop = self.ontology.object_properties[uri]
        return prop.describe(self.settings.jev_option_comment_chars)

    def _property_keys(self, uris: list[str]) -> dict[str, str]:
        """Option key -> property uri (keys stay unique even on a name clash)."""
        counts = Counter(self.ontology.property_name(uri) for uri in uris)
        seen: Counter[str] = Counter()
        mapping: dict[str, str] = {}
        for uri in uris:
            name = self.ontology.property_name(uri)
            if counts[name] > 1:
                seen[name] += 1
                key = f"{name} #{seen[name]}"
            else:
                key = name
            mapping[key] = uri
        return mapping

