from __future__ import annotations

import math
from typing import Any

from .jev import JevAnswer, JevClient, build_choice
from .mapper_lexicon import OntologyLexicon
from .mapper_types import (
    ClassMapping,
    ClassRepairRequest,
    JevOutcome,
    PropertyMapping,
    _Path,
    _PropertyPlan,
    _WindowRequest,
    _chunks,
    pair_key,
)
from .ontology import Ontology, get_ontology
from .schema import is_subclass_of
from .settings import Settings, get_settings


# %% Mapper


class OntologyMapper:
    """Maps entities and relations onto the DUL ontology with Jev."""

    def __init__(
        self,
        client: JevClient,
        ontology: Ontology | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self.ontology = ontology or get_ontology()
        # Everything used to *describe* DUL terms to Jev and to score a surface
        # phrase against one lives in `mapper_lexicon.OntologyLexicon`: it is
        # derived once from the ontology + settings and holds no mapping state.
        self.lexicon = OntologyLexicon(self.ontology, self.settings)

    @staticmethod
    def _load_ontology() -> Ontology:
        return get_ontology()


    # %% Windowed choice helper
    async def _windowed_answers(
        self,
        requests: list[_WindowRequest],
        state: str,
        min_confidence: float = 0.0,
        resolve_weak: bool = True,
    ) -> dict[str, JevOutcome]:
        """Ask windowed choice questions; move on when a window is rejected.

        Every window of every request that is still open travels in **one**
        request, so the cost is one round trip per *round* of windows, never
        one per question.

        A window answered with the "none of these" label — or with a
        confidence below `min_confidence` — is a rejection: the next window
        offers a different set of candidates instead. The escape hatch is
        offered in **every** window, the last one included: without it the
        final window would force a pick, and a forced pick is precisely the
        junk decision a strict gate exists to prevent.

        Every option probability seen on the way is merged into
        `JevOutcome.probabilities`. When no window earns a commitment, the
        strongest rejected pick becomes the decision only if `resolve_weak`
        asks for it — the class stage asks (a weakly preferred subclass still
        beats its parent), the property stage does not (it would rather fall
        back to the ontology's own catch-all than commit to a relation Jev
        explicitly refused).
        """
        pending = {r.qid: r for r in requests}
        outcomes: dict[str, JevOutcome] = {r.qid: JevOutcome() for r in requests}
        probabilities: dict[str, dict[str, float]] = {r.qid: {} for r in requests}
        fallback: dict[str, tuple[JevAnswer, int]] = {}
        round_index = 0
        while pending:
            questions: dict[str, Any] = {}
            active: dict[str, _WindowRequest] = {}
            for qid, request in list(pending.items()):
                if round_index >= len(request.windows):
                    pending.pop(qid, None)
                    continue
                options = dict(request.windows[round_index])
                if request.none_label:
                    options[request.none_label] = self._none_description()
                questions[qid] = build_choice(
                    request.instructions, options, self.settings.jev_max_choices
                )
                active[qid] = request
            if not questions:
                break
            answers = await self.client.ask_batched(questions, state)
            next_pending: dict[str, _WindowRequest] = {}
            for qid, request in active.items():
                answer = answers.get(qid)
                if answer is None:
                    # No answer at all: the same window is asked again in the
                    # next round rather than silently skipped.
                    next_pending[qid] = request
                    continue
                merged = probabilities.setdefault(qid, {})
                for option, probability in answer.probabilities.items():
                    if option == request.none_label:
                        continue
                    merged[option] = max(merged.get(option, 0.0), float(probability))
                is_none = (
                    request.none_label is not None
                    and answer.choice == request.none_label
                )
                floor = (
                    request.min_confidence
                    if request.min_confidence > 0.0
                    else min_confidence
                )
                if not is_none and answer.confidence >= floor:
                    outcomes[qid].answer = answer
                    outcomes[qid].window = round_index
                    continue
                if not is_none:
                    current = fallback.get(qid)
                    if current is None or answer.confidence > current[0].confidence:
                        fallback[qid] = (answer, round_index)
                if round_index + 1 < len(request.windows):
                    next_pending[qid] = request
            pending = next_pending
            round_index += 1

        for qid, outcome in outcomes.items():
            outcome.probabilities = probabilities.get(qid, {})
            if outcome.answer is None and resolve_weak:
                weak = fallback.get(qid)
                if weak is not None:
                    outcome.answer, outcome.window = weak[0], weak[1]
        return outcomes

    def _none_description(self) -> str:
        return (
            "None of the options above is correct — choose this when every "
            "listed alternative is wrong."
        )

    def _window_size(self) -> int:
        """How many real options fit in one window (the none-label takes one)."""
        size = self.settings.jev_max_choices
        if self.settings.jev_include_none_option:
            size = max(1, size - 1)
        return size

    # %% Class mapping (beam search over the hierarchy)
    async def map_classes(
        self, entities: list[str], state: str
    ) -> dict[str, ClassMapping]:
        """Map every entity onto a DOLCE class (beam search, one call/level)."""
        root = self.ontology.root_class
        root_name = self.ontology.class_name(root)
        beams: dict[str, list[_Path]] = {
            entity: [_Path(uri=root, names=[root_name])] for entity in entities
        }
        finished: dict[str, list[_Path]] = {entity: [] for entity in entities}
        levels: dict[str, int] = {entity: 0 for entity in entities}
        max_depth = max(1, self.settings.jev_max_class_depth)

        for depth in range(1, max_depth + 1):
            requests: list[_WindowRequest] = []
            for entity, paths in beams.items():
                for index, path in enumerate(paths):
                    children = self.lexicon._ordered_children(path.uri)
                    if not children:
                        finished[entity].append(path)
                        continue
                    parent_name = self.ontology.class_name(path.uri)
                    key_map = self.lexicon._unique_keys(children, parent_name)
                    by_uri = {uri: key for key, uri in key_map.items()}
                    windows = []
                    for chunk in _chunks(children, self._window_size()):
                        # The keys come from the *global* map of this level:
                        # a name that collides inside a chunk must keep the
                        # same label it has in `key_map`.
                        windows.append(
                            {
                                by_uri[uri]: self.lexicon._class_option(uri)
                                for uri in chunk
                            }
                        )
                    requests.append(
                        _WindowRequest(
                            qid=f"cls::{entity}::{index}",
                            instructions=(
                                f"Which subclass of '{parent_name}' is the entity "
                                f"'{entity}'? Answer with the most specific class that "
                                "fits the way the entity is used in the text."
                            ),
                            windows=windows,
                            none_label=(
                                self.settings.jev_none_option_key
                                if self.settings.jev_include_none_option
                                else None
                            ),
                            key_map=key_map,
                        )
                    )
            if not requests:
                break

            answers = await self._windowed_answers(
                requests,
                state,
                min_confidence=self.settings.jev_min_class_confidence,
            )
            by_qid = {request.qid: request for request in requests}

            next_beams: dict[str, list[_Path]] = {}
            for entity, paths in beams.items():
                candidates: list[tuple[_Path, str, float]] = []
                for index, path in enumerate(paths):
                    children = self.lexicon._ordered_children(path.uri)
                    if not children:
                        continue
                    qid = f"cls::{entity}::{index}"
                    request = by_qid[qid]
                    outcome = answers.get(qid)
                    answer = outcome.answer if outcome is not None else None
                    if answer is None:
                        # Jev could not answer: keep the parent as the result.
                        finished[entity].append(path)
                        continue
                    chosen = request.key_map.get(answer.choice)
                    if chosen is None:
                        finished[entity].append(path)
                        continue
                    seen = outcome.probabilities if outcome is not None else {}
                    child_probabilities = {
                        child: float(
                            seen.get(self._child_key(request.key_map, child), 0.0)
                        )
                        for child in children
                    }
                    best_child = max(child_probabilities.values(), default=0.0)
                    if best_child < self.settings.jev_min_class_confidence:
                        # The entity is not confidently more specific than the
                        # parent: the parent is the answer.
                        finished[entity].append(path)
                        continue
                    for child, probability in child_probabilities.items():
                        if probability <= 0.0:
                            continue
                        candidates.append(
                            (
                                _Path(
                                    uri=child,
                                    names=[
                                        *path.names,
                                        self.ontology.class_name(child),
                                    ],
                                    log_score=path.log_score + math.log(probability),
                                    decisions=path.decisions + 1,
                                ),
                                path.uri,
                                probability,
                            )
                        )
                if not candidates:
                    # Nothing survived on this level: the previous level is the
                    # final answer for this entity.
                    finished[entity].extend(paths)
                    next_beams[entity] = []
                    continue
                candidates.sort(key=lambda c: -c[0].score)
                pruned = self._prune_beam(candidates, self.settings.jev_class_beam_width)
                next_beams[entity] = [c[0] for c in pruned]
                levels[entity] = depth
            beams = next_beams
            if not any(beams.values()):
                break

        # %% Best terminal path per entity
        result: dict[str, ClassMapping] = {}
        for entity in entities:
            pool = [*finished.get(entity, []), *beams.get(entity, [])]
            pool = [p for p in pool if p.decisions > 0] or pool
            if not pool:
                result[entity] = ClassMapping(entity=entity, note="no class path found")
                continue
            best = max(pool, key=lambda p: (p.score, len(p.names)))
            result[entity] = ClassMapping(
                entity=entity,
                class_uri=best.uri,
                class_name=self.ontology.class_name(best.uri),
                confidence=round(best.score, 4),
                path=list(best.names),
                path_score=round(best.score, 4),
                levels=best.decisions,
                decided=bool(best.uri),
            )
        return result

    def _child_key(self, key_map: dict[str, str], child_uri: str) -> str:
        for key, uri in key_map.items():
            if uri == child_uri:
                return key
        return child_uri

    def _class_path(self, uri: str) -> list[str]:
        """Root-to-class chain of a class (the deepest parent path)."""
        chain = [uri]
        seen = {uri}
        current = uri
        while True:
            parents = self.ontology.class_parents.get(current, [])
            if not parents:
                break
            nxt = max(parents, key=lambda p: self.ontology.depth_of(p))
            if nxt in seen:
                break
            chain.append(nxt)
            seen.add(nxt)
            current = nxt
        return [self.ontology.class_name(u) for u in reversed(chain)]

    # %% Class repair (the gate blamed the class, not the relation)
    def _admissible_classes(
        self, deps: dict[str, Any], types: list[str]
    ) -> list[str]:
        """Classes that satisfy **every** one of the given type constraints.

        The computation uses the **gate's** schema, ancestors and lineage —
        not the ontology export — so every admissible class is one the strict
        gate actually accepts for the relation that was rejected. Classes the
        export does not describe are dropped: an option the model cannot read
        is not an option.
        """

        if not types:
            return []
        ancestors = deps["ancestors"]
        admissible = [
            uri
            for uri in deps["schema"]["classes"]
            if uri in self.ontology.classes
            and all(is_subclass_of(uri, t, ancestors) for t in types)
        ]
        return admissible

    def _rank_repair_candidates(
        self, candidates: list[str], rejected: str
    ) -> list[str]:
        """Order the admissible classes by closeness to the rejected one.

        Siblings first (same level, different reading), then the rejected
        class's own subclasses (a more specific reading that still satisfies
        the constraint), then its superclasses (a more general one), then
        everything else. The order is total, so the offer is reproducible.
        """
        parents = set(self.ontology.class_parents.get(rejected, []))
        rejected_ancestors = self.ontology.ancestors_of(rejected)

        def rank(uri: str) -> tuple[int, str]:
            if parents & set(self.ontology.class_parents.get(uri, [])):
                tier = 0
            elif rejected in self.ontology.ancestors_of(uri):
                tier = 1
            elif uri in rejected_ancestors:
                tier = 2
            else:
                tier = 3
            return (tier, self.ontology.class_name(uri))

        return sorted(candidates, key=rank)

    def repair_plans(
        self,
        requests: list[ClassRepairRequest],
        deps: dict[str, Any],
        exclude_classes: dict[str, set[str]] | None = None,
    ) -> tuple[list[_WindowRequest], dict[str, ClassRepairRequest]]:
        """Build the class-repair questions (no Jev call is made here).

        `requests` name the entities whose class the gate refused, the side
        they sit on and the **types** the class has to satisfy. The offered
        options are the classes that satisfy those types — computed with the
        gate's own schema, so every option is a class the strict gate would
        accept for the rejected relation. They are ranked by closeness to the
        rejected class, which keeps the repair as near to the original
        reading of the text as the ontology allows.

        The result is a list of windowed questions plus the metadata that maps
        a question id back onto the request it came from. The pipeline merges
        them with the property questions of the same round, so the whole
        repair costs **one** round trip.
        """
        exclude_classes = exclude_classes or {}
        plans: list[_WindowRequest] = []
        meta: dict[str, ClassRepairRequest] = {}
        seen_entities: set[tuple[str, str]] = set()
        for request in requests:
            # One class per entity: a second complaint about the same class
            # must not turn into a second, competing question.
            if (request.entity, request.side) in seen_entities:
                continue
            admissible = [
                uri
                for uri in self._admissible_classes(deps, request.types)
                if uri != request.rejected_class
                and uri not in exclude_classes.get(request.entity, set())
            ]
            admissible = self._rank_repair_candidates(admissible, request.rejected_class)
            limit = max(1, self.settings.jev_max_class_repair_candidates)
            admissible = admissible[:limit]
            if not admissible:
                continue
            seen_entities.add((request.entity, request.side))
            key_map = self.lexicon._unique_keys(
                admissible, self.ontology.class_name(request.rejected_class)
            )
            by_uri = {uri: key for key, uri in key_map.items()}
            windows = [
                {
                    by_uri[uri]: self.lexicon._class_option(uri)
                    for uri in chunk
                }
                for chunk in _chunks(admissible, self._window_size())[
                    : max(1, self.settings.jev_max_class_repair_windows)
                ]
            ]
            qid = f"clsfix::{request.entity}::{request.side}"
            meta[qid] = request
            plans.append(
                _WindowRequest(
                    qid=qid,
                    instructions=(
                        f"The DUL class '{self.ontology.class_name(request.rejected_class)}' "
                        f"was rejected for '{request.entity}': {request.complaint} "
                        f"Which of these DUL classes describes '{request.entity}' "
                        f"instead? Pick the most specific one that fits the text "
                        f"and satisfies the type constraint of the relation "
                        f"'{self.ontology.property_name(request.relation)}'."
                    ),
                    windows=windows,
                    none_label=(
                        self.settings.jev_none_option_key
                        if self.settings.jev_include_none_option
                        else None
                    ),
                    key_map=key_map,
                    min_confidence=self.settings.jev_min_class_confidence,
                )
            )
        return plans, meta

    def apply_class_repairs(
        self,
        outcomes: dict[str, JevOutcome],
        plans: list[_WindowRequest],
        meta: dict[str, ClassRepairRequest],
    ) -> dict[str, ClassMapping]:
        """Turn the answered repair questions into new class mappings."""
        repaired: dict[str, ClassMapping] = {}
        for qid, outcome in outcomes.items():
            request = meta.get(qid)
            if request is None or outcome.answer is None:
                continue
            plan = next((p for p in plans if p.qid == qid), None)
            if plan is None:
                continue
            chosen = plan.key_map.get(outcome.answer.choice)
            if chosen is None:
                continue
            repaired[request.entity] = ClassMapping(
                entity=request.entity,
                class_uri=chosen,
                class_name=self.ontology.class_name(chosen),
                confidence=round(float(outcome.answer.confidence), 4),
                path=self._class_path(chosen),
                path_score=round(float(outcome.answer.confidence), 4),
                levels=len(self._class_path(chosen)) - 1,
                decided=True,
                note=(
                    f"repaired: '{self.ontology.class_name(request.rejected_class)}' "
                    f"was rejected by the DUL gate"
                ),
            )
        return repaired

    async def repair_classes(
        self,
        requests: list[ClassRepairRequest],
        state: str,
        deps: dict[str, Any],
        exclude_classes: dict[str, set[str]] | None = None,
    ) -> dict[str, ClassMapping]:
        """Re-ask Jev for a **different class** for the entities the gate blamed.

        A thin wrapper around `repair_plans` / `apply_class_repairs` for the
        cases where the class repair is the *only* question of the round. The
        pipeline uses `repair_round` instead, which merges this question with
        the property questions of the same round into a single request.
        """
        if not requests:
            return {}
        plans, meta = self.repair_plans(requests, deps, exclude_classes)
        if not plans:
            return {}
        outcomes = await self._windowed_answers(
            plans,
            state,
            min_confidence=self.settings.jev_min_class_confidence,
        )
        return self.apply_class_repairs(outcomes, plans, meta)

    def _prune_beam(
        self, candidates: list[tuple[_Path, str, float]], width: int
    ) -> list[tuple[_Path, str, float]]:
        """Keep the best `width` children, never losing a whole branch."""
        if width <= 0:
            return []
        best_per_parent: dict[str, tuple[_Path, str, float]] = {}
        for candidate in candidates:
            parent = candidate[1]
            current = best_per_parent.get(parent)
            if current is None or candidate[2] > current[2]:
                best_per_parent[parent] = candidate
        kept = sorted(best_per_parent.values(), key=lambda c: -c[0].score)
        if len(kept) >= width:
            return kept[:width]
        chosen = {id(c) for c in kept}
        for candidate in candidates:
            if len(kept) >= width:
                break
            if id(candidate) in chosen:
                continue
            kept.append(candidate)
            chosen.add(id(candidate))
        kept.sort(key=lambda c: -c[0].score)
        return kept

    # %% Property mapping
    def property_candidates(
        self, subject_class: str, object_class: str, relation: str
    ) -> list[tuple[str, int]]:
        """Compatible properties with their specificity tier.

        Tier 0 = fully typed (domain and range are specific classes),
        1 = typed domain, 2 = typed range, 3 = the `Entity -> Entity`
        catch-alls. Typed relations come first: they carry the meaning, the
        catch-alls only satisfy the domain/range constraint.
        """
        compatible = self.ontology.compatible_properties(subject_class, object_class)
        return self._rank_properties(compatible, relation, subject_class, object_class)

    def relaxed_candidates(
        self, subject_class: str, object_class: str, relation: str
    ) -> list[tuple[str, int]]:
        """Near-miss properties: one side of the type constraint fits.

        They are **not** gate-valid — the gate rejects them and explains
        why. They are offered as a fallback only, so a class pair with no
        confident typed DUL relation still gets the semantically right
        candidate; the strict gate then disposes of the result and the retry
        loop asks Jev again with different choices.
        """
        if not self.settings.jev_allow_relaxed_candidates:
            return []
        relaxed = self.ontology.relaxed_properties(subject_class, object_class)
        return self._rank_properties(relaxed, relation, subject_class, object_class)

    def _context_text(self, subject_class: str, object_class: str) -> str:
        """The ontology's own description of the two classes.

        Using the *comments* and not just the names matters: DUL calls a
        `PhysicalPlace` "a physical object that is inherently **located**",
        and that is exactly the word a relation like `hasLocation` needs in
        order to be found. The context is only ever a tie-breaker for the
        generic relations, so its vocabulary never outweighs the relation
        phrase itself.
        """
        parts: list[str] = []
        limit = self.settings.jev_option_comment_chars
        for uri in (subject_class, object_class):
            term = self.ontology.classes.get(uri)
            if term is None:
                continue
            parts.append(term.name)
            if term.comment:
                # Only the head of the definition: a DUL comment can run for
                # thousands of characters (see `Event`) and an unbounded
                # context would turn every relation into a match.
                parts.append(term.comment[:limit])
        return " ".join(parts)

    def _rank_properties(
        self,
        uris: list[str],
        relation: str,
        subject_class: str,
        object_class: str,
    ) -> list[tuple[str, int]]:
        """Order properties by ontology-derived relevance.

        The key is a tuple, so it is deterministic and needs no weights:

        1. how specific the relation's declared types are for the two
           classes at hand (a relation declared `Agent -> SocialAgent`
           says far more than one declared `Entity -> Entity`) — this is
           what keeps the typed relations ahead of the catch-alls;
        2. how well the relation phrase matches the relation's own name and
           comment (the ontology's own vocabulary), with the ontology's
           description of the two classes breaking the remaining ties;
        3. how central the relation is in the property hierarchy: when two
           relations tie on both counts above, the shallow one is the safer
           offer. Depth is specialisation, and a deep specialisation that
           happens to sit in the first window (`isPreconditionOf`) hides a
           genuinely useful catch-all (`associatedWith`) that Jev would
           otherwise never see;
        4. the name — only to make the order total.
        """
        context = self._context_text(subject_class, object_class)
        scored: list[tuple[int, float, int, str, str]] = []
        for uri in uris:
            prop = self.ontology.object_properties[uri]
            subject_spec = self.ontology.type_specificity(subject_class, prop.domain)
            object_spec = self.ontology.type_specificity(object_class, prop.range)
            scored.append(
                (
                    -(subject_spec + object_spec),
                    -round(self.lexicon._affinity(relation, prop, context), 6),
                    self.lexicon._property_depth.get(uri, 0),
                    prop.name,
                    uri,
                )
            )
        scored.sort()
        return [
            (uri, self.ontology.specificity_tier(uri))
            for _spec, _aff, _depth, _name, uri in scored
        ]

    def _build_property_plans(
        self,
        requests: list[tuple[str, str, str, str, str]],
        exclude: dict[str, set[str]] | None = None,
        notes: dict[str, str] | None = None,
        allow_relaxed: bool = True,
    ) -> list[_PropertyPlan]:
        """Build one plan per relation (no Jev call is made here).

        `exclude` removes already-rejected properties from the option list
        (the "different choices" of the retry loop) and `notes` carries the
        gate's complaint into the instructions. `allow_relaxed` controls
        whether the near-miss candidates are put on the table at all.
        """
        exclude = exclude or {}
        notes = notes or {}
        plans: list[_PropertyPlan] = []

        for subject, subject_class, relation, obj, object_class in requests:
            key = pair_key(subject, relation, obj)
            excluded = exclude.get(key, set())
            strict = [
                (uri, tier)
                for uri, tier in self.property_candidates(
                    subject_class, object_class, relation
                )
                if uri not in excluded
            ]
            relaxed = [
                (uri, tier)
                for uri, tier in self.relaxed_candidates(
                    subject_class, object_class, relation
                )
                if uri not in excluded
            ]
            if not allow_relaxed:
                relaxed = []
            mapping = PropertyMapping(
                subject=subject,
                relation=relation,
                object=obj,
                candidates=[self.ontology.property_name(uri) for uri, _ in strict],
                relaxed_candidates=[
                    self.ontology.property_name(uri) for uri, _ in relaxed
                ],
            )
            plan = _PropertyPlan(
                key=key,
                mapping=mapping,
                strict_uris=[uri for uri, _ in strict],
            )
            plans.append(plan)
            if not strict and not relaxed:
                mapping.note = "no DUL property admits this subject/object class pair"
                continue

            candidates = [*strict, *relaxed]
            plan.key_map = self.lexicon._property_keys([uri for uri, _tier in candidates])
            plan.tiers = {
                key_: tier
                for key_, (_uri, tier) in zip(
                    plan.key_map.items(), candidates, strict=True
                )
            }
            plan.specificity = {
                uri: self._pair_specificity(uri, subject_class, object_class)
                for uri, _tier in candidates
            }
            note = notes.get(key, "")
            plan.instructions = (
                f"Which DOLCE relation expresses '{relation}' between '{subject}' "
                f"(class {self.ontology.class_name(subject_class)}) and '{obj}' "
                f"(class {self.ontology.class_name(object_class)})? "
                "Use the DOLCE meaning of the relation, not a loose synonym."
            )
            if note:
                plan.instructions = (
                    f"{plan.instructions} The previous attempt failed: {note}"
                )
            plan.near_instructions = (
                "If none of the type-correct DOLCE relations fits, which "
                f"relation is the closest fit for '{relation}' between "
                f"'{subject}' and '{obj}'? It will be checked against the "
                "DOLCE domain and range constraints afterwards."
            )

            plan.strict_windows = self._windows(plan.strict_uris, plan.key_map)
            plan.relaxed_windows = self._windows(
                [uri for uri, _ in relaxed], plan.key_map
            )
            if not plan.strict_windows and not plan.relaxed_windows:
                mapping.note = "no DUL property admits this subject/object class pair"
        return plans

    def _property_requests(
        self,
        plans: list[_PropertyPlan],
        near: bool,
        meta: dict[str, tuple[str, int, bool]],
        min_confidence: float,
    ) -> list[_WindowRequest]:
        """One `_WindowRequest` per window of every plan (one batched round).

        A window is an independent choice, so asking them one round at a time
        would only burn round trips on candidates Jev has already been able to
        refuse in the same breath.
        """
        none_label = (
            self.settings.jev_none_option_key
            if self.settings.jev_include_none_option
            else None
        )
        out: list[_WindowRequest] = []
        for plan in plans:
            windows = plan.relaxed_windows if near else plan.strict_windows
            instructions = plan.near_instructions if near else plan.instructions
            suffix = "::near#" if near else "#"
            for index, window in enumerate(windows):
                qid = f"prop::{plan.key}{suffix}{index}"
                meta[qid] = (plan.key, index, near)
                out.append(
                    _WindowRequest(
                        qid=qid,
                        instructions=instructions,
                        windows=[window],
                        none_label=none_label,
                        key_map=plan.key_map,
                        tiers=plan.tiers,
                        min_confidence=min_confidence,
                    )
                )
        return out

    async def _run_property_phase(
        self,
        plans: list[_PropertyPlan],
        state: str,
        near: bool,
        min_confidence: float,
    ) -> tuple[dict[str, tuple[str, int, bool]], dict[str, JevOutcome]]:
        """Ask one property phase and return `(meta, outcomes)`."""
        meta: dict[str, tuple[str, int, bool]] = {}
        requests = self._property_requests(plans, near, meta, min_confidence)
        if not requests:
            return meta, {}
        outcomes = await self._windowed_answers(
            requests,
            state,
            min_confidence=min_confidence,
            resolve_weak=False,
        )
        return meta, outcomes

    async def map_properties(
        self,
        requests: list[tuple[str, str, str, str, str]],
        state: str,
        exclude: dict[str, set[str]] | None = None,
        notes: dict[str, str] | None = None,
        allow_relaxed: bool = True,
    ) -> dict[str, PropertyMapping]:
        """Map relations onto DUL properties.

        `requests` are `(subject, subject_class, relation, object, object_class)`
        tuples. Every one of them becomes its own Choice question — one per
        window — and every question travels in the same request, so the whole
        stage costs one round trip no matter how many relations or windows it
        has. Each window carries its own "none of these" escape hatch, which
        is how Jev refuses a set of candidates; the first window that earns a
        commitment is the one that decides, because it holds the best-ranked
        candidates.

        Three phases, run only as far as they are needed:

        1. **strict** — every candidate the gate would accept;
        2. **near miss** (`allow_relaxed`) — when no type-correct candidate
           expresses the relation, Jev's closest guess. The gate rejects it
           by construction, the pipeline hands the complaint back and the
           next round re-asks with different choices — that feedback loop is
           what turns a hard failure into a type-correct triple;
        3. **catch-all** — when Jev commits to nothing, the root of the
           property hierarchy (DUL's own documented catch-all), flagged as a
           fallback and carrying Jev's ranking of the candidates it refused.

        `exclude` removes already-rejected properties from the option list
        (the "different choices" of the retry loop) and `notes` carries the
        gate's complaint into the instructions.
        """
        min_confidence = self.settings.jev_min_property_confidence
        plans = self._build_property_plans(requests, exclude, notes, allow_relaxed)
        by_key = {plan.key: plan for plan in plans}

        # %% Phase 1 — the candidates the gate would accept
        meta, outcomes = await self._run_property_phase(
            plans, state, near=False, min_confidence=min_confidence
        )
        self._apply_property_answers(by_key, meta, outcomes, False)

        # %% Phase 2 — the near misses, only for relations still undecided
        if allow_relaxed:
            undecided = [plan for plan in plans if not plan.mapping.decided]
            meta, outcomes = await self._run_property_phase(
                undecided, state, near=True, min_confidence=min_confidence
            )
            self._apply_property_answers(by_key, meta, outcomes, True)

        # %% Phase 3 — DUL's catch-all for what Jev refused to decide
        for plan in plans:
            if not plan.mapping.decided:
                self._apply_catchall(plan)
        return {plan.key: plan.mapping for plan in plans}

    async def repair_round(
        self,
        requests: list[tuple[str, str, str, str, str]],
        state: str,
        deps: dict[str, Any],
        exclude: dict[str, set[str]] | None = None,
        notes: dict[str, str] | None = None,
        class_requests: list[ClassRepairRequest] | None = None,
        exclude_classes: dict[str, set[str]] | None = None,
    ) -> tuple[dict[str, ClassMapping], dict[str, PropertyMapping]]:
        """Repair one failed round with **one** batched Jev request.

        A gate rejection has two possible causes: the relation is wrong, or
        the class of one of its ends is. Repairing them in two separate
        rounds would cost two round trips and, worse, would spend the second
        round on a class that the first round's new relation may no longer
        need. Both kinds of question therefore travel together:

        * the **property re-ask** — strict candidates only (the near-miss
          phase is exactly what just failed), rejected relations excluded and
          the gate's complaint in the instructions;
        * the **class repair** (`class_requests`) — only the classes that
          satisfy the rejected relation's type constraint, computed with the
          gate's own schema, so a repaired class can never be rejected again
          for that relation.

        The caller gets both results and decides how to combine them (the
        pipeline restores the original relation when the repaired class makes
        it legal).
        """
        class_requests = class_requests or []
        min_confidence = self.settings.jev_min_property_confidence
        plans = self._build_property_plans(
            requests, exclude, notes, allow_relaxed=False
        )
        by_key = {plan.key: plan for plan in plans}
        meta: dict[str, tuple[str, int, bool]] = {}
        property_requests = self._property_requests(
            plans, False, meta, min_confidence
        )
        class_plans, class_meta = self.repair_plans(
            class_requests, deps, exclude_classes
        )
        merged = [*property_requests, *class_plans]
        if not merged:
            return {}, {plan.key: plan.mapping for plan in plans}

        outcomes = await self._windowed_answers(merged, state)
        repaired_classes = self.apply_class_repairs(
            outcomes, class_plans, class_meta
        )
        self._apply_property_answers(by_key, meta, outcomes, False)
        for plan in plans:
            if not plan.mapping.decided:
                self._apply_catchall(plan)
        return repaired_classes, {plan.key: plan.mapping for plan in plans}

    def _apply_property_answers(
        self,
        plans: dict[str, _PropertyPlan],
        meta: dict[str, tuple[str, int, bool]],
        outcomes: dict[str, JevOutcome],
        is_fallback: bool,
    ) -> None:
        """Copy the answers of one phase onto the mappings.

        `meta` walks the questions in window order, so the first window that
        earns a commitment is the one that decides: it holds the best-ranked
        candidates, and a later window may only answer where an earlier one
        was refused. Everything Jev said in the other windows is still kept,
        merged per option, because that ranking is what a fallback decision
        is measured against.
        """
        for qid, (key, window_index, near) in meta.items():
            if near != is_fallback:
                continue
            plan = plans.get(key)
            if plan is None:
                continue
            mapping = plan.mapping
            if mapping.decided:
                # Either the best-ranked strict window already won, or a near
                # miss never overrides a relation the gate would accept.
                continue
            outcome = outcomes.get(qid)
            if outcome is None:
                if not is_fallback and not mapping.note:
                    mapping.note = "no answer returned"
                continue
            mapping.probabilities.update(outcome.probabilities)
            answer = outcome.answer
            if answer is None:
                if not is_fallback and not mapping.note:
                    mapping.note = "Jev accepted none of the offered DOLCE relations"
                continue
            uri = plan.key_map.get(answer.choice)
            if uri is None:
                if not is_fallback and not mapping.note:
                    mapping.note = f"unknown option returned: {answer.choice}"
                continue
            mapping.property_uri = uri
            mapping.property_name = self.ontology.property_name(uri)
            mapping.confidence = round(float(answer.confidence), 4)
            mapping.tier = int(plan.tiers.get(answer.choice, 3))
            mapping.window = window_index
            mapping.decided = True
            mapping.fallback_used = is_fallback
            mapping.specificity = plan.specificity.get(uri, 0)

    def _apply_catchall(self, plan: _PropertyPlan) -> None:
        """Fall back to the root of the property hierarchy, clearly flagged."""
        if not self.settings.jev_catchall_fallback:
            return
        uri = self.lexicon._root_property
        if uri is None or uri not in plan.strict_uris:
            plan.mapping.note = plan.mapping.note or (
                "Jev accepted none of the offered DOLCE relations"
            )
            return
        mapping = plan.mapping
        name = self.ontology.property_name(uri)
        catchall_key = next(
            (k for k, u in plan.key_map.items() if u == uri),
            "",
        )
        # How much probability Jev gave the catch-all itself when it saw it —
        # never a commitment, but the honest number to put next to a fallback.
        offered = mapping.probabilities.get(catchall_key, 0.0)
        mapping.property_uri = uri
        mapping.property_name = name
        mapping.confidence = round(float(offered), 4)
        mapping.tier = int(self.ontology.specificity_tier(uri))
        mapping.window = -1
        mapping.decided = True
        mapping.fallback_used = True
        mapping.specificity = plan.specificity.get(uri, 0)
        mapping.note = (
            f"{mapping.note}; " if mapping.note else ""
        ) + (
            f"Jev accepted no DOLCE relation for '{mapping.relation}'; "
            f"used the DUL catch-all '{name}'"
        )

    def _windows(
        self, uris: list[str], key_map: dict[str, str]
    ) -> list[dict[str, str]]:
        """Split the ranked candidates into Jev-sized windows.

        The first window always carries the root of the property hierarchy —
        DUL's own catch-all, and what this mapper falls back to when Jev
        commits to nothing. It belongs *on the table*, so Jev can choose it
        deliberately instead of having it smuggled in afterwards: it is moved
        into the first window from wherever the ranking placed it, and the
        candidate it displaces simply waits in a later window.
        """
        limit = max(1, self.settings.jev_max_property_windows)
        chunks = _chunks(uris, self._window_size())[:limit]
        root = self.lexicon._root_property
        if (
            root is not None
            and len(chunks) > 1
            and chunks[0]
            and root not in chunks[0]
        ):
            for index in range(1, len(chunks)):
                if root in chunks[index]:
                    displaced = chunks[0][-1]
                    chunks[0][-1] = root
                    chunks[index].remove(root)
                    chunks[index].insert(0, displaced)
                    break
        return [
            {
                key: self.lexicon._property_option(uri)
                for key, uri in key_map.items()
                if uri in chunk
            }
            for chunk in chunks
        ]

    def _pair_specificity(
        self, uri: str, subject_class: str, object_class: str
    ) -> int:
        """How specific a relation's declared types are for this class pair."""
        prop = self.ontology.object_properties.get(uri)
        if prop is None:
            return 0
        return self.ontology.type_specificity(
            subject_class, prop.domain
        ) + self.ontology.type_specificity(object_class, prop.range)
