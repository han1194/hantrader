"""Multi-Timeframe Bollinger Bands 전략.

기존 BB전략의 국면 판단을 상위/하위 타임프레임으로 보강한다.
기준 타임프레임의 국면 전환 시 인접 타임프레임 국면을 참고하여
허위 국면 전환(whipsaw)을 필터링한다.

예시: 기준 1h → 하위 30m + 상위 2h 국면 참고
"""

import pandas as pd

from src.utils.logger import setup_logger
from .base import MarketRegime
from .bb_strategy import BBStrategy
from .registry import register_strategy

logger = setup_logger("hantrader.strategy.bb_mtf")

# 인접 타임프레임 매핑: base → (lower, upper)
ADJACENT_TF = {
    "5m": ("3m", "15m"),
    "15m": ("5m", "30m"),
    "30m": ("15m", "1h"),
    "1h": ("30m", "2h"),
    "2h": ("1h", "4h"),
    "4h": ("2h", "8h"),
    "8h": ("4h", "12h"),
    "12h": ("8h", "1d"),
    "1d": ("12h", "1w"),
}


@register_strategy("bb_mtf")
class BBMTFStrategy(BBStrategy):
    """다중 타임프레임 BB 전략.

    기존 BBStrategy를 상속하고 detect_regime만 MTF로 보강한다.

    국면 판단 로직:
        기준 TF 국면 점수 (±2.0)
      + 상위 TF 국면 점수 (±mtf_weight_upper, 기본 1.0)
      + 하위 TF 국면 점수 (±mtf_weight_lower, 기본 0.5)
      = 총점 → ±mtf_trend_threshold 이상이면 추세, 미만이면 횡보

    기본 임계값 2.5 → 기준 TF가 추세(±2)여도 인접 TF 최소 1개가
    확인해야 추세로 판정. 이를 통해 단일 TF에서 발생하는 허위 국면
    전환을 억제한다.

    사용법:
        strategy = BBMTFStrategy(timeframe="1h", ...)
        strategy.prepare_mtf_data(df_lower=df_30m, df_upper=df_2h)
        signals = strategy.generate_signals(df_1h)
    """

    def __init__(
        self,
        mtf_weight_upper: float = 1.0,
        mtf_weight_lower: float = 0.5,
        mtf_trend_threshold: float = 2.5,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "BB_MTF_Strategy"
        self.mtf_weight_upper = mtf_weight_upper
        self.mtf_weight_lower = mtf_weight_lower
        self.mtf_trend_threshold = mtf_trend_threshold

        # 인접 타임프레임 결정
        adj = ADJACENT_TF.get(self.timeframe)
        self.lower_tf = adj[0] if adj else None
        self.upper_tf = adj[1] if adj else None

        # MTF 국면 데이터 (prepare_mtf_data로 설정)
        self._upper_regime: pd.Series | None = None
        self._lower_regime: pd.Series | None = None

        logger.info(
            f"MTF 전략 초기화: base={self.timeframe}, "
            f"lower={self.lower_tf}, upper={self.upper_tf}, "
            f"weight_upper={self.mtf_weight_upper}, weight_lower={self.mtf_weight_lower}, "
            f"threshold={self.mtf_trend_threshold}"
        )

    # ------------------------------------------------------------------
    # MTF 데이터 준비
    # ------------------------------------------------------------------

    def prepare_mtf_data(
        self,
        df_lower: pd.DataFrame | None = None,
        df_upper: pd.DataFrame | None = None,
    ):
        """인접 타임프레임 데이터로 국면을 사전 계산한다.

        generate_signals 호출 전에 호출해야 한다.
        각 TF 데이터에 대해 지표를 계산하고 국면을 판단한다.

        Args:
            df_lower: 하위 타임프레임 OHLCV (예: 30m)
            df_upper: 상위 타임프레임 OHLCV (예: 2h)
        """
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
    # 국면 판단 (MTF 보강)
    # ------------------------------------------------------------------

    def detect_regime(self, df: pd.DataFrame) -> pd.Series:
        """다중 타임프레임 가중 투표로 국면을 판단한다.

        기준 TF 국면(±2점) + 상위 TF(±weight_upper) + 하위 TF(±weight_lower)
        총점이 ±mtf_trend_threshold 이상이면 추세, 미만이면 횡보.

        MTF 데이터가 없으면 기존 단일 TF 로직으로 폴백한다.
        """
        base_regime = BBStrategy.detect_regime(self, df)

        if self._upper_regime is None and self._lower_regime is None:
            logger.debug("MTF 데이터 없음 → 단일 TF 국면 사용")
            return base_regime

        # 국면 → 점수 변환 맵
        score_map = {
            MarketRegime.TREND_UP: 1.0,
            MarketRegime.TREND_DOWN: -1.0,
            MarketRegime.SIDEWAYS: 0.0,
        }

        # 기준 TF 점수 (가중치 2.0)
        total_score = base_regime.map(score_map) * 2.0

        # 상위 TF 점수
        if self._upper_regime is not None:
            upper_aligned = self._upper_regime.reindex(df.index, method="ffill")
            upper_score = (
                upper_aligned.map(score_map).fillna(0.0) * self.mtf_weight_upper
            )
            total_score = total_score + upper_score

            # 디버그: 기준TF=추세인데 상위TF=횡보인 캔들 수
            mismatch = (base_regime != MarketRegime.SIDEWAYS) & (
                upper_aligned == MarketRegime.SIDEWAYS
            )
            if mismatch.any():
                logger.debug(
                    f"상위TF 불일치: {mismatch.sum()}캔들 "
                    f"(기준TF=추세, 상위TF=횡보 → 추세 필터링)"
                )

        # 하위 TF 점수
        if self._lower_regime is not None:
            lower_aligned = self._lower_regime.reindex(df.index, method="ffill")
            lower_score = (
                lower_aligned.map(score_map).fillna(0.0) * self.mtf_weight_lower
            )
            total_score = total_score + lower_score

            mismatch = (base_regime != MarketRegime.SIDEWAYS) & (
                lower_aligned == MarketRegime.SIDEWAYS
            )
            if mismatch.any():
                logger.debug(
                    f"하위TF 불일치: {mismatch.sum()}캔들 "
                    f"(기준TF=추세, 하위TF=횡보 → 추세 필터링)"
                )

        # 최종 국면 결정
        final = pd.Series(MarketRegime.SIDEWAYS, index=df.index)
        final[total_score >= self.mtf_trend_threshold] = MarketRegime.TREND_UP
        final[total_score <= -self.mtf_trend_threshold] = MarketRegime.TREND_DOWN

        # 요약 로깅
        base_trend = (base_regime != MarketRegime.SIDEWAYS).sum()
        final_trend = (final != MarketRegime.SIDEWAYS).sum()
        filtered = base_trend - final_trend
        logger.info(
            f"MTF 국면 판단: 기준TF 추세={base_trend}캔들 → "
            f"MTF 최종 추세={final_trend}캔들 (필터링 {filtered}캔들)"
        )

        return final
