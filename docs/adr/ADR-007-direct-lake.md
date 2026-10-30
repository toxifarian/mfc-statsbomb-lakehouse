# ADR-007 · Serve through Direct Lake + SQL endpoint

**Decision.** A Direct Lake semantic model over the gold tables (relationships, DAX measures, formatting and hidden
keys created **as code** by `nb_02_semantic_model` using semantic-link-labs), plus T-SQL analyst views on the SQL
analytics endpoint, plus direct Delta access for data scientists.

**Why.** No import refresh or duplicate copy; reports see new data as soon as gold commits (the pipeline triggers a
lightweight model refresh/reframe). Measures defined once (xG/90, PPDA, Goals − xG) → one version of the truth
for coaches and analysts.

**Trade-offs.** Direct Lake falls back to DirectQuery for some patterns / guardrail breaches; keep facts lean and
star-shaped (which we do). RLS for e.g. academy vs first-team data is defined in the model.
