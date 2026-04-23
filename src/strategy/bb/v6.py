"""Bollinger Bands V6 전략.

BB V2를 상속하여 국면 판단에 **밴드 기울기(slope) 정렬**과 **Squeeze 감지**를 추가한다.

문제:
  기존 detect_regime()의 direction 합의는 EMA/SMA/MACD/DI에 의존 — 모두 후행 지표.
  하락 중 되돌림에 쉽게 오염되어 direction이 임계값에 못 미치는 경우 다수.

해결:
  A. 밴드 기울기 정렬을 direction에 반영
     - 상단/중단/하단 밴드의 N캔들 변화율 부호(+1/-1/0) 합산
     - 세 밴드 모두 같은 방향이면 강한 추세, 혼조면 약한 방향
     - 후행성을 추가하지 않고 "밴드 자체의 움직임"을 direction에 직접 반영

  B. Squeeze 감지 후 신규 진입 차단
     - BBW가 rolling 평균 대비 squeeze_bbw_ratio 미만이면 squeeze 상태
     - squeeze 상태에서는 강제로 SIDEWAYS로 취급 (추세 오판 방지)
     - V2의 min_bbw_for_sideways(절대값 필터)와 병행 — 절대 좁음 + 상대 좁음 모두 체크

시그널/진입 로직은 BB V2 그대로. compute_indicators에 slope/squeeze 컬럼 추가, detect_regime 오버라이드.
"""

import pandas as pd

from src.utils.logger import setup_logger
from ..base import MarketRegime
from ..registry import register_strategy
from .v2 import BBV2Strategy

logger = setup_logger("hantrader.strategy.bb_v6")


