from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wotapp.database import Base


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        Index("ix_vehicles_nation", "nation"),
        Index("ix_vehicles_vehicle_type", "vehicle_type"),
        Index("ix_vehicles_tier", "tier"),
        Index("ix_vehicles_mastery_95", "mastery_95"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    nation: Mapped[str | None] = mapped_column(String)
    vehicle_type: Mapped[str | None] = mapped_column(String)
    role: Mapped[str | None] = mapped_column(String)
    tier: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String)
    en_name: Mapped[str | None] = mapped_column(String)
    short_name: Mapped[str | None] = mapped_column(String)
    en_short_name: Mapped[str | None] = mapped_column(String)
    tech_name: Mapped[str | None] = mapped_column(String)
    is_premium: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_collector: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    icon_url: Mapped[str | None] = mapped_column(String)
    rank: Mapped[int | None] = mapped_column(Integer)
    rank_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mastery_65: Mapped[int | None] = mapped_column(Integer)
    mastery_85: Mapped[int | None] = mapped_column(Integer)
    mastery_95: Mapped[int | None] = mapped_column(Integer)
    mastery_updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    snapshots: Mapped[list["MasterySnapshot"]] = relationship(back_populates="vehicle")


class MasterySnapshot(Base):
    __tablename__ = "mastery_snapshots"
    __table_args__ = (
        UniqueConstraint("vehicle_id", "captured_at", name="uq_snapshot_vehicle_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    mastery_65: Mapped[int | None] = mapped_column(Integer)
    mastery_85: Mapped[int | None] = mapped_column(Integer)
    mastery_95: Mapped[int | None] = mapped_column(Integer)
    ace: Mapped[int | None] = mapped_column(Integer)
    gathered_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    vehicle: Mapped[Vehicle] = relationship(back_populates="snapshots")
