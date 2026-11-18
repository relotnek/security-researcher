import json
import math
import re
import tempfile
import unittest
from pathlib import Path

from autoresearch.audit import AuditLog
from autoresearch.frontier import (
    Frontier,
    FrontierError,
    ScoringConfig,
    canonical_key,
    combine,
    normalize,
    novelty_of,
    score,
    validate_task,
)
from autoresearch.state import DeadEnd, FrontierTask, StateStore, Target, TaskStatus
from autoresearch.taxonomy import TargetType

DOCS = Path(__file__).parent.parent / "docs" / "frontier.md"


def task(**overrides):
    base = {
        "target_id": "tgt-fw",
        "objective": "Audit CGI handlers for unchecked strcpy",
        "action_class": "static_analysis",
        "estimates": {"likelihood": 0.5, "impact": 8.0, "value": 6.0, "cost": 2.0},
        "provenance": {"source": "worker", "episode_id": "ep-1"},
    }
    estimates = overrides.pop("estimates", None)
    base.update(overrides)
    if estimates is not None:
        base["estimates"] = {**base["estimates"], **estimates}
    return base


class FrontierTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = StateStore(self.root / "state")
        self.audit = AuditLog(self.root / "audit.jsonl")
        self.store.put(Target(id="tgt-fw", engagement_id="eng-1", asset="fw.bin", target_type=TargetType.FIRMWARE))
        self.store.put(Target(id="tgt-web", engagement_id="eng-2", asset="app.test", target_type=TargetType.WEB_APP))
        self.frontier = self.fresh()

    def fresh(self) -> Frontier:
        """A new Frontier over the same durable state: a cold-started process."""
        return Frontier(StateStore(self.root / "state"), self.audit)

    def ready_ids(self):
        return [t.id for t in self.fresh().peek(100)]


class TaskShapeTest(FrontierTestCase):
    def test_well_formed_task_is_accepted_scored_and_ready(self):
        result = self.frontier.enqueue(task(regions=["code:httpd/cgi"]))
        self.assertEqual(result.outcome, "enqueued")
        stored = self.store.get(FrontierTask, result.task.id)
        self.assertEqual(stored, result.task)
        self.assertEqual(stored.engagement_id, "eng-1")  # taken from the target
        self.assertEqual(stored.objective, "Audit CGI handlers for unchecked strcpy")
        self.assertEqual(stored.action_class, "static_analysis")
        self.assertEqual(stored.estimates, {"likelihood": 0.5, "impact": 8.0, "value": 6.0, "cost": 2.0})
        self.assertEqual(stored.provenance, {"source": "worker", "episode_id": "ep-1"})
        self.assertIs(stored.status, TaskStatus.QUEUED)
        self.assertGreater(stored.priority, 0)
        self.assertEqual(self.ready_ids(), [stored.id])

    def test_task_missing_any_required_field_is_rejected(self):
        for missing in ("target_id", "objective", "action_class", "estimates", "provenance"):
            with self.subTest(missing=missing):
                submission = task()
                del submission[missing]
                with self.assertRaisesRegex(FrontierError, missing):
                    self.frontier.enqueue(submission)
        for factor in ("likelihood", "impact", "value", "cost"):
            with self.subTest(missing_estimate=factor):
                submission = task()
                del submission["estimates"][factor]
                with self.assertRaisesRegex(FrontierError, factor):
                    self.frontier.enqueue(submission)
        self.assertEqual(self.store.list(FrontierTask), [])  # nothing unscoreable was queued

    def test_other_malformed_tasks_are_rejected(self):
        bad = [
            task(objective="   "),
            task(objective="check it"),  # says nothing about what to investigate
            task(action_class="wing_it"),
            task(estimates={"likelihood": "high"}),
            task(estimates={"cost": float("nan")}),
            task(estimates={"likelihood": True}),
            task(estimates={"novelty": 1.0}),  # derived, not estimated
            task(provenance={"episode_id": "ep-1"}),  # no source
            task(regions="code:httpd"),
            task(target_id="tgt-nope"),
            task(surprise="field"),
            "not a mapping",
        ]
        for submission in bad:
            with self.subTest(submission=submission), self.assertRaises(FrontierError):
                self.frontier.enqueue(submission)
        self.assertEqual(self.store.list(FrontierTask), [])

    def test_documented_example_validates_as_written(self):
        blocks = re.findall(r"```json\n(.*?)```", DOCS.read_text(), re.S)
        self.assertEqual(len(blocks), 1)
        example = json.loads(blocks[0])
        validated = validate_task(example)
        self.assertEqual(validated["target_id"], example["target_id"])
        # ...and is accepted by a frontier that knows the target it references.
        self.store.put(
            Target(id=example["target_id"], engagement_id="eng-1", asset="router", target_type=TargetType.FIRMWARE)
        )
        self.assertEqual(self.frontier.enqueue(example).outcome, "enqueued")
        # Every field and estimate the validator knows is documented.
        text = DOCS.read_text()
        for name in ("target_id", "objective", "action_class", "estimates", "provenance", "regions",
                     "likelihood", "impact", "value", "cost"):
            self.assertIn(f"| `{name}` |", text)


