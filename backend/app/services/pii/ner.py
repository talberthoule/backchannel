"""On-device named-entity recognition for the PII Shield.

Runs ``bert-base-NER`` (CoNLL-2003: person, organization, location, misc)
exported to ONNX, with a small WordPiece tokenizer implemented here so no
tokenizer library joins the desktop bundle. Weights come from the Hugging Face
hub into ``DATA_DIR/pii-models`` on first use, the same way the local ASR
weights do, and then load offline. ``onnxruntime`` is already shipped for
diarization and local transcription.

The model is optional. When the weights cannot be fetched (no network on
first use) the shield keeps working with its pattern and roster recognizers
and reports the gap in its status; nothing falls back to a cloud call.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from pathlib import Path

import numpy as np

from app.services import model_downloads
from app.services.pii.recognizers import LOCATION, ORG, PERSON, Span

logger = logging.getLogger(__name__)

MODEL_REPO = "Xenova/bert-base-NER"
MODEL_DIR_NAME = "bert-base-NER"
_MODEL_FILES = ("onnx/model_quantized.onnx", "vocab.txt", "config.json")

# Tokens per model call; BERT's window is 512 and speech turns are short.
MAX_TOKENS = 256
MIN_SCORE = 0.55

_LABEL_TO_CATEGORY = {"PER": PERSON, "ORG": ORG, "LOC": LOCATION}

# Capitalized words the model reads as a person in speech that are not one:
# "Oh my God", "Jesus", "Lord". A miss here costs a spurious vault entry, not
# a leak, so the list stays short and obvious.
_NOT_ENTITIES = frozenset({
    "god", "lord", "jesus", "christ", "gosh", "mom", "dad", "mum", "sir", "ma'am",
    "okay", "ok", "yeah", "hello", "hi", "hey", "thanks", "thank you",
})

# The registry key the browser watches this download under.
DOWNLOAD_KEY = "pii-ner"
DOWNLOAD_LABEL = "Name recognition model"
DOWNLOAD_PURPOSE = "PII Shield"

# `_state_lock` guards the two globals below and is never held across I/O.
# `_install_lock` is held across the download and the ONNX session build, and
# is only ever acquired without blocking: detection degrades to the pattern and
# roster recognizers rather than waiting on a fetch. Holding one lock across a
# network download is what wedged the whole app in v0.6.1 (ALP-373).
_state_lock = threading.Lock()
_install_lock = threading.Lock()
_model: "NerModel | None" = None
_load_error: str | None = None


def model_dir() -> Path:
    from app.services.secrets import data_dir

    return data_dir() / "pii-models" / MODEL_DIR_NAME


def is_installed() -> bool:
    root = model_dir()
    return all((root / name).is_file() for name in _MODEL_FILES)


def load_error() -> str | None:
    return _load_error


def _remote_total() -> int:
    """Combined size of the weights, or 0 when the hub will not say.

    Only used to show a percentage, so a failure here costs the progress bar
    its denominator and nothing else.
    """
    try:
        from huggingface_hub import get_hf_file_metadata, hf_hub_url

        total = 0
        for name in _MODEL_FILES:
            meta = get_hf_file_metadata(hf_hub_url(MODEL_REPO, name))
            total += int(meta.size or 0)
        return total
    except Exception:  # noqa: BLE001 - a missing denominator is not a failure
        logger.debug("Could not read the NER model size from the hub", exc_info=True)
        return 0


def ensure_downloaded() -> Path:
    """Fetch the weights once; later calls are a no-op.

    Reports byte progress into the model-download registry through
    `hf_hub_download`'s public `tqdm_class`, so the fetch is visible in the app
    instead of looking like a stall.
    """
    root = model_dir()
    if is_installed():
        return root
    from huggingface_hub import hf_hub_download

    root.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading the on-device NER model %s (first use)", MODEL_REPO)
    total = _remote_total()
    model_downloads.begin(DOWNLOAD_KEY, total)
    done = 0
    for name in _MODEL_FILES:
        hf_hub_download(
            MODEL_REPO,
            name,
            local_dir=str(root),
            tqdm_class=model_downloads.reporter_for(DOWNLOAD_KEY, base=done, total=total),
        )
        done += (root / name).stat().st_size if (root / name).is_file() else 0
        model_downloads.advance(DOWNLOAD_KEY, done, total)
    return root


class WordPiece:
    """Cased WordPiece over a BERT vocab, tracking character offsets."""

    def __init__(self, vocab_path: Path):
        self.vocab: dict[str, int] = {}
        with open(vocab_path, encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                self.vocab[line.rstrip("\n")] = index
        self.unk = self.vocab["[UNK]"]
        self.cls = self.vocab["[CLS]"]
        self.sep = self.vocab["[SEP]"]

    _WORD = re.compile(r"\w+|[^\w\s]", re.UNICODE)

    def words(self, text: str) -> list[tuple[int, int, str]]:
        return [(m.start(), m.end(), m.group()) for m in self._WORD.finditer(text)]

    def encode_word(self, word: str) -> list[int]:
        word = unicodedata.normalize("NFC", word)
        if len(word) > 60:
            return [self.unk]
        ids: list[int] = []
        start = 0
        while start < len(word):
            end = len(word)
            piece = None
            while start < end:
                candidate = word[start:end]
                if start > 0:
                    candidate = "##" + candidate
                if candidate in self.vocab:
                    piece = self.vocab[candidate]
                    break
                end -= 1
            if piece is None:
                return [self.unk]
            ids.append(piece)
            start = end
        return ids


class NerModel:
    def __init__(self, root: Path):
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(
            str(root / "onnx" / "model_quantized.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self.input_names = {i.name for i in self.session.get_inputs()}
        self.tokenizer = WordPiece(root / "vocab.txt")
        with open(root / "config.json", encoding="utf-8") as handle:
            config = json.load(handle)
        id2label = config.get("id2label") or {}
        self.labels = [id2label[str(i)] for i in range(len(id2label))]

    def _run(self, ids: list[int]) -> np.ndarray:
        input_ids = np.array([ids], dtype=np.int64)
        feeds = {"input_ids": input_ids}
        if "attention_mask" in self.input_names:
            feeds["attention_mask"] = np.ones_like(input_ids)
        if "token_type_ids" in self.input_names:
            feeds["token_type_ids"] = np.zeros_like(input_ids)
        logits = self.session.run(None, feeds)[0][0]
        shifted = logits - logits.max(axis=-1, keepdims=True)
        probs = np.exp(shifted)
        return probs / probs.sum(axis=-1, keepdims=True)

    def entities(self, text: str) -> list[Span]:
        words = self.tokenizer.words(text)
        if not words:
            return []
        spans: list[Span] = []
        # Chunk by words so no window exceeds MAX_TOKENS pieces.
        chunk: list[tuple[int, int, list[int]]] = []
        budget = 0
        for start, end, word in words:
            pieces = self.tokenizer.encode_word(word)
            if chunk and budget + len(pieces) > MAX_TOKENS - 2:
                spans.extend(self._entities_for(text, chunk))
                chunk, budget = [], 0
            chunk.append((start, end, pieces))
            budget += len(pieces)
        if chunk:
            spans.extend(self._entities_for(text, chunk))
        return spans

    def _entities_for(self, text: str, chunk: list[tuple[int, int, list[int]]]) -> list[Span]:
        ids = [self.tokenizer.cls]
        first_piece_index: list[int] = []
        for _, _, pieces in chunk:
            first_piece_index.append(len(ids))
            ids.extend(pieces)
        ids.append(self.tokenizer.sep)
        probs = self._run(ids)

        spans: list[Span] = []
        current: dict | None = None

        def close() -> None:
            nonlocal current
            if current is None:
                return
            score = float(np.mean(current["scores"]))
            category = _LABEL_TO_CATEGORY.get(current["type"])
            start, end = current["start"], current["end"]
            entity = text[start:end]
            if category and score >= MIN_SCORE and entity.strip().lower() not in _NOT_ENTITIES:
                spans.append(Span(start, end, category, entity, score, "ner"))
            current = None

        for (start, end, _), index in zip(chunk, first_piece_index):
            row = probs[index]
            label_id = int(row.argmax())
            label = self.labels[label_id] if label_id < len(self.labels) else "O"
            score = float(row[label_id])
            if label == "O" or "-" not in label:
                close()
                continue
            prefix, entity_type = label.split("-", 1)
            # A continuation extends the open entity; anything else (a new
            # B- tag, or an I- of another type) starts a fresh one.
            if current is not None and prefix == "I" and entity_type == current["type"]:
                current["end"] = end
                current["scores"].append(score)
            else:
                close()
                current = {"type": entity_type, "start": start, "end": end, "scores": [score]}
        close()
        return spans


def _current() -> "NerModel | None":
    with _state_lock:
        return _model


def _record(model: "NerModel | None", error: str | None) -> None:
    global _model, _load_error
    with _state_lock:
        _model = model
        _load_error = error


def get_model(download: bool = False) -> "NerModel | None":
    """The loaded model, or None when it is not ready.

    Never blocks on another thread's fetch and, by default, never starts one.
    A caller on the ingest path wants an answer now: if the weights are absent,
    still arriving, or already known to be broken, it gets None and the shield
    carries on with its pattern and roster recognizers.

    `download=True` is for the explicit install and the background warm-up
    only, and even then only one fetch runs at a time.
    """
    ready = _current()
    if ready is not None:
        return ready
    if _load_error is not None and not download:
        return None
    if not download and not is_installed():
        return None
    # Whoever holds this is already doing the work; do not queue behind them.
    if not _install_lock.acquire(blocking=False):
        return None
    try:
        ready = _current()
        if ready is not None:
            return ready
        try:
            root = ensure_downloaded() if download else model_dir()
            if not is_installed():
                _record(None, "The on-device NER model is not installed.")
                return None
            model = NerModel(root)
            _record(model, None)
            logger.info("On-device NER model loaded from %s", root)
            return model
        except Exception as exc:  # noqa: BLE001 - detection must degrade, never crash ingest
            message = f"{type(exc).__name__}: {exc}"
            _record(None, message)
            logger.warning("On-device NER model unavailable: %s", message)
            return None
    finally:
        _install_lock.release()


def install() -> "NerModel | None":
    """Fetch and load the weights now, reporting into the download registry.

    Returns the model, or None with `load_error` set. Safe to call from a
    worker thread; a second concurrent call is a no-op that returns whatever
    is loaded already.
    """
    if not model_downloads.claim(DOWNLOAD_KEY, DOWNLOAD_LABEL, DOWNLOAD_PURPOSE):
        return _current()
    _record(None, None)
    try:
        with model_downloads.download(DOWNLOAD_KEY, DOWNLOAD_LABEL, DOWNLOAD_PURPOSE):
            model = get_model(download=True)
            if model is None:
                raise RuntimeError(_load_error or "The on-device NER model could not be installed.")
            return model
    except Exception:  # noqa: BLE001 - already recorded in the registry and in _load_error
        return None


def find_entities(text: str, categories: set[str], download: bool = False) -> list[Span]:
    model = get_model(download=download)
    if model is None:
        return []
    try:
        return [s for s in model.entities(text) if s.category in categories]
    except Exception:  # noqa: BLE001
        logger.warning("NER inference failed; continuing with pattern recognizers", exc_info=True)
        return []


def reset_for_tests() -> None:
    _record(None, None)
    model_downloads.forget(DOWNLOAD_KEY)
