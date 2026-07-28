"""Shared provenance and validity rules for persisted fit measurements."""

from __future__ import annotations

from datetime import datetime, timezone

FIT_SCHEMA_VERSION = 1
FIT_RESULT_SOFT_AGE_DAYS = 90

CURRENT = "current"
INCOMPATIBLE = "incompatible"
SUPERSEDED = "superseded"
AGED = "aged"

_HOST_FIELDS = ("device", "gpu_name", "gpu_backend", "gpu_memory_gb")


def stamp_fit_record(
    subject: dict,
    host: dict,
    *,
    measured_at: datetime | None = None,
) -> dict:
    measured = measured_at or datetime.now(timezone.utc)
    return {
        "schema_version": FIT_SCHEMA_VERSION,
        "measured_at": measured.astimezone(timezone.utc).isoformat(),
        "subject": dict(subject),
        "host": {field: host.get(field) for field in _HOST_FIELDS},
    }


def assess_fit_record(
    record: dict,
    *,
    current_subject: dict | None,
    current_host: dict,
    required_fields: tuple[str, ...] = (),
    now: datetime | None = None,
    check_host: bool = True,
) -> dict:
    if record.get("schema_version") != FIT_SCHEMA_VERSION:
        return _validity(
            INCOMPATIBLE,
            "This machine has not been measured against the current benchmark.",
        )
    if any(field not in record or record[field] is None for field in required_fields):
        return _validity(
            INCOMPATIBLE,
            "This machine has not been measured against the current benchmark.",
        )

    subject = record.get("subject")
    host = record.get("host")
    if not _complete_subject(subject) or not _complete_host(host):
        return _validity(
            INCOMPATIBLE,
            "This machine has not been measured against the current benchmark.",
        )
    measured_at = _parse_measured_at(record.get("measured_at"))
    if measured_at is None:
        return _validity(
            INCOMPATIBLE,
            "This machine has not been measured against the current benchmark.",
        )

    if current_subject is None or subject.get("model_id") != current_subject.get("model_id"):
        return _validity(
            SUPERSEDED,
            f"Measured model {subject.get('model_id')} is no longer the configured subject.",
        )
    if subject.get("endpoint_fingerprint") != current_subject.get("endpoint_fingerprint"):
        return _validity(
            SUPERSEDED,
            "Measured on a different server; re-run the benchmark for the current endpoint.",
        )
    if check_host and host != {field: current_host.get(field) for field in _HOST_FIELDS}:
        old_name = host.get("gpu_name") or host.get("device") or "unknown hardware"
        new_name = current_host.get("gpu_name") or current_host.get("device") or "unknown hardware"
        return _validity(
            SUPERSEDED,
            f"Measured on {old_name}; this machine now reports {new_name}.",
        )

    current_time = now or datetime.now(timezone.utc)
    age_days = max(0, (current_time - measured_at).days)
    if age_days > FIT_RESULT_SOFT_AGE_DAYS:
        return _validity(
            AGED,
            f"Measured {age_days} days ago.",
            age_days=age_days,
        )
    return _validity(CURRENT, "", age_days=age_days)


def host_fingerprint(environment) -> dict:
    return {
        "device": environment.device,
        "gpu_name": environment.gpu_name,
        "gpu_backend": environment.gpu_backend,
        "gpu_memory_gb": environment.gpu_memory_gb,
    }


def _validity(status: str, reason: str, *, age_days: int | None = None) -> dict:
    return {"status": status, "reason": reason, "age_days": age_days}


def _complete_subject(subject) -> bool:
    return (
        isinstance(subject, dict)
        and isinstance(subject.get("model_id"), str)
        and "endpoint_fingerprint" in subject
    )


def _complete_host(host) -> bool:
    return isinstance(host, dict) and all(field in host for field in _HOST_FIELDS)


def _parse_measured_at(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        measured = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return measured if measured.tzinfo is not None else None
