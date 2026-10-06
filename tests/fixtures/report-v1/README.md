# Frozen schema-1 compatibility evidence

These documents were produced by the unchanged report/comparator implementations at
commit `f5addc4d95f94b4c0b1dba8e7280c0f160b0881e`, before the schema-2 edit.
They use an empty local store, a small invented study plan, April/May 2024 cutoffs,
and an explicit `0.10.0` software label. They contain no market observations,
provider responses or credentials. Timestamps of fixture generation are incidental.

`comparison.json` is the original comparator-1 result, including six changed
entities. Tests require recomputation to reproduce this frozen result exactly;
they do not generate the expected comparison using the implementation under test.
The original report bytes and fingerprints are retained, so inserting new default
fields into old reports is detectable. Do not regenerate these fixtures as part
of routine schema generation.