class NormalizationTest(unittest.TestCase):
    def test_boundaries(self):
        cases = [
            ("likelihood", 0, 0.0), ("likelihood", 1, 1.0), ("likelihood", 0.25, 0.25),
            ("impact", 0, 0.0), ("impact", 10, 1.0), ("impact", 5, 0.5),
            ("value", 0, 0.0), ("value", 10, 1.0), ("value", 2.5, 0.25),
            ("cost", 0, 0.0), ("cost", 4, 0.5), ("cost", 12, 0.75),
            ("novelty", 0, 0.0), ("novelty", 1, 1.0), ("novelty", 0.5, 0.5),
        ]  # fmt: skip
        for factor, raw, expected in cases:
            with self.subTest(factor=factor, raw=raw):
                self.assertAlmostEqual(normalize(factor, raw), expected)

    def test_out_of_range_inputs_are_clamped(self):
        for factor in ("likelihood", "impact", "value", "cost", "novelty"):
            with self.subTest(factor=factor):
                self.assertEqual(normalize(factor, -5), 0.0)
                self.assertEqual(normalize(factor, float("-inf")), 0.0)
                self.assertEqual(normalize(factor, float("inf")), 1.0)
                for raw in (-1e9, -0.001, 0, 0.5, 1, 7, 10, 11, 1e12):
                    self.assertTrue(0.0 <= normalize(factor, raw) <= 1.0)
        self.assertEqual(normalize("likelihood", 1.7), 1.0)
        self.assertEqual(normalize("impact", 42), 1.0)
        self.assertEqual(normalize("value", 10.01), 1.0)
        self.assertLess(normalize("cost", 1e12), 1.0 + 1e-12)

    def test_cost_is_monotonic(self):
        values = [normalize("cost", c) for c in (0, 0.5, 1, 2, 4, 8, 100)]
        self.assertEqual(values, sorted(values))
        self.assertEqual(len(set(values)), len(values))

    def test_non_numbers_rejected(self):
        for raw in (None, "0.5", float("nan"), True, [1]):
            with self.subTest(raw=raw), self.assertRaises(FrontierError):
                normalize("likelihood", raw)
        with self.assertRaises(FrontierError):
            normalize("vibes", 0.5)

    def test_scales_are_configurable(self):
        config = ScoringConfig(impact_max=5, value_max=100, cost_half=1)
        self.assertEqual(normalize("impact", 5, config), 1.0)
        self.assertEqual(normalize("value", 50, config), 0.5)
        self.assertEqual(normalize("cost", 1, config), 0.5)


