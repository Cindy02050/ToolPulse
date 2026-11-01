"""Placeholder python language pack.

Python is the default language, and its error-classification logic is not
parked in a language pack: it lives inside
``toolpulse.semantics.repo.errors`` (the shared detector
``_detect_observation_error_type`` plus the python signature/command
tables). This module intentionally defines no functions of its own; it
exists only so that the language registry (``get_language``) can resolve
``"python"`` symmetrically with ``"cpp"``/``"java"``.
"""
