from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Verdict(StrEnum):
    CLEAN = "clean"
    BLOCKED = "blocked"
    UNCERTAIN = "uncertain"


class AlertKind(StrEnum):
    BLOCKED = "blocked"
    RECOVERED = "recovered"


@dataclass(frozen=True)
class Node:
    uuid: str
    name: str
    address: str
    port: int = 443
    server_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class AlertDecision:
    kind: AlertKind
    status: Verdict


def normalize_verdict(value: str | Verdict) -> Verdict:
    if isinstance(value, Verdict):
        return value
    return Verdict(value)


def result_verdict(result: dict[str, Any]) -> Verdict:
    return normalize_verdict(str(result.get("verdict", Verdict.UNCERTAIN)))
