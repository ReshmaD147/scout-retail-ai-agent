"""Scout deterministic service layer.

Services hold business rules that must always produce the same answer
for the same input: budget checks, discount math, stock evaluation,
distance/radius policy, and ranking. Python runs every one of these
computations - never a language model - so prices, availability, and
rankings are always reproducible and auditable.

See each *_service.py module for one focused responsibility. Services
take and return plain Python / Pydantic values (usually the domain
models from scout.repositories.models); most have no dependency on the
database at all, which is what makes them fast and simple to unit test.
"""
