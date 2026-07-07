import logging

from app.services.diarizer_selection import DIARIZER_SORTFORMER
from app.services.sortformer_diarizer import SortformerDiarizer
from app.services.speaker_diarizer import SpeakerDiarizer, SpeakerRegistry

logger = logging.getLogger(__name__)


def create_diarizer(mode: str, registry: SpeakerRegistry | None = None):
    if mode == DIARIZER_SORTFORMER:
        logger.info("Using enhanced Sortformer diarizer")
        return SortformerDiarizer(registry=registry)

    logger.info("Using lightweight VAD + embedding diarizer")
    return SpeakerDiarizer(registry=registry)
