"""Mechanism shared by `relatorio-advogado` and `relatorio-relator`.

Both skills produce per-actor STF activity reports (lawyer or
minister-relator). They diverge in *content* — what counts as
relevant peças, what the subagent extracts, what the narrative §
structure is — but converge in *infrastructure*:

- depth-pass coverage tripwire (`tripwire`)
- manifest-stage skill-scope filter shape (`filter`)
- post-breadth query helper over summaries.jsonl (`query`)

This package holds only the mechanism. Each skill's `summarize.py`
defines its own filter constants (which doc_types are irrelevant
*for this actor*) and calls the shared helpers.

The contract on disk (so the mechanism is portable):

    internal/
    ├── manifest.jsonl       ← one record per peça, sha + doc_type + chars
    ├── summaries.jsonl      ← Stage 2b breadth-pass output, keyed by sha
    ├── _depth_plan.jsonl    ← Stage 2c planned reads
    └── verification.jsonl   ← Stage 2c actual reads, also keyed by sha

The tripwire and query helper assume these filenames; downstream
helpers (filter) only see the records, not the paths.

Public entrypoints — import directly from submodules to avoid
re-import cycles when invoking ``python -m
judex.skills.actor_profile.tripwire``::

    from judex.skills.actor_profile.tripwire import verify_depth_coverage
    from judex.skills.actor_profile.filter   import skill_filter_reason
    from judex.skills.actor_profile.query    import query_summaries
"""