class CombinationTest(FrontierTestCase):
    FACTORS = {"likelihood": 0.5, "impact": 0.8, "value": 0.6, "cost": 0.25, "novelty": 1.0}

    def test_formula_with_cost_in_the_denominator(self):
        c = ScoringConfig()
        expected = (0.35 * 0.5 + 0.25 * 0.8 + 0.20 * 0.6 + 0.20 * 1.0) / (1.0 * 0.25 + 0.25)
        self.assertAlmostEqual(combine(self.FACTORS, c), expected)
        self.assertGreater(combine({**self.FACTORS, "cost": 0.1}), combine(self.FACTORS))
        self.assertLess(combine({**self.FACTORS, "cost": 0.9}), combine(self.FACTORS))
        self.assertTrue(math.isfinite(combine({**self.FACTORS, "cost": 0.0})))
        for factor in ("likelihood", "impact", "value", "novelty"):
            self.assertGreater(combine({**self.FACTORS, factor: 1.0}), combine({**self.FACTORS, factor: 0.1}))

    def test_weights_are_configurable(self):
        only_impact = ScoringConfig(w_likelihood=0, w_value=0, w_novelty=0, w_impact=1, w_cost=0, epsilon=1)
        self.assertAlmostEqual(combine(self.FACTORS, only_impact), 0.8)
        self.assertEqual(ScoringConfig.from_dict({"w_impact": 0.9}).w_impact, 0.9)
        for bad in ({"epsilon": 0}, {"w_cost": -1}, {"w_impact": float("nan")}, {"bogus": 1}):
            with self.subTest(bad=bad), self.assertRaises(FrontierError):
                ScoringConfig.from_dict(bad)

    def test_identical_inputs_yield_identical_scores(self):
        estimates = {"likelihood": 0.37, "impact": 7.3, "value": 4.1, "cost": 3.3}
        self.assertEqual(score(estimates, 0.6), score(dict(estimates), 0.6))
        a = self.frontier.enqueue(task(estimates=estimates, objective="overflow in upload parser")).task
        b = self.frontier.enqueue(task(estimates=estimates, objective="race in session cleanup")).task
        self.assertEqual(a.priority, b.priority)
        self.assertEqual(self.fresh()._store.get(FrontierTask, a.id).priority, a.priority)

    def test_tasks_from_two_targets_share_one_deterministically_ordered_queue(self):
        estimates = {"likelihood": 0.5, "impact": 8.0, "value": 6.0, "cost": 2.0}
        same_fw = self.frontier.enqueue(task(target_id="tgt-fw", objective="overflow in upload parser")).task
        same_web = self.frontier.enqueue(task(target_id="tgt-web", objective="overflow in upload parser")).task
        # Same factors on different targets and engagements -> the same priority.
        self.assertEqual(same_fw.priority, same_web.priority)
        self.assertEqual(same_fw.priority, score(estimates, same_fw.novelty))

        high_web = self.frontier.enqueue(
            task(target_id="tgt-web", objective="sql injection in search", estimates={"likelihood": 0.9})
        ).task
        low_fw = self.frontier.enqueue(
            task(target_id="tgt-fw", objective="weak rng in token", estimates={"likelihood": 0.1})
        ).task
        # One queue, interleaving targets by priority; the exact tie resolves by age.
        expected = [high_web.id, same_fw.id, same_web.id, low_fw.id]
        self.assertEqual(self.ready_ids(), expected)
        self.assertEqual(self.ready_ids(), expected)  # stable across cold starts
        self.assertEqual([t.id for t in self.fresh().peek(100, engagement_id="eng-2")], [high_web.id, same_web.id])


