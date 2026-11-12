# Additive contracts

`pid-reader-wp456-proposals-v1` is a standalone sidecar envelope, NOT Worksheet
R1, DEXPI or a standalone project schema migration. Coordinates are unrotated
MediaBox normalized top-left, matching the host's PageFrame media frame.

Required top-level keys: schema, algorithm, source_sha256, frame, review_state,
upstream_wp123_sha256, inputs, wp04, wp05, wp06, metrics, notice, result_sha256.
`result_sha256` is SHA256 over the canonical JSON of all other top-level keys.
Use `common.verify_seal`, `pipeline.build`, and immutable store validation.
A content digest detects inconsistent bytes; it does not authenticate an author.

WP04 retains original evidence members, spatial occurrences, independent
readings, document fields, conflicting line readings, same-run bubble readings
and budgeted automatic regions. Corrections require named review.

WP05 retains every detector candidate including withheld ones. A geometry
circle is explicitly a separate evidence source. Named reviewer symbol-class
proposals are another separate source; they do not alter detector gates.
Associations carry options, distances and explicit abstention states.

WP06 contains only geometry proposals: segment edges, endpoints, explicit
junctions, unresolved crossings/tees/overlaps/gaps and port contacts. Unknown
stroke types cannot be used to join lines. No flow direction, off-page joins,
process state, engineering acceptance or functional-safety credit is inferred.

Review decision actions:
- ACCEPTED_AS_READING / CORRECTED_READING: printed readings only.
- SUPPORTED_AS_DRAWING_HYPOTHESIS: drawing hypothesis only, not plant truth.
- REJECTED / UNRESOLVED: all review targets.

The authoritative executable field validation is in the modules. JSON schemas
cover envelope/annotation structure; a JSON schema success alone is not a
provenance, geometry or engineering check.
