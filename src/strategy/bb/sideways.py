"""BB 전략 횡보장 반전매매 시그널 생성."""

import logging

import pandas as pd

from ..base import Signal, SignalType
from . import levels


def generate_sideways_signals(
    ts: pd.Timestamp,
    price: float,
    bbp: float,
    leverage: int,
    long_step: int,
    short_step: int,
    entry_price: float,
    adx_entry_block: float,
    adx: float,
    adx_rising: bool,
    logger: logging.Logger,
) -> list[Signal]:
    """횡보장에서 BB% 기반 반전매매 시그널을 생성한다.

    한 캔들에서는 하나의 방향만 처리한다.
    - 포지션 없음: BB% 위치에 따라 long 또는 short 진입
    - long 보유: 익절(BB상단 65%) 또는 손절만 처리
    - short 보유: 익절(BB하단 35%) 또는 손절만 처리

    ADX >= adx_entry_block 이면서 상승 중이면 추세 전환 임박으로 판단하여
    신규 진입을 억제한다. 기존 포지션의 청산/손절은 정상 처리한다.
    """
    signals: list[Signal] = []

    # 추세 전환 임박 여부: ADX가 기준 이상이면서 상승 중
    trend_approaching = adx >= adx_entry_block and adx_rising

    logger.debug(
        f"[횡보] {ts} | price={price:,.2f} BB%={bbp:.3f} ADX={adx:.1f} "
        f"ADX상승={adx_rising} 추세임박={trend_approaching} | "
        f"포지션: L{long_step}단계 S{short_step}단계 진입가={entry_price:,.2f}"
    )

    # === Long 포지션 보유 중 ===
    if long_step > 0:
        # 손절 체크 (우선)
        for level in levels.LONG_STOP_LEVELS:
            if bbp <= level["bbp"]:
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.STOP_LOSS,
                    price=price,
                    leverage=leverage,
                    stop_loss_ratio=level["stop_ratio"],
                    reason=f"횡보 Long 손절 {int(level['stop_ratio']*100)}% (BB%={bbp:.2f})",
                ))
                return signals  # 손절 시 다른 시그널 생성하지 않음

        # BB 상단영역 진입 → 청산 (매도 조건 BB% >= 0.65)
        if bbp >= 0.65:
            pnl_pct = (price - entry_price) / entry_price if entry_price > 0 else 0
            if pnl_pct >= 0:
                label = f"횡보 Long 익절 BB상단영역 (BB%={bbp:.2f}, PnL={pnl_pct:.2%})"
            else:
                label = f"횡보 Long 청산 BB상단영역 (BB%={bbp:.2f}, PnL={pnl_pct:.2%})"
            signals.append(Signal(
                timestamp=ts,
                signal_type=SignalType.LONG_EXIT,
                price=price,
                leverage=leverage,
                reason=label,
            ))
            return signals

        # 물타기 (손실 중일 때만, BB 하단 방향으로 더 내려갔을 때)
        # ADX 상승 중이면 추세 전환 임박 → 물타기 억제 (손실 확대 방지)
        if entry_price > 0 and price < entry_price and not trend_approaching:
            for level in levels.LONG_ENTRY_LEVELS:
                if bbp <= level["bbp"] and long_step < level["step"]:
                    signals.append(Signal(
                        timestamp=ts,
                        signal_type=SignalType.LONG_ENTRY,
                        price=price,
                        leverage=leverage,
                        position_ratio=level["ratio"],
                        entry_step=level["step"],
                        reason=f"횡보 반전매수 {level['step']}차 (BB%={bbp:.2f})",
                    ))
                    break
            else:
                logger.debug(
                    f"[횡보] Long 물타기 조건 미달: BB%={bbp:.3f} "
                    f"(필요≤{levels.LONG_ENTRY_LEVELS[long_step]['bbp'] if long_step < len(levels.LONG_ENTRY_LEVELS) else 'MAX'})"
                )
        else:
            if trend_approaching:
                logger.debug(f"[횡보] Long 물타기 억제: ADX 상승 중 (ADX={adx:.1f})")
            elif price >= entry_price:
                logger.debug(
                    f"[횡보] Long 물타기 스킵: 수익 중 "
                    f"(price={price:,.2f} >= entry={entry_price:,.2f})"
                )
        return signals

    # === Short 포지션 보유 중 ===
    if short_step > 0:
        # 손절 체크 (우선)
        for level in levels.SHORT_STOP_LEVELS:
            if bbp >= level["bbp"]:
                signals.append(Signal(
                    timestamp=ts,
                    signal_type=SignalType.STOP_LOSS,
                    price=price,
                    leverage=leverage,
                    stop_loss_ratio=level["stop_ratio"],
                    reason=f"횡보 Short 손절 {int(level['stop_ratio']*100)}% (BB%={bbp:.2f})",
                ))
                return signals

        # BB 하단영역 진입 → 청산 (매수 조건 BB% <= 0.35)
        if bbp <= 0.35:
            pnl_pct = (entry_price - price) / entry_price if entry_price > 0 else 0
            if pnl_pct >= 0:
                label = f"횡보 Short 익절 BB하단영역 (BB%={bbp:.2f}, PnL={pnl_pct:.2%})"
            else:
                label = f"횡보 Short 청산 BB하단영역 (BB%={bbp:.2f}, PnL={pnl_pct:.2%})"
            signals.append(Signal(
                timestamp=ts,
                signal_type=SignalType.SHORT_EXIT,
                price=price,
                leverage=leverage,
                reason=label,
            ))
            return signals

        # 물타기 (손실 중일 때만, BB 상단 방향으로 더 올라갔을 때)
        # ADX 상승 중이면 추세 전환 임박 → 물타기 억제 (손실 확대 방지)
        if entry_price > 0 and price > entry_price and not trend_approaching:
            for level in levels.SHORT_ENTRY_LEVELS:
                if bbp >= level["bbp"] and short_step < level["step"]:
                    signals.append(Signal(
                        timestamp=ts,
                        signal_type=SignalType.SHORT_ENTRY,
                        price=price,
                        leverage=leverage,
                        position_ratio=level["ratio"],
                        entry_step=level["step"],
                        reason=f"횡보 반전매도 {level['step']}차 (BB%={bbp:.2f})",
                    ))
                    break
            else:
                logger.debug(
                    f"[횡보] Short 물타기 조건 미달: BB%={bbp:.3f} "
                    f"(필요≥{levels.SHORT_ENTRY_LEVELS[short_step]['bbp'] if short_step < len(levels.SHORT_ENTRY_LEVELS) else 'MAX'})"
                )
        else:
            if trend_approaching:
                logger.debug(f"[횡보] Short 물타기 억제: ADX 상승 중 (ADX={adx:.1f})")
            elif price <= entry_price:
                logger.debug(
                    f"[횡보] Short 물타기 스킵: 수익 중 "
                    f"(price={price:,.2f} <= entry={entry_price:,.2f})"
                )
        return signals

    # === 포지션 없음: 신규 진입 ===
    # ADX 상승 중이면 추세 전환 임박 → 신규 진입 억제 (관망)
    if trend_approaching:
        logger.debug(
            f"[횡보] 신규진입 억제: ADX 상승 중 (ADX={adx:.1f}, 기준={adx_entry_block})"
        )
        return signals

    # BB 하단 → Long 진입
    for level in levels.LONG_ENTRY_LEVELS:
        if bbp <= level["bbp"]:
            signals.append(Signal(
                timestamp=ts,
                signal_type=SignalType.LONG_ENTRY,
                price=price,
                leverage=leverage,
                position_ratio=level["ratio"],
                entry_step=level["step"],
                reason=f"횡보 반전매수 {level['step']}차 (BB%={bbp:.2f})",
            ))
            return signals  # 한 방향만

    # BB 상단 → Short 진입
    for level in levels.SHORT_ENTRY_LEVELS:
        if bbp >= level["bbp"]:
            signals.append(Signal(
                timestamp=ts,
                signal_type=SignalType.SHORT_ENTRY,
                price=price,
                leverage=leverage,
                position_ratio=level["ratio"],
                entry_step=level["step"],
                reason=f"횡보 반전매도 {level['step']}차 (BB%={bbp:.2f})",
            ))
            return signals

    # 조건 미달 → 관망
    logger.debug(
        f"[횡보] 신규진입 조건 미달 — 관망: BB%={bbp:.3f} "
        f"(Long≤{levels.LONG_ENTRY_LEVELS[0]['bbp']}, Short≥{levels.SHORT_ENTRY_LEVELS[0]['bbp']})"
    )
    return signals