class NoveltyTest(FrontierTestCase):
    def test_novelty_is_the_unexplored_fraction_of_the_footprint(self):
        explored = {"code:a", "code:b"}
        self.assertEqual(novelty_of(["code:c"], explored), 1.0)
        self.assertEqual(novelty_of(["code:a"], explored), 0.0)
        self.assertEqual(novelty_of(["code:a", "code:c"], explored), 0.5)
        self.assertEqual(novelty_of(["Code:A ", "code:b"], explored), 0.0)  # normalized
        self.assertEqual(novelty_of([], explored), ScoringConfig().unknown_novelty)

    def test_unexplored_region_outscores_equivalent_but_explored(self):
        # Explore the CGI region by dispatching a task over it.
        self.frontier.enqueue(task(objective="map the cgi dispatch table", regions=["code:httpd/cgi"]))
        self.assertIsNotNone(self.frontier.pop_highest())

        # Two tasks identical in likelihood, impact, value and cost.
        trodden = self.frontier.enqueue(task(objective="format string in cgi logger", regions=["code:httpd/cgi"])).task
        novel = self.frontier.enqueue(task(objective="format string in upnp logger", regions=["code:upnpd"])).task
        self.assertEqual(trodden.estimates, novel.estimates)
        self.assertEqual((trodden.novelty, novel.novelty), (0.0, 1.0))
        self.assertGreater(novel.priority, trodden.priority)
        self.assertEqual(self.ready_ids(), [novel.id, trodden.id])  # despite being enqueued second

    def test_dispatching_a_task_lowers_the_novelty_of_queued_tasks_sharing_its_region(self):
        first = self.frontier.enqueue(task(objective="overflow in cgi login", regions=["code:httpd/cgi"])).task
        second = self.frontier.enqueue(task(objective="overflow in cgi upload", regions=["code:httpd/cgi"])).task
        other = self.frontier.enqueue(task(objective="overflow in upnp soap", regions=["code:upnpd"])).task
        other_target = self.frontier.enqueue(
            task(target_id="tgt-web", objective="overflow in cgi login", regions=["code:httpd/cgi"])
        ).task
        self.assertEqual(second.novelty, 1.0)

        self.assertEqual(self.frontier.pop_highest().id, first.id)
        get = lambda t: self.store.get(FrontierTask, t.id)  # noqa: E731
        self.assertEqual(get(second).novelty, 0.0)
        self.assertLess(get(second).priority, second.priority)
        self.assertEqual(get(other).priority, other.priority)  # different region: untouched
        self.assertEqual(get(other_target).priority, other_target.priority)  # coverage is per target
        # The change is a recorded event naming its cause.
        updates = self.audit.entries("frontier.novelty_update")
        self.assertEqual([(u["task_id"], u["cause"]) for u in updates], [(second.id, first.id)])


