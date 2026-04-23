"""BB 전략 포지션 상태 업데이트."""

from ..base import Signal, SignalType


def update_position_state(
    sig: Signal,
    long_step: int,
    short_step: int,
    entry_price: float,
    total_weight: float,
) -> tuple[int, int, float, float]:
    """시그널에 따라 포지션 상태를 업데이트한다 (진입가는 금액 가중평균)."""
    if sig.signal_type == SignalType.LONG_ENTRY:
        long_step = sig.entry_step
        w = sig.position_ratio
        if total_weight == 0:
            entry_price = sig.price
            total_weight = w
        else:
            entry_price = (entry_price * total_weight + sig.price * w) / (total_weight + w)
            total_weight += w

    elif sig.signal_type == SignalType.SHORT_ENTRY:
        short_step = sig.entry_step
        w = sig.position_ratio
        if total_weight == 0:
            entry_price = sig.price
            total_weight = w
        else:
            entry_price = (entry_price * total_weight + sig.price * w) / (total_weight + w)
            total_weight += w

    elif sig.signal_type in (
        SignalType.LONG_EXIT, SignalType.SHORT_EXIT,
        SignalType.TAKE_PROFIT,
    ):
        long_step = 0
        short_step = 0
        entry_price = 0.0
        total_weight = 0.0

    elif sig.signal_type == SignalType.STOP_LOSS:
        if sig.stop_loss_ratio >= 1.0:
            long_step = 0
            short_step = 0
            entry_price = 0.0
            total_weight = 0.0
        # 50% 손절은 단계 유지 (일부 청산)

    return long_step, short_step, entry_price, total_weight
