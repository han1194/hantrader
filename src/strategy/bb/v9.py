"""Bollinger Bands V9 전략.

BB V4를 상속하여 국면 판단을 **차트 구조 기반 다중 규칙 투표**로 재설계한다.
V4로부터 `cooldown_candles` (trend→sideways 전환 직후 횡보 신규 진입 차단)를
상속받는다.

배경:
  V6/V7/V8이 사용하는 평균·밴드 폭 지표는 급락/급등 구간에서 한 박자 늦거나,
  단일 캔들 스파이크를 추세로 오판하는 경향이 있다.
  사용자가 SOL/USDT 2026-04-01~15 1h 차트에서 짚은 세 가지 오판 케이스:
    (1) Apr 2~3 -10% 하락: sideways로 판단, 역추세 LONG 물타기 손실
    (2) Apr 8 87달러 1캔들 스파이크: trend_up으로 승격되면 안 됨
    (3) Apr 14~15 강한 상승: 진입이 늦음
  이 세 케이스를 모두 걸러내도록 **독립적인 4개 규칙**의 투표로 국면을 결정한다.

규칙 (각 -1/0/+1 을 반환):
  A. 캔들 몸통 누적 방향성 (ATR 정규화)
     sum(sign(close-open) * |close-open| / ATR) over body_window
     합 ≥  body_threshold →  +1
     합 ≤ -body_threshold →  -1

  B. BB 외부 체류 연속 캔들 수
     close > bb_upper 가 out_streak_min봉 이상 연속 → +1
     close < bb_lower 가 out_streak_min봉 이상 연속 → -1
     (1캔들 스파이크는 streak < min 이라 0점)

  C. 스윙 구조 (HH-HL / LH-LL)
     최근 swing_window봉 (high 최대, low 최소) vs 그 이전 swing_window봉
     모두 상승 → +1 (HH+HL), 모두 하락 → -1

  D. 중단선 대비 종가 위치의 지속성
     최근 mid_persist_window봉 모두 close > mid AND 괴리율이 확장 → +1
     최근 mid_persist_window봉 모두 close < mid AND 괴리율이 확장 → -1

합산 score:
  score ≥  vote_threshold → raw TREND_UP
  score ≤ -vote_threshold → raw TREND_DOWN
  그 외                   → raw SIDEWAYS

V5/V7 방식 hysteresis:
  SIDEWAYS → TREND: 즉시 전환
  TREND → SIDEWAYS: hysteresis_candles 연속 sideways 조건 만족 시에만
  TREND_UP ↔ TREND_DOWN: 즉시 전환

V4 방식 쿨다운 (상속으로 자동 적용):
  TREND → SIDEWAYS 전환 직후 `cooldown_candles` 캔들 동안 횡보 신규 진입 차단.
  추세 지속 중의 "숨고르기"가 hysteresis 해제 후 즉시 반전매수/매도로 이어져
  whipsaw 손실을 내는 문제를 차단.

기존 BB V2의 BBW 필터, 물타기 간격, 진입/청산 로직은 그대로 유지.
V9가 추가로 오버라이드: detect_regime, compute_indicators, _trend_signals.
"""

import logging

import numpy as np
import pandas as pd
import ta

from src.utils.logger import setup_logger
from src.utils.log_manager import LogManager
from ..base import MarketRegime, Signal
from ..registry import register_strategy
from .hysteresis import apply_regime_hysteresis
from .trend import generate_trend_signals
from .v4 import BBV4Strategy

logger = setup_logger("hantrader.strategy.bb_v9")


def _streak(mask: pd.Series) -> pd.Series:
    """각 인덱스에서 끝나는 True 연속 구간의 길이를 반환한다."""
    m = mask.astype(int)
    # 0이 나올 때마다 그룹 번호 증가 → 같은 그룹 내 1들의 cumsum이 streak
    grp = (m == 0).cumsum()
    return m.groupby(grp).cumsum()