class EquivalenceTest(FrontierTestCase):
    def test_reworded_duplicates_share_a_key(self):
        rewordings = [
            "Audit CGI handlers for unchecked strcpy",
            "Check the CGI handlers for any unchecked strcpy()",
            "check for unchecked strcpy in the CGI handler",
            "Investigate whether CGI handlers have an unchecked strcpy.",
            "UNCHECKED STRCPY — CGI HANDLERS",
        ]
        keys = {canonical_key("tgt-fw", o, "static_analysis") for o in rewordings}
        self.assertEqual(len(keys), 1, keys)

    def test_distinct_tasks_get_distinct_keys(self):
        base = canonical_key("tgt-fw", "unchecked strcpy in CGI handlers", "static_analysis")
        different = [
            canonical_key("tgt-web", "unchecked strcpy in CGI handlers", "static_analysis"),  # target
            canonical_key("tgt-fw", "unchecked strcpy in CGI handlers", "fuzzing"),  # action class
            canonical_key("tgt-fw", "unchecked sprintf in CGI handlers", "static_analysis"),  # objective
            canonical_key("tgt-fw", "unchecked strcpy in UPnP handlers", "static_analysis"),
            canonical_key("tgt-fw", "unchecked strcpy in CGI handlers", "static_analysis", "arm build"),
        ]
        self.assertEqual(len({base, *different}), 6)

    def test_duplicate_of_an_open_task_is_merged(self):
        original = self.frontier.enqueue(task(regions=["code:httpd/cgi"])).task
        result = self.frontier.enqueue(
            task(
                objective="Check the CGI handlers for any unchecked strcpy()",
                provenance={"source": "worker", "episode_id": "ep-2"},
                estimates={"likelihood": 0.99},
                regions=["code:httpd/cgi/login.c"],
            )
        )
        self.assertEqual(result.outcome, "merged")
        self.assertEqual(result.task.id, original.id)
        self.assertEqual(len(self.store.list(FrontierTask)), 1)  # no duplicate
        merged = self.store.get(FrontierTask, original.id)
        self.assertEqual(merged.merged_provenance[0]["episode_id"], "ep-2")
        self.assertEqual(merged.regions, ["code:httpd/cgi", "code:httpd/cgi/login.c"])
        self.assertEqual(merged.estimates, original.estimates)  # estimates change only by re-score
        self.assertEqual(len(self.audit.entries("frontier.merge")), 1)

        # Still merged while the original is in progress, not just while queued.
        self.assertEqual(self.frontier.pop_highest().id, original.id)
        self.assertEqual(self.frontier.enqueue(task()).outcome, "merged")
        self.assertEqual(len(self.store.list(FrontierTask)), 1)

    def test_distinguisher_keeps_genuinely_distinct_tasks_apart(self):
        self.frontier.enqueue(task())
        result = self.frontier.enqueue(task(provenance={"source": "worker", "distinguisher": "mips build"}))
        self.assertEqual(result.outcome, "enqueued")
        self.assertEqual(len(self.store.list(FrontierTask)), 2)

    def test_equivalent_of_a_dead_end_is_deprioritized_below_novel_tasks(self):
        strong = {"likelihood": 1.0, "impact": 10.0, "value": 10.0, "cost": 0.0}
        weak = {"likelihood": 0.01, "impact": 0.1, "value": 0.1, "cost": 50.0}
        doomed = self.frontier.enqueue(task(estimates=strong)).task
        self.frontier.mark_dead_end(doomed.id, "every strcpy in the CGI handlers is length-checked")

        novel = self.frontier.enqueue(task(objective="weak rng in session token", estimates=weak)).task
        retry = self.frontier.enqueue(
            task(objective="check for unchecked strcpy in the CGI handler", estimates=strong)
        )
        self.assertEqual(retry.outcome, "deprioritized")
        self.assertTrue(retry.task.dead_end_equivalent)
        # Best possible estimates, yet below the weakest novel task - in order and in score.
        self.assertEqual(self.ready_ids(), [novel.id, retry.task.id])
        self.assertLess(retry.task.priority, score(strong, retry.task.novelty))
        # A dead-end on one target does not taint the same objective on another.
        elsewhere = self.frontier.enqueue(task(target_id="tgt-web", estimates=strong))
        self.assertEqual(elsewhere.outcome, "enqueued")
        self.assertEqual(self.ready_ids()[0], elsewhere.task.id)


