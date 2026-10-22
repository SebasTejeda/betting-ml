"""SQLAlchemy ORM models. Money columns are Numeric(12, 2) mapped to `Decimal`.

The CHECK constraints (spec 003, US5) make the database reject impossible data even when
the API is bypassed. Migration 0005 adds the same constraints to existing databases (a test
compares both schemas), so a change here needs a new migration.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

MONEY = Numeric(12, 2, asdecimal=True)
ODDS = Numeric(8, 3, asdecimal=True)


class Base(DeclarativeBase):
    pass


class BookmakerRow(Base):
    __tablename__ = "bookmakers"
    __table_args__ = (
        CheckConstraint("role IN ('reference', 'exchange', 'soft')", name="ck_bookmakers_role"),
        CheckConstraint("source IN ('api', 'manual')", name="ck_bookmakers_source"),
    )

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20))
    accessible: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(20))


class OddsSnapshotRow(Base):
    __tablename__ = "odds_snapshots"
    __table_args__ = (
        CheckConstraint("source IN ('the_odds_api', 'manual')", name="ck_odds_snapshots_source"),
        CheckConstraint(
            "credits_remaining IS NULL OR credits_remaining >= 0",
            name="ck_odds_snapshots_credits_remaining",
        ),
        CheckConstraint(
            "credits_used IS NULL OR credits_used >= 0", name="ck_odds_snapshots_credits_used"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str] = mapped_column(String(20))
    credits_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credits_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    leagues: Mapped[str] = mapped_column(String(80), default="")
    quotes: Mapped[list[OddsQuoteRow]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class OddsQuoteRow(Base):
    __tablename__ = "odds_quotes"
    __table_args__ = (
        Index("ix_quotes_match_book_outcome", "match_id", "bookmaker_key", "outcome"),
        CheckConstraint("odds > 1", name="ck_odds_quotes_odds"),
        CheckConstraint("outcome IN ('H', 'D', 'A')", name="ck_odds_quotes_outcome"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("odds_snapshots.id"), index=True)
    match_id: Mapped[str] = mapped_column(String(120))
    league: Mapped[str] = mapped_column(String(10))
    kickoff_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    home_team: Mapped[str] = mapped_column(String(60), default="")
    away_team: Mapped[str] = mapped_column(String(60), default="")
    bookmaker_key: Mapped[str] = mapped_column(String(40))
    market: Mapped[str] = mapped_column(String(10), default="h2h")
    outcome: Mapped[str] = mapped_column(String(1))
    odds: Mapped[float] = mapped_column(Numeric(8, 3, asdecimal=False))
    last_update: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    snapshot: Mapped[OddsSnapshotRow] = relationship(back_populates="quotes")


class BetRow(Base):
    __tablename__ = "bets"
    __table_args__ = (
        Index("ix_bets_status_kind", "status", "kind"),
        CheckConstraint("odds > 1", name="ck_bets_odds"),
        CheckConstraint("stake > 0 AND stake = round(stake, 2)", name="ck_bets_stake"),
        CheckConstraint("kind IN ('real', 'paper')", name="ck_bets_kind"),
        CheckConstraint(
            "status IN ('pendiente', 'ganada', 'perdida', 'nula')", name="ck_bets_status"
        ),
        CheckConstraint("outcome IN ('H', 'D', 'A')", name="ck_bets_outcome"),
        CheckConstraint(
            "result_source IS NULL OR result_source IN ('manual', 'official')",
            name="ck_bets_result_source",
        ),
        # pending ⇔ no profit and no settlement date; a settled bet has both
        CheckConstraint(
            "(status = 'pendiente') = (profit IS NULL) "
            "AND (status = 'pendiente') = (settled_at IS NULL)",
            name="ck_bets_settlement",
        ),
        # lost → −stake, void → 0, won → ≥ 0, always in cents
        CheckConstraint(
            "profit IS NULL OR (profit = round(profit, 2) AND CASE status "
            "WHEN 'perdida' THEN profit = -stake WHEN 'nula' THEN profit = 0 "
            "WHEN 'ganada' THEN profit >= 0 ELSE 0 END)",
            name="ck_bets_profit",
        ),
        CheckConstraint(
            "fair_probability IS NULL OR fair_probability BETWEEN 0 AND 1",
            name="ck_bets_fair_probability",
        ),
        # EV and CLV are odds × probability − 1: from −1 up to odds − 1
        CheckConstraint("ev IS NULL OR ev BETWEEN -1 AND 1000", name="ck_bets_ev"),
        CheckConstraint("clv IS NULL OR clv BETWEEN -1 AND 1000", name="ck_bets_clv"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    match_id: Mapped[str] = mapped_column(String(120), index=True)
    league: Mapped[str] = mapped_column(String(10))
    home_team: Mapped[str] = mapped_column(String(60), default="")
    away_team: Mapped[str] = mapped_column(String(60), default="")
    kickoff_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(1))
    bookmaker: Mapped[str] = mapped_column(String(40))
    odds: Mapped[Decimal] = mapped_column(ODDS)
    stake: Mapped[Decimal] = mapped_column(MONEY)
    kind: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(12))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_experimental_signal: Mapped[bool] = mapped_column(Boolean, default=False)
    fair_probability: Mapped[float | None] = mapped_column(
        Numeric(8, 6, asdecimal=False), nullable=True
    )
    ev: Mapped[float | None] = mapped_column(Numeric(8, 6, asdecimal=False), nullable=True)
    warnings: Mapped[str] = mapped_column(Text, default="")
    clv: Mapped[float | None] = mapped_column(Numeric(8, 6, asdecimal=False), nullable=True)
    clv_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    profit: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_source: Mapped[str | None] = mapped_column(String(10), nullable=True)
    no_reference: Mapped[bool] = mapped_column(Boolean, default=False)


class SettingsRow(Base):
    __tablename__ = "settings"
    __table_args__ = (
        CheckConstraint(
            "bankroll_initial >= 0 AND bankroll_initial = round(bankroll_initial, 2)",
            name="ck_settings_bankroll_initial",
        ),
        CheckConstraint(
            "monthly_loss_limit >= 0 AND monthly_loss_limit = round(monthly_loss_limit, 2)",
            name="ck_settings_monthly_loss_limit",
        ),
        CheckConstraint("currency GLOB '[A-Z][A-Z][A-Z]'", name="ck_settings_currency"),
        CheckConstraint("max_stake_pct > 0 AND max_stake_pct <= 1", name="ck_settings_max_stake"),
        CheckConstraint(
            "kelly_fraction > 0 AND kelly_fraction <= 1", name="ck_settings_kelly_fraction"
        ),
        CheckConstraint("min_edge >= 0 AND min_edge <= 1", name="ck_settings_min_edge"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bankroll_initial: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    monthly_loss_limit: Mapped[Decimal] = mapped_column(MONEY)
    max_stake_pct: Mapped[float] = mapped_column(Numeric(6, 4, asdecimal=False))
    kelly_fraction: Mapped[float] = mapped_column(Numeric(6, 4, asdecimal=False))
    min_edge: Mapped[float] = mapped_column(Numeric(6, 4, asdecimal=False))


class SettingsHistoryRow(Base):
    __tablename__ = "settings_history"
    __table_args__ = (
        CheckConstraint(
            "effective_from GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'",
            name="ck_settings_history_effective_from",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    field: Mapped[str] = mapped_column(String(40))
    old_value: Mapped[str] = mapped_column(String(40))
    new_value: Mapped[str] = mapped_column(String(40))
    effective_from: Mapped[str] = mapped_column(String(7))  # YYYY-MM (Lima calendar month)


class SessionRow(Base):
    """Owner sessions (spec 003). ``token_hash`` is HMAC-SHA256(SESSION_SECRET, token)."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("length(token_hash) = 64", name="ck_sessions_token_hash"),
        CheckConstraint("expires_at > created_at", name="ck_sessions_expiry"),
        CheckConstraint("last_seen_at >= created_at", name="ck_sessions_last_seen"),
    )

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    password_fingerprint: Mapped[str] = mapped_column(String(64))
