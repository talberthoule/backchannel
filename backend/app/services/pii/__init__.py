"""PII Shield: tokenize personal data before it is stored or sent to a model.

The package is split by trust boundary:

- ``recognizers`` finds structured identifiers with patterns and checks
  (email, phone, card, national id, IP, street address) and names from a
  roster. Pure functions, no I/O.
- ``ner`` is the optional on-device named-entity model (people, organizations,
  places) for free text. Weights download once into DATA_DIR; nothing about
  detection ever leaves the machine.
- ``vault`` stores the real values encrypted under a key derived from the
  DATA_DIR master key and hands out per-session tokens.
- ``shield`` is the only module application code should import. It owns the
  settings, ``protect_text`` (the encode path, safe for any caller) and
  ``reveal_text`` (the decode path, for the local interface only).

Nothing under ``services/agents`` or ``services/llm.py`` may import
``reveal_text``: the models only ever see what ``protect_text`` produced.
"""