class OperationsTest(FrontierTestCase):
    def enqueue_three(self):
        low = self.frontier.enqueue(task(objective="weak rng in token", estimates={"likelihood": 0.1})).task
        high = self.frontier.enqueue(task(objective="overflow in upload", estimates={"likelihood": 0.9})).task
        mid = self.frontier.enqueue(task(objective="race in cleanup", estimates={"likelihood": 0.5})).task
        return low, mid, high

    def test_peek_does_not_remove(self):
        low, mid, high = self.enqueue_three()
        self.assertEqual([t.id for t in self.frontier.peek()], [high.id])
        self.assertEqual([t.id for t in self.frontier.peek(2)], [high.id, mid.id])
        self.assertEqual(self.ready_ids(), [high.id, mid.id, low.id])
        self.assertEqual(self.frontier.peek(0), [])

    def test_pop_highest_returns_and_removes_the_top_ready_task(self):
        low, mid, high = self.enqueue_three()
        popped = self.frontier.pop_highest()
        self.assertEqual(popped.id, high.id)
        self.assertIs(popped.status, TaskStatus.IN_PROGRESS)
        self.assertIs(self.store.get(FrontierTask, high.id).status, TaskStatus.IN_PROGRESS)
        self.assertEqual(self.ready_ids(), [mid.id, low.id])
        # Each cold-started caller gets the next one; nothing is handed out twice.
        self.assertEqual(self.fresh().pop_highest().id, mid.id)
        self.assertEqual(self.fresh().pop_highest().id, low.id)
        self.assertIsNone(self.fresh().pop_highest())
        self.assertEqual(len(self.audit.entries("frontier.pop")), 3)

    def test_pop_can_be_limited_to_an_engagement(self):
        self.enqueue_three()
        web = self.frontier.enqueue(task(target_id="tgt-web", estimates={"likelihood": 0.01})).task
        self.assertEqual(self.frontier.pop_highest(engagement_id="eng-2").id, web.id)
        self.assertIsNone(self.frontier.pop_highest(engagement_id="eng-2"))
        self.assertIsNone(self.frontier.pop_highest(engagement_id="eng-none"))

    def test_mark_dead_end_records_and_removes_from_the_ready_set(self):
        low, mid, high = self.enqueue_three()
        # A queued task...
        record = self.frontier.mark_dead_end(high.id, "upload size is bounded upstream")
        self.assertEqual(self.ready_ids(), [mid.id, low.id])
        self.assertIs(self.store.get(FrontierTask, high.id).status, TaskStatus.DEAD_END)
        self.assertEqual(self.store.list(DeadEnd), [record])
        self.assertEqual((record.task_id, record.equivalence_key), (high.id, high.equivalence_key))
        self.assertEqual(record.reason, "upload size is bounded upstream")
        # ...and one a worker already has in hand.
        popped = self.frontier.pop_highest()
        self.frontier.mark_dead_end(popped.id, "cleanup holds the lock")
        self.assertEqual(self.ready_ids(), [low.id])
        self.assertEqual(len(self.store.list(DeadEnd)), 2)
        # Dead-ends are never dispatched.
        self.assertEqual(self.frontier.pop_highest().id, low.id)
        self.assertIsNone(self.frontier.pop_highest())

    def test_invalid_operations_are_rejected(self):
        low, _, _ = self.enqueue_three()
        with self.assertRaises(FrontierError):
            self.frontier.mark_dead_end("tsk-nope", "x")
        with self.assertRaises(FrontierError):
            self.frontier.mark_dead_end(low.id, " ")
        self.frontier.mark_dead_end(low.id, "done with it")
        with self.assertRaises(FrontierError):
            self.frontier.mark_dead_end(low.id, "again")
        with self.assertRaises(FrontierError):
            self.frontier.rescore(low.id, evidence="late", likelihood=0.9)


