from __future__ import annotations

from copy import deepcopy
from threading import Lock
from typing import Any

from app.core.serialization import json_compatible
from app.services.cache import RedisJsonCache
from market_core.models.feature_contracts import content_version


class FeatureSnapshotCache:
    def __init__(self, metadata: dict[str, Any], state: dict[str, Any], cache: RedisJsonCache | None):
        self.cache = cache
        self._value = json_compatible({name: state[name] for name in ("date", "features", "contributions", "model_version")})
        self._identity = json_compatible({
            "schema": "latest-features-v1",
            "view": "current-market",
            "scope": "market:all-assets:v1",
            "feature_version": metadata["feature_contract"]["feature_version"],
            "input_version": metadata["input_version"],
            "data_version": metadata["data_version"],
            "model_parameters": metadata["model_parameters"],
            "model_identity": state.get("regime_identity", "local-cluster-v1"),
            "model_version": state["model_version"],
            "date": state["date"],
            "value_version": content_version("value-", self._value),
        })
        self.key = (cache.namespace if cache else "disabled") + ":" + content_version("snapshot-", self._identity)
        self.stats = {"validated_hits": 0, "fallbacks": 0, "rejected": 0}
        self.lock = Lock()

    def read(self) -> dict[str, Any]:
        if self.cache is None:
            return deepcopy(self._value)
        envelope = self.cache.get(self.key)
        valid = False
        if isinstance(envelope, dict) and envelope.get("identity") == self._identity:
            try:
                valid = content_version("value-", envelope["value"]) == self._identity["value_version"]
            except (KeyError, TypeError, ValueError, OverflowError):
                pass
        with self.lock:
            if valid:
                self.stats["validated_hits"] += 1
            else:
                self.stats["fallbacks"] += 1
                if envelope is not None:
                    self.stats["rejected"] += 1
        if valid:
            return deepcopy(envelope["value"])
        self.cache.set(self.key, {"identity": self._identity, "value": self._value})
        return deepcopy(self._value)

    def status(self) -> dict[str, Any]:
        with self.lock:
            stats = dict(self.stats)
        return {
            "enabled": self.cache is not None,
            "view": self._identity["view"],
            "scope": self._identity["scope"],
            "date": self._identity["date"],
            "feature_version": self._identity["feature_version"],
            **stats,
            "shared": ({**self.cache.stats, "ttl_seconds": self.cache.ttl_seconds, "circuit": self.cache.breaker.snapshot()} if self.cache else None),
        }
