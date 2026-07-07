"""Registry mapping knowledge source_type values to adapter classes.

Extension point: to add an external source (e.g. an HTTP/RAG platform),
implement a class with `source_name` and `async fetch_context(db) -> str`
(it may ignore `db`), store endpoint/auth details in the source's `config`
JSON column, add a new source_type value, and register it in _ADAPTERS.
"""

import logging

from app.models import KnowledgeSource
from app.services.knowledge.base import KnowledgeAdapter
from app.services.knowledge.offerings_adapter import OfferingsAdapter
from app.services.knowledge.records_adapter import RecordsAdapter

logger = logging.getLogger(__name__)

_ADAPTERS = {
    "offerings": OfferingsAdapter,
    "collection": RecordsAdapter,
    "files": RecordsAdapter,
}

USER_SOURCE_TYPES = {"collection", "files"}


def get_adapter(source: KnowledgeSource | None) -> KnowledgeAdapter | None:
    """Resolve the adapter for a source; None source = legacy offerings default."""
    if source is None:
        return OfferingsAdapter(None)
    cls = _ADAPTERS.get(source.source_type)
    if cls is None:
        logger.warning(f"[knowledge] unknown source_type '{source.source_type}' on source '{source.name}'")
        return None
    return cls(source)
