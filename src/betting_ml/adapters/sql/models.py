"""SQLAlchemy ORM models. Money columns are Numeric(12, 2) mapped to `Decimal`."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

MONEY = Numeric(12, 2, asdecimal=True)
ODDS = Numeric(8, 3, asdecimal=True)


class Base(DeclarativeBase):
    pass


class BookmakerRow(Base):
    __tablename__ = "bookmakers"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20))
    accessible: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(20))


class OddsSnapshotRow(Base):
    __tablename__ = "odds_snapshots"

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
    __table_args__ = (Index("ix_bets_status_kind", "status", "kind"),)

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bankroll_initial: Mapped[Decimal] = mapped_column(MONEY)
    currency: Mapped[str] = mapped_column(String(3))
    monthly_loss_limit: Mapped[Decimal] = mapped_column(MONEY)
    max_stake_pct: Mapped[float] = mapped_column(Numeric(6, 4, asdecimal=False))
    kelly_fraction: Mapped[float] = mapped_column(Numeric(6, 4, asdecimal=False))
    min_edge: Mapped[float] = mapped_column(Numeric(6, 4, asdecimal=False))


class SettingsHistoryRow(Base):
    __tablename__ = "settings_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    field: Mapped[str] = mapped_column(String(40))
    old_value: Mapped[str] = mapped_column(String(40))
    new_value: Mapped[str] = mapped_column(String(40))
    effective_from: Mapped[str] = mapped_column(String(7))  # YYYY-MM (Lima calendar month)


class SessionRow(Base):
    """Owner sessions (spec 003). ``token_hash`` is HMAC-SHA256(SESSION_SECRET, token)."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    password_fingerprint: Mapped[str] = mapped_column(String(64))
