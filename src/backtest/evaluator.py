"""백테스트 평가 모듈.

거래 내역과 equity curve로부터 성과 지표를 계산한다.

평가 지표 설명:
- Total Return: 전체 수익률 (최종 자본 / 초기 자본 - 1)
- Sharpe Ratio: 위험 대비 수익 비율 (연간화). 1 이상이면 양호, 2 이상이면 우수
- Max Drawdown: 최대 낙폭. 고점 대비 최대 하락 비율. 작을수록 좋음
- Win Rate: 승률. 수익 거래 수 / 전체 거래 수
- Profit Factor: 총 수익 / 총 손실의 절대값. 1 이상이면 수익, 2 이상이면 우수
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .engine import Trade


@dataclass
class BacktestMetrics:
    """백테스트 평가 결과."""
    # 기본 정보
    initial_capital: float = 0.0
    final_capital: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0

    # 핵심 평가 지표
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0

    # 거래 통계 (포지션 단위: 같은 position_id의 진입/물타기를 하나로 집계)
    total_trades: int = 0       # 총 포지션 수
    winning_trades: int = 0     # 수익 포지션 수 (net PnL > 0)
    losing_trades: int = 0      # 손실 포지션 수 (net PnL < 0)
    neutral_trades: int = 0     # 무손익 포지션 수 (net PnL == 0)
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    avg_trade_pnl: float = 0.0

    # 기간별 수익
    monthly_returns: pd.Series | None = None
    trade_returns: pd.Series | None = None


class BacktestEvaluator:
    """백테스트 결과 평가기."""

    def __init__(self, risk_free_rate: float = 0.02):
        """
        Args:
            risk_free_rate: 무위험 수익률 (연간, 기본 2%)
        """
        self.risk_free_rate = risk_free_rate

    def evaluate(
        self,
        trades: list[Trade],
        equity_df: pd.DataFrame,
        initial_capital: float,
    ) -> BacktestMetrics:
        """거래 내역과 equity curve로 평가 지표를 계산한다."""
        metrics = BacktestMetrics()
        metrics.initial_capital = initial_capital

        if not trades or equity_df.empty:
            metrics.final_capital = initial_capital
            return metrics

        # 기본 정보
        metrics.final_capital = equity_df["equity"].iloc[-1]
        metrics.total_pnl = metrics.final_capital - initial_capital
        metrics.total_return_pct = metrics.total_pnl / initial_capital

        # 거래 통계 — 포지션 단위 집계 (같은 position_id의 물타기를 합산해서 1건으로)
        position_pnls: dict[int, float] = {}
        for t in trades:
            position_pnls[t.position_id] = position_pnls.get(t.position_id, 0.0) + t.pnl
        pnls = list(position_pnls.values())

        metrics.total_trades = len(pnls)
        metrics.winning_trades = sum(1 for p in pnls if p > 0)
        metrics.losing_trades = sum(1 for p in pnls if p < 0)
        metrics.neutral_trades = sum(1 for p in pnls if p == 0)
        metrics.win_rate = metrics.winning_trades / metrics.total_trades if metrics.total_trades > 0 else 0

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        metrics.avg_win = np.mean(wins) if wins else 0
        metrics.avg_loss = np.mean(losses) if losses else 0
        metrics.largest_win = max(wins) if wins else 0
        metrics.largest_loss = min(losses) if losses else 0
        metrics.avg_trade_pnl = np.mean(pnls) if pnls else 0

        # Profit Factor (포지션 단위 PnL 합산과 동일, trade-row 집계와 값은 같음)
        total_wins = sum(wins) if wins else 0
        total_losses = abs(sum(losses)) if losses else 0
        metrics.profit_factor = total_wins / total_losses if total_losses > 0 else float("inf") if total_wins > 0 else 0

        # Sharpe Ratio (연간화)
        metrics.sharpe_ratio = self._calc_sharpe(equity_df)

        # Max Drawdown
        metrics.max_drawdown, metrics.max_drawdown_pct = self._calc_max_drawdown(equity_df)

        # 월별 수익률
        metrics.monthly_returns = self._calc_monthly_returns(equity_df, initial_capital)

        # 거래별 수익
        metrics.trade_returns = pd.Series(pnls)

        return metrics

    def _calc_sharpe(self, equity_df: pd.DataFrame) -> float:
        """Sharpe Ratio를 계산한다 (연간화)."""
        returns = equity_df["equity"].pct_change().dropna()
        if returns.empty or returns.std() == 0:
            return 0.0

        # 시간 간격으로 연간화 팩터 추정
        if len(equity_df) >= 2:
            time_diff = (equity_df.index[-1] - equity_df.index[0]).total_seconds()
            n_periods = len(equity_df)
            if time_diff > 0:
                periods_per_year = n_periods / (time_diff / (365.25 * 24 * 3600))
            else:
                periods_per_year = 252  # 기본값
        else:
            periods_per_year = 252

        excess_return = returns.mean() - self.risk_free_rate / periods_per_year
        return float(excess_return / returns.std() * np.sqrt(periods_per_year))

    def _calc_max_drawdown(self, equity_df: pd.DataFrame) -> tuple[float, float]:
        """Maximum Drawdown을 계산한다.

        Returns:
            (절대 금액, 비율)
        """
        equity = equity_df["equity"]
        peak = equity.cummax()
        drawdown = equity - peak
        max_dd = drawdown.min()
        max_dd_pct = (drawdown / peak).min()
        return float(max_dd), float(max_dd_pct)

    def _calc_monthly_returns(self, equity_df: pd.DataFrame, initial_capital: float) -> pd.Series:
        """월별 수익률을 계산한다."""
        equity = equity_df["equity"]
        monthly = equity.resample("ME").last()
        # 첫 번째 달은 초기 자본 대비 수익률로 계산
        returns = monthly.pct_change()
        if len(monthly) > 0:
            returns.iloc[0] = (monthly.iloc[0] - initial_capital) / initial_capital
        return returns