@register_strategy("bb_v6")
class BBV6Strategy(BBV2Strategy):
    """BB V6 전략: 밴드 기울기 + Squeeze.

    BBV2Strategy를 상속하여 compute_indicators, detect_regime만 오버라이드한다.
    """

    def __init__(
        self,
        slope_lookback: int = 3,
        slope_threshold: float = 0.001,
        slope_weight: float = 0.5,
        squeeze_bbw_ratio: float = 0.7,
        block_entry_on_squeeze: bool = True,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "BB_V6_Strategy"
        self.slope_lookback = slope_lookback
        self.slope_threshold = slope_threshold
        self.slope_weight = slope_weight
        self.squeeze_bbw_ratio = squeeze_bbw_ratio
        self.block_entry_on_squeeze = block_entry_on_squeeze

        logger.info(
            f"BB V6 전략 초기화: slope_lookback={self.slope_lookback}, "
            f"slope_threshold={self.slope_threshold}, slope_weight={self.slope_weight}, "
            f"squeeze_ratio={self.squeeze_bbw_ratio}, "
            f"block_squeeze={self.block_entry_on_squeeze}"
        )

    # ------------------------------------------------------------------
    # 지표 계산: 밴드 기울기 + squeeze 컬럼 추가
    # ------------------------------------------------------------------

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """기존 지표 + 상/중/하단 N캔들 변화율 + squeeze 플래그."""
        out = super().compute_indicators(df)

        # 각 밴드의 N캔들 변화율 (slope 근사) — 가격 비율로 정규화
        for band in ("bb_upper", "bb_middle", "bb_lower"):
            prev = out[band].shift(self.slope_lookback)
            out[f"{band}_slope"] = (out[band] - prev) / prev

        # Squeeze: BBW가 최근 regime_window 평균의 ratio 미만
        bbw_ma = out["bb_width"].rolling(self.regime_window).mean()
        out["bb_squeeze"] = out["bb_width"] < bbw_ma * self.squeeze_bbw_ratio

        return out.dropna()

    # ------------------------------------------------------------------
    # 국면 판단: direction에 밴드 기울기 정렬 추가 + squeeze → sideways
    # ------------------------------------------------------------------

    def detect_regime(self, df: pd.DataFrame) -> pd.Series:
        """slope 정렬 + squeeze를 반영한 국면 판단.

        BBStrategy.detect_regime와 동일한 구조이되:
          - direction에 (upper_slope_sign + middle_slope_sign + lower_slope_sign) * slope_weight 추가
          - squeeze 상태면 최종 regime을 SIDEWAYS로 덮어씀 (block_entry_on_squeeze=True일 때)
        """
        regime = pd.Series(MarketRegime.SIDEWAYS, index=df.index)

        # === 1단계: 추세 강도 (parent와 동일) ===
        strength = pd.Series(0.0, index=df.index)

        adx = df["adx"]
        strength += (adx >= 25).astype(float) * 2.0
        strength += ((adx >= 20) & (adx < 25)).astype(float) * 1.0

        bb_width = df["bb_width"]
        width_ma = bb_width.rolling(self.regime_window).mean()
        width_change = (bb_width / width_ma) - 1.0
        strength += (width_change > self.regime_threshold).astype(float) * 1.0

        # === 2단계: 추세 방향 (parent + slope 보강) ===
        direction = pd.Series(0.0, index=df.index)

        # EMA 배열 (12 vs 26)
        direction += (df["ema_12"] > df["ema_26"]).astype(float) * 1.5
        direction -= (df["ema_12"] < df["ema_26"]).astype(float) * 1.5

        # 가격 vs SMA 20
        direction += (df["close"] > df["sma_20"]).astype(float) * 1.0
        direction -= (df["close"] < df["sma_20"]).astype(float) * 1.0

        # MACD diff
        direction += (df["macd_diff"] > 0).astype(float) * 1.0
        direction -= (df["macd_diff"] < 0).astype(float) * 1.0

        # DI+ vs DI-
        direction += (df["di_plus"] > df["di_minus"]).astype(float) * 1.0
        direction -= (df["di_plus"] < df["di_minus"]).astype(float) * 1.0

        # V6: 밴드 기울기 부호 정렬 (세 밴드 모두 같은 방향일수록 강한 신호)
        slope_sum = (
            self._slope_sign(df["bb_upper_slope"])
            + self._slope_sign(df["bb_middle_slope"])
            + self._slope_sign(df["bb_lower_slope"])
        )  # 범위: -3 ~ +3
        direction += slope_sum * self.slope_weight  # 기본 0.5 → 전체 정렬 시 ±1.5

        # === 국면 결정 ===
        is_trend = strength >= 2.0
        regime[is_trend & (direction >= 2.0)] = MarketRegime.TREND_UP
        regime[is_trend & (direction <= -2.0)] = MarketRegime.TREND_DOWN

        # V6-B: squeeze 상태는 sideways로 강제 (밴드 수렴 구간 추세 진입 방지)
        if self.block_entry_on_squeeze and "bb_squeeze" in df.columns:
            squeeze_mask = df["bb_squeeze"].astype(bool)
            squeeze_overridden = (regime[squeeze_mask] != MarketRegime.SIDEWAYS).sum()
            regime[squeeze_mask] = MarketRegime.SIDEWAYS
            if squeeze_overridden > 0:
                logger.info(f"Squeeze 덮어쓰기: 추세 → sideways {squeeze_overridden}캔들")

        # slope 기여 통계
        all_up = (slope_sum == 3).sum()
        all_down = (slope_sum == -3).sum()
        logger.info(
            f"Slope 정렬 통계: 세 밴드 모두↑={all_up}캔들, 모두↓={all_down}캔들 "
            f"(총 {len(df)}캔들 중)"
        )

        return regime

    # ------------------------------------------------------------------
    # 헬퍼
    # ------------------------------------------------------------------

    def _slope_sign(self, slope_series: pd.Series) -> pd.Series:
        """기울기 시리즈를 +1/-1/0 부호로 변환 (임계값 이상일 때만 유의미)."""
        sign = pd.Series(0.0, index=slope_series.index)
        sign[slope_series > self.slope_threshold] = 1.0
        sign[slope_series < -self.slope_threshold] = -1.0
        return sign
