# Change 6 - R4 C12-v4 indexed dashed-fragment optimisation: evaluated, NOT integrated

Decision: **SKIPPED - not applicable to the live program.** Nothing was ported and no setting exists for it.

## What was compared

* **R4 C12-v4** (`prototypes/pidlab4/dashes_r4.py::reconstruct_r4`, `_FragGrid`, 180 lines, taken unchanged from the R4 archive inside the R5 research
  return). Its own header says what it is: it removes the quadratic "residual-fragment absorption" scan of *R3 C12-v3* **without changing that stage's
  decisions**, and it calls the research base routine `pidlab.dashes.reconstruct` (R2) first. It is an optimisation of a *dash-run reconstruction stage*:
  group collinear dash fragments into runs, bridge gaps between runs, absorb short residual fragments, snap run ends to signal ports.
* **The live program** (`src/pid_reader`, branch base `main` 4cefc35 = 0.18.1-dev0). A search of every module for the corresponding stage
  (`fragment`, `absorb`, `dash_array`, `dashed`, `dash_pattern`, `reconstruct`) finds none. Dashes are handled by:
  * `engineering/topology.py` / `vector_network.py` - a stroke's *style* (`DASHED_OR_DOTTED`) is taken from the PDF's own stroke dash attribute,
    per native stroke; there is no re-assembly of separate short strokes into a run;
  * `engineering/signal_links.py` - a dashed native stroke that ends at a detected outline is a candidate (one pass over strokes, no pairwise scan);
  * `engineering/signal_paths.py` - traversal over reviewed contact candidates, bounded by `MAX_EDGES = 7000` and `MAX_HOPS`;
  * `engineering/engineering_graph.py::port_compatible` and the path "all strokes dashed" test - a per-path predicate, not a fragment search.

## Finding

The hotspot C12-v4 removes (every run x every short fragment, repeated until a fixpoint) **does not exist in the live program**, so there is no
incumbent behaviour to reproduce exactly and no cost to remove. Integrating the R4 routine would not be a speed patch; it would add a new
algorithm (run reconstruction, gap bridging, extended port snapping, a glyph guard) that changes which strokes count as one dashed line and therefore
changes engineering connectivity proposals. The R5 instructions forbid exactly that ("do not change port typing or signal assertions as part of a speed
patch"), and the equivalence evidence supplied (160/160 replays) compares C12-v4 with R3, not with this program.

Also relevant: on the live dense sheet S023 the typed graph has zero edges and the signal stage found no dashed-signal ports, which matches R4's own
observation that S023 has zero signal ports; there is nothing for a dash optimisation to speed up on that sheet.

## Equivalence / timing / resource gates

| Gate | Result |
|---|---|
| exact decision and canonical-output equivalence against the live incumbent | NOT_APPLICABLE (no incumbent stage) |
| cancellation and resource caps | NOT_APPLICABLE (the live passes already honour the existing stage cancel token and caps; unchanged) |
| cold + 7 warm Windows process timing | NOT_RUN (nothing to time) |

## If this is ever wanted

It needs its own work package: first decide (with gold data) whether re-assembling dash runs is *wanted* behaviour; then port R3's reconstruction as a new,
flagged stage with its own tests and fresh test data; only then is C12-v4 a candidate optimisation of it. It must not be tuned on the R5 TEST split.
