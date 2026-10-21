"""Skill helpers shared across the .claude/skills/ packages.

Each subpackage holds the mechanism (how-we-detect, how-we-filter,
how-we-query) that is policy-free and skill-agnostic. The per-skill
policy — actor-specific filter constants, narrative § structure,
subagent prompt — lives in each `.claude/skills/<skill>/` directory.

Currently:

- ``judex.skills.actor_profile`` — infrastructure shared by
  `relatorio-advogado` and `relatorio-relator`: depth-coverage
  tripwire, manifest filter helper, query-summaries helper.
"""
