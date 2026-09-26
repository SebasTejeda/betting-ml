"""Dixon-Coles (1997): Poisson goals with a low-score dependence correction ρ and
exponential time decay ξ. The estimation lives in `poisson.GoalModel`."""

from __future__ import annotations

from betting_ml.ml.models.poisson import GoalModel, GoalTarget, dc_tau

__all__ = ["DixonColesModel", "dc_tau"]


class DixonColesModel(GoalModel):
    def __init__(self, xi: float = 0.0019, target: GoalTarget = "goals", **kwargs: object) -> None:
        super().__init__(xi=xi, dixon_coles=True, target=target, **kwargs)  # type: ignore[arg-type]
