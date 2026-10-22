"""Spec-002 bankroll settings and responsible-gambling limits (US6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from betting_ml.api.dependencies import JournalApi, get_journal, require_app_key
from betting_ml.api.mappers.journal import bankroll_settings, settings_out
from betting_ml.api.schemas_002 import SettingsIO, SettingsOut

router = APIRouter(prefix="/api/v1", tags=["spec-002"])


@router.get("/settings", response_model=SettingsOut)
def get_settings(journal: JournalApi = Depends(get_journal)) -> SettingsOut:
    return settings_out(journal.bets.get_settings(), journal.bets.current_limit())


@router.put("/settings", response_model=SettingsOut, dependencies=[Depends(require_app_key)])
def put_settings(body: SettingsIO, journal: JournalApi = Depends(get_journal)) -> SettingsOut:
    saved = journal.bets.update_settings(bankroll_settings(body))
    return settings_out(saved, journal.bets.current_limit())
