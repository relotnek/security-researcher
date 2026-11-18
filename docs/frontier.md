# Frontier

The frontier is the prioritized backlog of investigation tasks. Workers and the
driver use five operations on `autoresearch.frontier.Frontier` and nothing else:

| Operation | Effect |
|---|---|
| `enqueue(task)` | Validate, de-duplicate, score and queue a task. |
| `peek(n)` | The next `n` ready tasks in dispatch order; nothing changes. |
| `pop_highest()` | Return the top ready task and mark it in-progress. |
| `mark_dead_end(task_id, reason)` | Record a dead-end; the task leaves the ready set. |
| `rescore(task_id, evidence=..., **estimates)` | Update estimates from new evidence and recompute priority. |

## Task shape

A task is submitted as a mapping. This example is validated by the test suite
exactly as written:

```json
{
  "target_id": "tgt-router-fw",
  "objective": "Check whether the CGI login handler copies the username with an unchecked strcpy",
  "action_class": "static_analysis",
  "estimates": {
    "likelihood": 0.4,
    "impact": 9.0,
    "value": 8.0,
    "cost": 2
  },
  "provenance": {
    "source": "worker",
    "episode_id": "ep-0042",
    "parent_task_id": "tsk-3f9c2a7d1b60"
  },
  "regions": ["code:httpd/cgi/login.c", "hypothesis:stack-overflow"]
}
```

| Field | Required | Meaning |
|---|---|---|
| `target_id` | yes | Target reference. Must name a stored target; the engagement is taken from it. |
| `objective` | yes | The hypothesis or objective to investigate, in plain words. |
| `action_class` | yes | Intended action class: one of `static_analysis`, `dynamic_analysis`, `network_probe`, `fuzzing`, `exploitation`, `denial_of_service`. |
| `estimates` | yes | All four of the estimates below. |
| `provenance` | yes | What produced the task. `source` is required; anything else is kept as given. |
| `regions` | no | Coverage footprint: the code regions, endpoints or hypothesis classes the task would explore. Used to derive novelty. |

Estimates:

| Estimate | Raw scale | Normalized as |
|---|---|---|
| `likelihood` | probability, 0–1 | clamped to [0, 1] |
| `impact` | severity, 0–10 | divided by 10, clamped |
| `value` | how much the engagement cares, 0–10 | divided by 10, clamped |
| `cost` | expected worker episodes, ≥ 0 | `cost / (cost + 4)`: 0 is free, 4 episodes is 0.5, approaches 1 |

Out-of-range numbers are clamped. A missing field, a missing estimate, a
non-numeric estimate or an unknown action class is rejected.

## Scoring

```
priority = (w_l*likelihood + w_i*impact + w_v*value + w_n*novelty) / (w_c*cost + epsilon)
```

over the normalized factors. Defaults (`ScoringConfig`): `w_l` 0.35, `w_i` 0.25,
`w_v` 0.20, `w_n` 0.20, `w_c` 1.0, `epsilon` 0.25. The function is the same for
every target and engagement, so all tasks are comparable on one queue. Ties are
broken by age, then task id.

**Novelty** is derived, not estimated: the fraction of a task's regions that no
dispatched task on the same target has covered. A task that declares no regions
gets a neutral 0.5.

A task's priority changes only on a logged event: a `rescore`, a merge that
widens its footprint, or another task being dispatched over regions it shares.

## Equivalence

Two tasks are equivalent when they share a canonical key: the target, the action
class, and the objective reduced to its sorted set of meaningful word stems
(case, punctuation, word order, filler words and "go and look" verbs such as
*check*, *audit*, *investigate* are ignored).

- Equivalent to an **open** task: merged into it. No new task is created; the
  submitter's provenance is recorded on the existing task and its footprint is
  widened.
- Equivalent to a recorded **dead-end**: queued, but ranked below every task
  that is not a dead-end equivalent.

If two tasks really are distinct but collapse to the same key, set
`provenance.distinguisher` to a short label; it becomes part of the key.
