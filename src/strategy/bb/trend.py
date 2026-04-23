"""BB 전략 추세장 시그널 생성 + 추세 확인."""

import logging

import pandas as pd

from ..base import Signal, SignalType, MarketRegime
from . import levels


def confirm_trend(row: pd.Series, is_uptrend: bool, logger: logging.Logger) -> bool:
    """MACD, RSI, Volume을 종합하여 추세 지속 여부를 확인한다."""
    confirmations = 0
    details = []
    direction = "UP" if is_uptrend else "DOWN"

    # MACD: diff 양수면 상승, 음수면 하락
    macd_ok = (is_uptrend and row["macd_diff"] > 0) or (not is_uptrend and row["macd_diff"] < 0)
    if macd_ok:
        confirmations += 1
        details.append(f"MACD=O({row['macd_diff']:.2f})")
    else:
        details.append(f"MACD=X({row['macd_diff']:.2f})")

    # RSI: 50 이상이면 상승 우세, 50 이하이면 하락 우세
    rsi_ok = (is_uptrend and row["rsi"] > 50) or (not is_uptrend and row["rsi"] < 50)
    if rsi_ok:
        confirmations += 1
        details.append(f"RSI=O({row['rsi']:.1f})")
    else:
        details.append(f"RSI=X({row['rsi']:.1f})")

    # Volume: 평균 이상이면 추세 신뢰도 상승
    vol_ok = row["volume"] > row["volume_sma"]
    if vol_ok:
        confirmations += 1
        details.append("Vol=O")
    else:
        details.append("Vol=X")

    confirmed = confirmations >= 2
    logger.debug(
        f"[추세확인] {direction} {confirmations}/3 → "
        f"{'확인' if confirmed else '미확인'} | {' '.join(details)}"
    )
    return confirmed


