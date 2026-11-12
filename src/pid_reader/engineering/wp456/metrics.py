"""WP04 benchmark: one-to-one exact-string/location matching, no fake accuracy."""
from __future__ import annotations
from collections import defaultdict, deque
from .common import collection, evidence_rows, clean, iou, source_hash, digest


def _maximum_matching(options):
    """Deterministic augmenting-path matching; no greedy undercount or recursion."""
    left, right = {}, {}
    for start in sorted(options):
        queue, seen, parent = deque([start]), {start}, {}
        free = None
        while queue and free is None:
            p = queue.popleft()
            for g in options[p]:
                if g in parent:
                    continue
                parent[g] = p
                if g not in right:
                    free = g
                    break
                nxt = right[g]
                if nxt not in seen:
                    seen.add(nxt); queue.append(nxt)
        while free is not None:
            p = parent[free]
            old = left.get(p)
            left[p], right[free] = free, p
            free = old
    return left


def score(reference, predictions, *, source_sha256, iou_gate=.3):
    """Annotations must declare exhaustive coverage per measured class/page.

    DRAFT annotations return NOT_RUN. Classes outside declared coverage are
    excluded, never counted as negatives. Duplicate predictions count as FP.
    """
    from .common import number, page
    number(iou_gate, .01, 1.)
    source_hash(source_sha256)
    if reference.get('source_sha256') != source_sha256:
        raise ValueError('Reference belongs to a different drawing')
    if reference.get('status') not in ('APPROVED_REFERENCE', 'SYNTHETIC_REFERENCE'):
        return {'status':'NOT_RUN', 'reason':'REFERENCE_NOT_APPROVED', 'per_class':{}}
    if not reference.get('reviewer') or not reference.get('reviewed_utc'):
        raise ValueError('Missing annotation reviewer or review timestamp')
    labels = evidence_rows(reference['items']); evidence_rows(predictions)
    coverage = set()
    for c in reference['coverage']:
        page(c['page'])
        if c.get('exhaustive') is True:
            coverage.add((c['page'],c['kind']))
    if not coverage:
        return {'status':'NOT_RUN', 'reason':'NO_EXHAUSTIVE_CLASS_COVERAGE', 'per_class':{}}
    classes = sorted({kind for pg,kind in coverage})
    results, pairs = {}, {}
    for kind in classes:
        truth = [r for r in labels if r['kind']==kind and (r['page'],kind) in coverage]
        pred = [r for r in predictions if r['kind']==kind and (r['page'],kind) in coverage]
        opts = {}
        for p in pred:
            opts[p['id']] = [g['id'] for g in sorted(truth,key=lambda g:(-iou(p['bbox'],g['bbox']),g['id']))
                             if p['page']==g['page'] and clean(p['text'])==clean(g['text']) and iou(p['bbox'],g['bbox'])>=iou_gate]
        matches = _maximum_matching(opts); pairs.update(matches)
        tp, fp, fn = len(matches), len(pred)-len(matches), len(truth)-len(matches)
        # A spatial match alone is a localisation hit, never a text exact match.
        spatial = {p['id']:[g['id'] for g in truth if g['page']==p['page'] and iou(p['bbox'],g['bbox'])>=iou_gate] for p in pred}
        spatial_n = len(_maximum_matching(spatial))
        results[kind] = {'true_positive':tp,'false_positive':fp,'false_negative':fn,
                         'precision':tp/len(pred) if pred else None,
                         'recall':tp/len(truth) if truth else None,
                         'exact_match_rate_on_localised':tp/spatial_n if spatial_n else None,
                         'miss_rate':fn/len(truth) if truth else None,
                         'ground_truth_count':len(truth), 'prediction_count':len(pred)}
    return {'status':'MEASURED_SYNTHETIC' if reference['status']=='SYNTHETIC_REFERENCE' else 'MEASURED',
            'text_matching':'TYPOGRAPHY_NORMALIZED_NO_CONFUSABLE_SUBSTITUTION',
            'source_sha256':source_sha256,'reference_sha256':digest(reference), 'iou_gate':iou_gate,
            'per_class':results,'prediction_to_reference':pairs,
            'excluded_predictions':sum((p['page'],p['kind']) not in coverage for p in predictions)}


def score_associations(expected_pairs, proposed_pairs, id_mapping):
    """Use independently measured object mappings, not producer self-readback."""
    truth = {tuple(x) for x in expected_pairs}
    mapped = []
    unresolved = 0
    for a,b in proposed_pairs:
        if a not in id_mapping or b not in id_mapping:
            unresolved += 1
        else:
            mapped.append((id_mapping[a],id_mapping[b]))
    # Duplicate link proposals are false positives too.
    good = set(mapped) & truth
    tp = len(good); fp = len(mapped)-tp+unresolved; fn = len(truth)-tp
    return {'true_positive':tp,'false_positive':fp,'false_negative':fn,
            'precision':tp/(tp+fp) if tp+fp else None,
            'recall':tp/len(truth) if truth else None, 'unmatched_endpoint_proposals':unresolved}
