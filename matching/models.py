from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class Module:
    sn: str
    aec: float
    rg: float
    bg: float
    imu: int
    group: str = "pool"
    score: float | None = None
    block3: float | None = None
    block4: float | None = None


@dataclass(frozen=True)
class Config:
    mode: str = "no-imu"
    aec_limit: float = 1
    rg_limit: float = 10
    bg_limit: float = 10
    score_limit: float = 6.8
    use_score: bool = False
    score_source: str = "block-average"
    weights: dict = field(default_factory=lambda: {"aec": 0, "rg": 0.5, "bg": 0.5, "score": 0})

    def __post_init__(self):
        if self.mode not in {"no-imu", "mixed-imu"}:
            raise ValueError("mode 必须是 no-imu 或 mixed-imu")
        if self.score_source not in {"column", "block-average"}:
            raise ValueError("score_source 必须是 column 或 block-average")
        for name in ("aec", "rg", "bg", "score"):
            value = getattr(self, name + "_limit")
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name}_limit 必须是有限正数")
        if set(self.weights) != {"aec", "rg", "bg", "score"}:
            raise ValueError("weights 必须包含 aec/rg/bg/score")
        if any(isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in self.weights.values()):
            raise ValueError("权重必须是有限非负数")
        if not sum(v for k, v in self.weights.items() if k != "score" or self.use_score):
            raise ValueError("至少一个已启用指标的权重必须大于 0")
        if not isinstance(self.use_score, bool):
            raise ValueError("use_score 必须是布尔值")