@register_strategy("bb_v9")
class BBV9Strategy(BBV4Strategy):
    """BB V9 전략: 4개 규칙 투표 기반 국면 판단 + Hysteresis + V4 쿨다운."""

    def __init__(
        self,
        atr_window: int = 14,
        body_window: int = 5,
        body_threshold: float = 2.0,
        out_streak_min: int = 2,
        swing_window: int = 5,
        mid_persist_window: int = 5,
        vote_threshold: int = 2,
        hysteresis_candles: int = 3,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "BB_V9_Strategy"
        self.atr_window = atr_window
        self.body_window = body_window
        self.body_threshold = body_threshold
        self.out_streak_min = out_streak_min
        self.swing_window = swing_window
        self.mid_persist_window = mid_persist_window
        self.vote_threshold = vote_threshold
        self.hysteresis_candles = hysteresis_candles

        logger.info(
            f"BB V9 전략 초기화: body_window={body_window}, "
            f"body_threshold={body_threshold}, out_streak_min={out_streak_min}, "
            f"swing_window={swing_window}, mid_persist_window={mid_persist_window}, "
            f"vote_threshold={vote_threshold}, hysteresis_candles={hysteresis_candles}, "
            f"atr_window={atr_window}"
        )

    # ------------------------------------------------------------------
    # 지표 계산: ATR 추가 (규칙 A 정규화용)
    # ------------------------------------------------------------------

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """기존 지표 + ATR."""
        out = super().compute_indicators(df)

        atr_ind = ta.volatility.AverageTrueRange(
            out["high"], out["low"], out["close"], window=self.atr_window,
        )
        out["atr"] = atr_ind.average_true_range()

        return out.dropna()

    # ------------------------------------------------------------------
    # 국면 판단: 4개 규칙 투표 + Hysteresis
    # ------------------------------------------------------------------

    def detect_regime(self, df: pd.DataFrame) -> pd.Series:
        """4개 규칙 투표 → raw regime → hysteresis 적용."""
        # === Rule A: 캔들 몸통 누적 방향성 (ATR 정규화) ===
        body = df["close"] - df["open"]
        body_sign = np.sign(body)
        atr_safe = df["atr"].replace(0, np.nan)
        body_norm = body_sign * (body.abs() / atr_safe)
        body_cum = body_norm.rolling(self.body_window).sum()

        score_a = pd.Series(0, index=df.index, dtype=int)
        score_a[body_cum >= self.body_threshold] = 1
        score_a[body_cum <= -self.body_threshold] = -1

        # === Rule B: BB 외부 체류 연속 캔들 수 ===
        above = df["close"] > df["bb_upper"]
        below = df["close"] < df["bb_lower"]
        above_streak = _streak(above)
        below_streak = _streak(below)

        score_b = pd.Series(0, index=df.index, dtype=int)
        score_b[above_streak >= self.out_streak_min] = 1
        score_b[below_streak >= self.out_streak_min] = -1

        # === Rule C: 스윙 구조 (HH-HL / LH-LL) ===
        w = self.swing_window
        recent_high = df["high"].rolling(w).max()
        recent_low = df["low"].rolling(w).min()
        prev_high = recent_high.shift(w)
        prev_low = recent_low.shift(w)

        score_c = pd.Series(0, index=df.index, dtype=int)
        score_c[(recent_high > prev_high) & (recent_low > prev_low)] = 1
        score_c[(recent_high < prev_high) & (recent_low < prev_low)] = -1

        # === Rule D: 중단선 대비 종가 위치의 지속성 ===
        mp = self.mid_persist_window
        diff = df["close"] - df["bb_middle"]
        above_mid = (diff > 0).astype(int)
        below_mid = (diff < 0).astype(int)
        all_above = above_mid.rolling(mp).sum() == mp
        all_below = below_mid.rolling(mp).sum() == mp

        mid_safe = df["bb_middle"].replace(0, np.nan)
        diff_abs_rel = diff.abs() / mid_safe
        diff_expanding = diff_abs_rel > diff_abs_rel.shift(mp)

        score_d = pd.Series(0, index=df.index, dtype=int)
        score_d[all_above & diff_expanding] = 1
        score_d[all_below & diff_expanding] = -1

        # === 합산 및 raw regime ===
        total = score_a + score_b + score_c + score_d

        raw = pd.Series(MarketRegime.SIDEWAYS, index=df.index)
        raw[total >= self.vote_threshold] = MarketRegime.TREND_UP
        raw[total <= -self.vote_threshold] = MarketRegime.TREND_DOWN

        # === Hysteresis ===
        final, filtered_count = apply_regime_hysteresis(raw, self.hysteresis_candles)

        # === 요약 로그 (각 규칙 발동 횟수 + raw/final 분포) ===
        raw_up = int((raw == MarketRegime.TREND_UP).sum())
        raw_dn = int((raw == MarketRegime.TREND_DOWN).sum())
        final_up = int((final == MarketRegime.TREND_UP).sum())
        final_dn = int((final == MarketRegime.TREND_DOWN).sum())
        self._log_info(
            f"V9 국면: raw(↑{raw_up}/↓{raw_dn}) → final(↑{final_up}/↓{final_dn}) "
            f"hysteresis 유지 {filtered_count}캔들 (총 {len(df)}캔들) | "
            f"규칙발동 A={int((score_a != 0).sum())} B={int((score_b != 0).sum())} "
            f"C={int((score_c != 0).sum())} D={int((score_d != 0).sum())}"
        )

        # === 국면 전환 시점 INFO 로그 (final 기준) ===
        # 첫 캔들 이후 final이 직전과 달라지는 지점만 골라서 기록한다.
        final_prev = final.shift(1)
        transitions = (final != final_prev) & final_prev.notna()
        for i in np.where(transitions.values)[0]:
            ts = df.index[i]
            a, b, c, d = (
                int(score_a.iloc[i]), int(score_b.iloc[i]),
                int(score_c.iloc[i]), int(score_d.iloc[i]),
            )
            t = int(total.iloc[i])
            prev_r = final_prev.iloc[i]
            prev_name = prev_r.value if hasattr(prev_r, "value") else str(prev_r)
            self._log_info(
                f"V9 전환 | {ts} | {prev_name} → {final.iloc[i].value} | "
                f"A={a:+d} B={b:+d} C={c:+d} D={d:+d} total={t:+d} "
                f"raw={raw.iloc[i].value} close={df['close'].iloc[i]:.4f}"
            )

        # === 캔들별 DEBUG 로그 (모든 시점의 A/B/C/D/total/raw/final) ===
        # 성능: LogManager 레벨이 DEBUG가 아니면 루프/포맷팅을 건너뛴다.
        # (HanLogger에는 isEnabledFor가 없어 LogManager._level로 사전 체크)
        if LogManager.instance()._level <= logging.DEBUG:
            idx = df.index
            sa = score_a.to_numpy(); sb = score_b.to_numpy()
            sc = score_c.to_numpy(); sd = score_d.to_numpy()
            tot = total.to_numpy()
            raw_arr = raw.to_numpy(); final_arr = final.to_numpy()
            closes = df["close"].to_numpy()
            lowers = df["bb_lower"].to_numpy()
            mids = df["bb_middle"].to_numpy()
            uppers = df["bb_upper"].to_numpy()
            atrs = df["atr"].to_numpy()
            for i in range(len(df)):
                self._log_debug(
                    f"V9 score | {idx[i]} | "
                    f"A={int(sa[i]):+d} B={int(sb[i]):+d} "
                    f"C={int(sc[i]):+d} D={int(sd[i]):+d} "
                    f"total={int(tot[i]):+d} → raw={raw_arr[i].value} "
                    f"final={final_arr[i].value} | close={closes[i]:.4f} "
                    f"bb=[{lowers[i]:.4f}, {mids[i]:.4f}, {uppers[i]:.4f}] "
                    f"atr={atrs[i]:.4f}"
                )

        return final

    # ------------------------------------------------------------------
    # 추세장 시그널 오버라이드: 역추세(반전) 진입 차단 (Option A)
    # ------------------------------------------------------------------

    def _trend_signals(
        self,
        ts,
        price,
        bbp,
        bb_width,
        leverage,
        regime,
        row,
        long_step,
        short_step,
        entry_price,
        peak_price: float = 0.0,
        trough_price: float = float("inf"),
    ) -> list[Signal]:
        """V9 추세장 시그널.

        기존 BB 전략은 추세장에서도 '반대 방향 반전매매'를 허용했다
        (BB 상단에서 regime=DOWN이면 Short 진입, BB 하단에서 regime=UP이면
        Long 진입). 이는 엄밀히 반전매매로, 추세장에서는 칼날 잡기로
        기능할 위험이 있다.

        V9는 `allow_counter_trend=False` 로 호출해서 추세장에서는
        '추세추종 방향' 시그널만 발생시킨다. 물타기 후 손절/트레일링/익절
        로직은 그대로 유지되어 포지션 관리는 변경 없음.
        """
        return generate_trend_signals(
            ts=ts, price=price, bbp=bbp, bb_width=bb_width, leverage=leverage,
            regime=regime, row=row,
            long_step=long_step, short_step=short_step, entry_price=entry_price,
            stoploss_pct=self.stoploss_pct,
            takeprofit_pct=self.takeprofit_pct,
            trailing_start_pct=self.trailing_start_pct,
            trailing_stop_pct=self.trailing_stop_pct,
            peak_price=peak_price, trough_price=trough_price,
            logger=logger,
            allow_counter_trend=False,
        )

    # ------------------------------------------------------------------
    # 로그 라우팅: _log_ctx 있으면 signal 카테고리로, 없으면 모듈 logger
    # ------------------------------------------------------------------

    def _log_info(self, msg: str) -> None:
        if self._log_ctx is not None:
            self._log_ctx.signal(msg, level="INFO")
        else:
            logger.info(msg)

    def _log_debug(self, msg: str) -> None:
        if self._log_ctx is not None:
            self._log_ctx.signal(msg, level="DEBUG")
        else:
            logger.debug(msg)