def generate_trend_signals(
    ts: pd.Timestamp,
    price: float,
    bbp: float,
    bb_width: float,
    leverage: int,
    regime: MarketRegime,
    row: pd.Series,
    long_step: int,
    short_step: int,
    entry_price: float,
    stoploss_pct: float,
    takeprofit_pct: float,
    trailing_start_pct: float,
    trailing_stop_pct: float,
    peak_price: float,
    trough_price: float,
    logger: logging.Logger,
) -> list[Signal]:
    """추세장에서 추세추종/반전매매 시그널을 생성한다.

    현재 포지션 방향과 충돌하는 시그널은 생성하지 않는다.
    트레일링 스톱: PnL이 trailing_start_pct 이상이면 활성화,
    고점/저점 대비 trailing_stop_pct 되돌리면 익절 청산.
    """
    signals: list[Signal] = []

    is_uptrend = regime == MarketRegime.TREND_UP
    trend_confirmed = confirm_trend(row, is_uptrend, logger)

    logger.debug(
        f"[추세] {ts} | price={price:,.2f} BB%={bbp:.3f} BBw={bb_width:.4f} "
        f"regime={'UP' if is_uptrend else 'DOWN'} confirmed={trend_confirmed} | "
        f"포지션: L{long_step}단계 S{short_step}단계 진입가={entry_price:,.2f}"
    )

    # --- 물타기 3회 후 손절/트레일링스톱/익절 (최우선) ---
    if long_step >= 3 and entry_price > 0:
        pnl_pct = (price - entry_price) / entry_price
        # 손절
        if pnl_pct <= -stoploss_pct:
            signals.append(Signal(
                timestamp=ts,
                signal_type=SignalType.STOP_LOSS,
                price=price,
                leverage=leverage,
                stop_loss_ratio=1.0,
                reason=f"추세 Long 손절 (PnL={pnl_pct:.2%}, 기준=-{stoploss_pct:.2%})",
            ))
            return signals
        # 트레일링 스톱: 수익이 기준 이상 도달한 후 고점 대비 되돌림 시 익절
        peak_pnl = (peak_price - entry_price) / entry_price if peak_price > 0 else 0
        if peak_pnl >= trailing_start_pct:
            drawdown_from_peak = (peak_price - price) / peak_price
            if drawdown_from_peak >= trailing_stop_pct:
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.TAKE_PROFIT,
                    price=price,
                    leverage=leverage,
                    reason=f"추세 Long 트레일링 익절 (PnL={pnl_pct:.2%}, 고점대비=-{drawdown_from_peak:.2%})",
                ))
                return signals
        # 고정 익절 (트레일링에 안 걸린 경우 폴백)
        elif pnl_pct >= takeprofit_pct:
            signals.append(Signal(
                timestamp=ts,
                signal_type=SignalType.TAKE_PROFIT,
                price=price,
                leverage=leverage,
                reason=f"추세 Long 익절 (PnL={pnl_pct:.2%}, 기준=+{takeprofit_pct:.2%})",
            ))
            return signals

    if short_step >= 3 and entry_price > 0:
        pnl_pct = (entry_price - price) / entry_price
        # 손절
        if pnl_pct <= -stoploss_pct:
            signals.append(Signal(
                timestamp=ts,
                signal_type=SignalType.STOP_LOSS,
                price=price,
                leverage=leverage,
                stop_loss_ratio=1.0,
                reason=f"추세 Short 손절 (PnL={pnl_pct:.2%}, 기준=-{stoploss_pct:.2%})",
            ))
            return signals
        # 트레일링 스톱: 수익이 기준 이상 도달한 후 저점 대비 되돌림 시 익절
        trough_pnl = (entry_price - trough_price) / entry_price if trough_price < float("inf") else 0
        if trough_pnl >= trailing_start_pct:
            drawdown_from_trough = (price - trough_price) / trough_price
            if drawdown_from_trough >= trailing_stop_pct:
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.TAKE_PROFIT,
                    price=price,
                    leverage=leverage,
                    reason=f"추세 Short 트레일링 익절 (PnL={pnl_pct:.2%}, 저점대비=+{drawdown_from_trough:.2%})",
                ))
                return signals
        # 고정 익절 (트레일링에 안 걸린 경우 폴백)
        elif pnl_pct >= takeprofit_pct:
            signals.append(Signal(
                timestamp=ts,
                signal_type=SignalType.TAKE_PROFIT,
                price=price,
                leverage=leverage,
                reason=f"추세 Short 익절 (PnL={pnl_pct:.2%}, 기준=+{takeprofit_pct:.2%})",
            ))
            return signals

    # --- BB 상단 도달 ---
    if bbp >= 0.80:
        if is_uptrend and trend_confirmed:
            # 상승 추세 → Long 진입/추가 (short 보유 중이면 무시, 최대 3회)
            if short_step == 0 and long_step < 3:
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.LONG_ENTRY,
                    price=price,
                    leverage=leverage,
                    position_ratio=0.20,
                    entry_step=long_step + 1,
                    reason=f"추세추종 Long BB상단 (BB%={bbp:.2f}, regime=UP)",
                ))
            else:
                if short_step > 0:
                    logger.debug(f"[추세] BB상단 Long 미진입: Short 포지션 보유 중 (S{short_step}단계)")
                elif long_step >= 3:
                    logger.debug(f"[추세] BB상단 Long 미진입: 최대 단계 도달 (L{long_step}단계)")
        else:
            # 하락 추세 → Short 진입/추가 (long 보유 중이면 무시)
            if long_step == 0:
                for level in levels.SHORT_ENTRY_LEVELS:
                    if bbp >= level["bbp"] and short_step < level["step"]:
                        signals.append(Signal(
                            timestamp=ts,
                            signal_type=SignalType.SHORT_ENTRY,
                            price=price,
                            leverage=leverage,
                            position_ratio=level["ratio"],
                            entry_step=level["step"],
                            reason=f"추세장 반전매도 {level['step']}차 (BB%={bbp:.2f}, regime=DOWN)",
                        ))
                        break
            else:
                logger.debug(f"[추세] BB상단 Short 미진입: Long 포지션 보유 중 (L{long_step}단계)")
            if not trend_confirmed:
                logger.debug("[추세] BB상단 미확인: 추세확인 실패 (MACD/RSI/Vol)")
        return signals

    # --- BB 하단 도달 ---
    if bbp <= 0.20:
        if not is_uptrend and trend_confirmed:
            # 하락 추세 → Short 진입/추가 (long 보유 중이면 무시, 최대 3회)
            if long_step == 0 and short_step < 3:
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.SHORT_ENTRY,
                    price=price,
                    leverage=leverage,
                    position_ratio=0.20,
                    entry_step=short_step + 1,
                    reason=f"추세추종 Short BB하단 (BB%={bbp:.2f}, regime=DOWN)",
                ))
            else:
                if long_step > 0:
                    logger.debug(f"[추세] BB하단 Short 미진입: Long 포지션 보유 중 (L{long_step}단계)")
                elif short_step >= 3:
                    logger.debug(f"[추세] BB하단 Short 미진입: 최대 단계 도달 (S{short_step}단계)")
        else:
            # 상승 추세 → Long 진입/추가 (short 보유 중이면 무시)
            if short_step == 0:
                for level in levels.LONG_ENTRY_LEVELS:
                    if bbp <= level["bbp"] and long_step < level["step"]:
                        signals.append(Signal(
                            timestamp=ts,
                            signal_type=SignalType.LONG_ENTRY,
                            price=price,
                            leverage=leverage,
                            position_ratio=level["ratio"],
                            entry_step=level["step"],
                            reason=f"추세장 반전매수 {level['step']}차 (BB%={bbp:.2f}, regime=UP)",
                        ))
                        break
            else:
                logger.debug(f"[추세] BB하단 Long 미진입: Short 포지션 보유 중 (S{short_step}단계)")
            if not trend_confirmed:
                logger.debug("[추세] BB하단 미확인: 추세확인 실패 (MACD/RSI/Vol)")
        return signals

    # BB 중간대 → 관망
    logger.debug(f"[추세] BB 중간대 — 관망: BB%={bbp:.3f} (진입조건: ≥0.80 또는 ≤0.20)")
    return signals
