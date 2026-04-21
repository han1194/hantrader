"""Bollinger Bands V3 전략.

BB V2를 상속하여 횡보 신규진입에 2가지 필터를 추가한다.

A. BB% 극단 돌파 필터
   - bb_pct > bbp_breakout_upper (기본 1.05) 또는 bb_pct < bbp_breakout_lower (기본 -0.05)
     이면 횡보 신규진입 차단.
   - 극단 돌파는 "반전" 신호가 아니라 "추세 시작" 신호일 가능성이 높음 → 역추세 손실 방지.

B. ADX OR 차단 (adx_rising AND 조건 완화)
   - 부모 V2/BB: trend_approaching = (adx >= adx_entry_block) AND adx_rising
   - V3: trend_approaching = (adx >= adx_entry_block)  (rising 조건 제거)
   - ADX가 이미 기준 이상이면 상승/하락 여부 무관하게 신규진입 억제.

기존 포지션의 청산/손절/물타기는 부모 로직 그대로 사용 (변경 없음).
"""

import pandas as pd

from src.utils.logger import setup_logger
from .base import Signal
from .bb_v2_strategy import BBV2Strategy
from .registry import register_strategy

logger = setup_logger("hantrader.strategy.bb_v3")


@register_strategy("bb_v3")
class BBV3Strategy(BBV2Strategy):
    """BB V3 전략: BB% 돌파 필터 + ADX OR 차단 (신규진입 한정).

    BBV2Strategy를 상속하여 _sideways_signals_v2만 오버라이드한다.
    """

    def __init__(
        self,
        bbp_breakout_upper: float = 1.05,
        bbp_breakout_lower: float = -0.05,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "BB_V3_Strategy"
        self.bbp_breakout_upper = bbp_breakout_upper
        self.bbp_breakout_lower = bbp_breakout_lower

        logger.info(
            f"BB V3 전략 초기화: bbp_breakout=[{self.bbp_breakout_lower}, "
            f"{self.bbp_breakout_upper}], adx_block={self.adx_entry_block} (OR)"
        )

    # ------------------------------------------------------------------
    # 횡보장 반전매매 — 신규진입에 A + B 필터 추가
    # ------------------------------------------------------------------

    def _sideways_signals_v2(
        self,
        ts: pd.Timestamp,
        price: float,
        bbp: float,
        bb_width: float,
        leverage: int,
        long_step: int,
        short_step: int,
        entry_price: float,
        adx: float = 0.0,
        adx_rising: bool = False,
    ) -> list[Signal]:
        """V3: BBW + BB% 돌파 + ADX OR 차단 (신규진입만).

        기존 포지션이 있으면 부모 V2 로직 그대로 (물타기/청산 변경 없음).
        """
        has_position = long_step > 0 or short_step > 0

        if has_position:
            return super()._sideways_signals_v2(
                ts, price, bbp, bb_width, leverage, long_step, short_step,
                entry_price, adx=adx, adx_rising=adx_rising,
            )

        # === 신규 진입 필터들 ===

        # V2: BBW 최소 기준
        if bb_width < self.min_bbw_for_sideways:
            logger.debug(
                f"[V3] 신규진입 차단: BBW={bb_width:.4f} < "
                f"최소기준={self.min_bbw_for_sideways}"
            )
            return []

        # V3-A: BB% 극단 돌파 필터 (밴드 돌파는 추세 시작 신호)
        if bbp > self.bbp_breakout_upper or bbp < self.bbp_breakout_lower:
            logger.debug(
                f"[V3] 신규진입 차단: BB% 돌파 (bbp={bbp:.3f}, "
                f"범위=[{self.bbp_breakout_lower}, {self.bbp_breakout_upper}])"
            )
            return []

        # V3-B: ADX OR 차단 (절대값만, rising 무관)
        if adx >= self.adx_entry_block:
            logger.debug(
                f"[V3] 신규진입 차단: ADX={adx:.1f} >= "
                f"기준={self.adx_entry_block} (OR조건)"
            )
            return []

        # 필터 통과 → 부모 V2/BB 로직 사용 (신규 진입)
        return super()._sideways_signals_v2(
            ts, price, bbp, bb_width, leverage, long_step, short_step,
            entry_price, adx=adx, adx_rising=adx_rising,
        )
