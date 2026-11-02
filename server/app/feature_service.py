from __future__ import annotations

from fastapi import FastAPI

from app.main import create_app
from app.services.replay_store import ReplayStore


def create_feature_app(initialize: bool = True, replay_store: ReplayStore | None = None) -> FastAPI:
    return create_app(initialize=initialize, replay_store=replay_store, title="MarketLens 特征与状态服务", service_name="marketlens-feature")


app = create_feature_app()