class RescoreTest(FrontierTestCase):
    def test_raising_likelihood_moves_a_queued_task_up(self):
        a = self.frontier.enqueue(task(objective="overflow in upload", estimates={"likelihood": 0.8})).task
        b = self.frontier.enqueue(task(objective="race in cleanup", estimates={"likelihood": 0.5})).task
        c = self.frontier.enqueue(task(objective="weak rng in token", estimates={"likelihood": 0.2})).task
        self.assertEqual(self.ready_ids(), [a.id, b.id, c.id])

        updated = self.frontier.rescore(c.id, evidence="token seeded from uptime (bundle ev-17)", likelihood=0.95)
        self.assertEqual(updated.estimates["likelihood"], 0.95)
        self.assertEqual(updated.estimates["impact"], c.estimates["impact"])  # others untouched
        self.assertGreater(updated.priority, c.priority)
        self.assertEqual(updated.priority, score(updated.estimates, updated.novelty))
        self.assertEqual(self.ready_ids(), [c.id, a.id, b.id])

        logged = self.audit.entries("frontier.rescore")[-1]
        self.assertEqual(logged["task_id"], c.id)
        self.assertEqual(logged["evidence"], "token seeded from uptime (bundle ev-17)")
        self.assertEqual(logged["before"]["estimates"]["likelihood"], 0.2)

    def test_rescore_can_move_a_task_down_and_update_several_factors(self):
        a = self.frontier.enqueue(task(objective="overflow in upload", estimates={"likelihood": 0.8})).task
        b = self.frontier.enqueue(task(objective="race in cleanup", estimates={"likelihood": 0.5})).task
        self.frontier.rescore(a.id, evidence="needs hardware glitching", cost=40, likelihood=0.3)
        self.assertEqual(self.ready_ids(), [b.id, a.id])

    def test_rescore_requires_evidence_and_known_factors(self):
        a = self.frontier.enqueue(task()).task
        for kwargs in (
            {"evidence": "", "likelihood": 0.9},
            {"evidence": "e"},
            {"evidence": "e", "novelty": 1.0},
            {"evidence": "e", "likelihood": "high"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(FrontierError):
                self.frontier.rescore(a.id, **kwargs)
        self.assertEqual(self.store.get(FrontierTask, a.id).priority, a.priority)

    def test_priority_does_not_drift_without_an_event(self):
        a = self.frontier.enqueue(task()).task
        before = len(self.audit.entries())
        for _ in range(3):
            self.assertEqual(self.fresh().peek()[0].priority, a.priority)
        self.assertEqual(len(self.audit.entries()), before)


class EndToEndTest(FrontierTestCase):
    def test_dispatch_order_dead_ends_and_rescoring(self):
        likelihoods = {"alpha": 0.9, "bravo": 0.7, "charlie": 0.5, "delta": 0.3, "echo": 0.1}
        ids = {}
        for name in ("charlie", "echo", "alpha", "delta", "bravo"):  # enqueued out of order
            result = self.fresh().enqueue(
                task(objective=f"overflow in {name} parser", estimates={"likelihood": likelihoods[name]})
            )
            ids[name] = result.task.id
        names = {v: k for k, v in ids.items()}
        order = lambda: [names[i] for i in self.ready_ids()]  # noqa: E731
        self.assertEqual(order(), ["alpha", "bravo", "charlie", "delta", "echo"])

        dispatched = [names[self.fresh().pop_highest().id]]  # alpha
        self.assertEqual(dispatched, ["alpha"])

        # A worker reports bravo's region is a dead-end before it is dispatched,
        # and the task in hand (alpha) turns out to be one as well.
        self.fresh().mark_dead_end(ids["bravo"], "bravo parser is fuzzed upstream")
        self.fresh().mark_dead_end(ids["alpha"], "alpha parser bounds-checks every copy")
        self.assertEqual(order(), ["charlie", "delta", "echo"])

        # New evidence lifts echo from last to first.
        self.fresh().rescore(ids["echo"], evidence="echo parser trusts a length field", likelihood=1.0)
        self.assertEqual(order(), ["echo", "charlie", "delta"])

        # A worker re-proposes the dead bravo idea in other words, with top marks.
        again = self.fresh().enqueue(
            task(objective="Check the bravo parser for an overflow", estimates={"likelihood": 1.0, "cost": 0})
        )
        self.assertEqual(again.outcome, "deprioritized")
        names[again.task.id] = "bravo-again"
        self.assertEqual(order(), ["echo", "charlie", "delta", "bravo-again"])

        # Drain the queue, each pop from a cold-started process.
        while (popped := self.fresh().pop_highest()) is not None:
            dispatched.append(names[popped.id])
        self.assertEqual(dispatched, ["alpha", "echo", "charlie", "delta", "bravo-again"])
        # The original dead-ends were never re-dispatched, and nothing came out twice.
        self.assertNotIn("bravo", dispatched)
        self.assertEqual(len(dispatched), len(set(dispatched)))
        self.assertEqual(len(self.audit.entries("frontier.pop")), 5)
        statuses = {names[t.id]: t.status for t in self.store.list(FrontierTask)}
        self.assertIs(statuses["alpha"], TaskStatus.DEAD_END)
        self.assertIs(statuses["bravo"], TaskStatus.DEAD_END)


if __name__ == "__main__":
    unittest.main()
