"""Multi-Timeframe Bollinger Bands V2 전략.

BB V2 전략(BBW 필터 + 물타기 간격 제한)에 MTF 국면 판단을 결합한다.
BBMTFStrategy와 동일한 다중 타임프레임 국면 보강을 제공하면서
BBV2Strategy의 개선된 진입 로직을 사용한다.

상속 구조:
  BBStrategy → BBV2Strategy → BBV2MTFStrategy
  BBStrategy → BBMTFStrategy (기존, 별도)
"""

import pandas as pd

from src.utils.logger import setup_logger
from .base import MarketRegime
from .bb_strategy import BBStrategy
from .bb_v2_strategy import BBV2Strategy
from .bb_mtf_strategy import ADJACENT_TF
from .registry import register_strategy

logger = setup_logger("hantrader.strategy.bb_v2_mtf")


@register_strategy("bb_v2_mtf")
class BBV2MTFStrategy(BBV2Strategy):
    """BB V2 + MTF 전략.

    BBV2Strategy를 상속하고 detect_regime만 MTF로 보강한다.
    국면 판단 로직은 BBMTFStrategy와 동일하다.
    """

    def __init__(
        self,
        mtf_weight_upper: float = 1.0,
        mtf_weight_lower: float = 0.5,
        mtf_trend_threshold: float = 2.5,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "BB_V2_MTF_Strategy"
        self.mtf_weight_upper = mtf_weight_upper
        self.mtf_weight_lower = mtf_weight_lower
        self.mtf_trend_threshold = mtf_trend_threshold

        adj = ADJACENT_TF.get(self.timeframe)
        self.lower_tf = adj[0] if adj else None
        self.upper_tf = adj[1] if adj else None

        self._upper_regime: pd.Series | None = None
        self._lower_regime: pd.Series | None = None

        logger.info(
            f"BB V2 MTF 전략 초기화: base={self.timeframe}, "
            f"lower={self.lower_tf}, upper={self.upper_tf}, "
            f"min_bbw={self.min_bbw_for_sideways}, "
            f"min_interval={self.min_entry_interval}"
        )

    # ------------------------------------------------------------------
    # MTF 데이터 준비 (BBMTFStrategy와 동일)
    # ------------------------------------------------------------------

    def prepare_mtf_data(
        self,
        df_lower: pd.DataFrame | None = None,
        df_upper: pd.DataFrame | None = None,
    ):
        """인접 타임프레임 데이터로 국면을 사전 계산한다."""
        self._upper_regime = None
        self._lower_regime = None

        if df_upper is not None and not df_upper.empty:
            try:
                upper_ind = self.compute_indicators(df_upper)
                self._upper_regime = BBStrategy.detect_regime(self, upper_ind)
                logger.info(
                    f"상위 TF({self.upper_tf}) 국면 계산 완료: "
                    f"{len(self._upper_regime)}캔들"
                )
            except Exception as e:
                logger.warning(f"상위 TF 국면 계산 실패: {e}")

        if df_lower is not None and not df_lower.empty:
            try:
                lower_ind = self.compute_indicators(df_lower)
                self._lower_regime = BBStrategy.detect_regime(self, lower_ind)
                logger.info(
                    f"하위 TF({self.lower_tf}) 국면 계산 완료: "
                    f"{len(self._lower_regime)}캔들"
                )
            except Exception as e:
                logger.warning(f"하위 TF 국면 계산 실패: {e}")

    # ------------------------------------------------------------------
    # 국면 판단 (MTF 보강 — BBMTFStrategy와 동일 로직)
    # ------------------------------------------------------------------

    def detect_regime(self, df: pd.DataFrame) -> pd.Series:
        """다중 타임프레임 가중 투표로 국면을 판단한다."""
        base_regime = BBStrategy.detect_regime(self, df)

        if self._upper_regime is None and self._lower_regime is None:
            logger.debug("MTF 데이터 없음 → 단일 TF 국면 사용")
            return base_regime

        score_map = {
            MarketRegime.TREND_UP: 1.0,
            MarketRegime.TREND_DOWN: -1.0,
            MarketRegime.SIDEWAYS: 0.0,
        }

        total_score = base_regime.map(score_map) * 2.0

        if self._upper_regime is not None:
            upper_aligned = self._upper_regime.reindex(df.index, method="ffill")
            upper_score = (
                upper_aligned.map(score_map).fillna(0.0) * self.mtf_weight_upper
            )
            total_score = total_score + upper_score

        if self._lower_regime is not None:
            lower_aligned = self._lower_regime.reindex(df.index, method="ffill")
            lower_score = (
                lower_aligned.map(score_map).fillna(0.0) * self.mtf_weight_lower
            )
            total_score = total_score + lower_score

        final = pd.Series(MarketRegime.SIDEWAYS, index=df.index)
        final[total_score >= self.mtf_trend_threshold] = MarketRegime.TREND_UP
        final[total_score <= -self.mtf_trend_threshold] = MarketRegime.TREND_DOWN

        base_trend = (base_regime != MarketRegime.SIDEWAYS).sum()
        final_trend = (final != MarketRegime.SIDEWAYS).sum()
        filtered = base_trend - final_trend
        logger.info(
            f"MTF 국면 판단: 기준TF 추세={base_trend}캔들 → "
            f"MTF 최종 추세={final_trend}캔들 (필터링 {filtered}캔들)"
        )

        return final
