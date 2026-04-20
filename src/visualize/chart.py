"""매매 차트 생성기.

백테스트/시뮬레이터/실거래에서 공통으로 사용하는 HTML 차트를 생성한다.

- 캔들스틱 + Bollinger Bands
- 매수/매도 시그널을 상하 화살표로 표시
  * ▲ (아래→위, 초록): LONG 진입/매수
  * ▼ (위→아래, 빨강): SHORT 진입/매도
  * ■ (노랑): 청산/익절
  * ✖ (자주): 손절
- 포지션 보유 구간을 배경색(long=초록 / short=빨강)으로 음영 표시
- 하단 서브플롯: equity curve (있는 경우)

plotly로 self-contained HTML을 생성한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.strategy.base import Signal, SignalType
from src.utils.logger import setup_logger
from src.utils.timeframe import KST

logger = setup_logger("hantrader.visualize")


# ---------------------------------------------------------------------------
# 데이터 구조
# ---------------------------------------------------------------------------

@dataclass
class PositionSpan:
    """포지션 보유 구간."""
    side: str                          # "long" or "short"
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp | None
    entry_price: float
    exit_price: float | None = None
    pnl: float | None = None


# 시그널 종류별 마커 설정: (심볼, 색상, 위치 오프셋 부호, 이름표)
# 오프셋 부호: +1 → 캔들 high 위쪽, -1 → 캔들 low 아래쪽
_SIGNAL_MARKERS = {
    SignalType.LONG_ENTRY:  {"symbol": "triangle-up",   "color": "#22c55e", "offset": -1, "label": "LONG 진입"},
    SignalType.SHORT_ENTRY: {"symbol": "triangle-down", "color": "#ef4444", "offset": +1, "label": "SHORT 진입"},
    SignalType.LONG_EXIT:   {"symbol": "square",        "color": "#facc15", "offset": +1, "label": "LONG 청산"},
    SignalType.SHORT_EXIT:  {"symbol": "square",        "color": "#facc15", "offset": -1, "label": "SHORT 청산"},
    SignalType.STOP_LOSS:   {"symbol": "x",             "color": "#a855f7", "offset": -1, "label": "손절"},
    SignalType.TAKE_PROFIT: {"symbol": "star",          "color": "#38bdf8", "offset": +1, "label": "익절"},
}


# ---------------------------------------------------------------------------
# TradeChart
# ---------------------------------------------------------------------------

class TradeChart:
    """공통 매매 차트 생성기.

    사용 예:
        chart = TradeChart(exchange="binance_futures", symbol="BTC/USDT", timeframe="1h")
        path = chart.render(
            df=ohlcv_df,
            signals=signals,
            position_spans=spans,
            equity_df=equity_df,
            output_dir="data/backtest/20260420",
            title_suffix="backtest",
        )
    """

    def __init__(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        bb_period: int = 20,
        bb_std: float = 2.0,
    ):
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.bb_period = bb_period
        self.bb_std = bb_std

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------

    def render(
        self,
        df: pd.DataFrame,
        signals: Iterable[Signal] | None = None,
        position_spans: Iterable[PositionSpan] | None = None,
        equity_df: Optional[pd.DataFrame] = None,
        output_dir: str | Path = "data/charts",
        title_suffix: str = "",
        filename: str | None = None,
    ) -> Path:
        """차트 HTML을 생성하여 파일로 저장하고 경로를 반환한다.

        Args:
            df: OHLCV DataFrame (index=datetime, columns=open/high/low/close/volume)
            signals: 시그널 리스트 (선택)
            position_spans: 포지션 보유 구간 리스트 (선택)
            equity_df: equity curve DataFrame (index=datetime, column=equity)
            output_dir: 저장 디렉토리
            title_suffix: 차트 제목 꼬리표 (e.g., "backtest", "simulator", "trader")
            filename: 파일명 (미지정 시 자동 생성)
        """
        if df is None or df.empty:
            raise ValueError("OHLCV 데이터가 비어있습니다.")

        signals = list(signals or [])
        position_spans = list(position_spans or [])

        # 지표 계산 (BB)
        df = self._add_bollinger(df)

        # 서브플롯: equity_df가 있으면 2행, 없으면 1행
        has_equity = equity_df is not None and not equity_df.empty
        if has_equity:
            fig = make_subplots(
                rows=2, cols=1, shared_xaxes=True,
                row_heights=[0.75, 0.25], vertical_spacing=0.04,
                subplot_titles=("가격 / 매매 시그널", "Equity Curve"),
            )
        else:
            fig = make_subplots(
                rows=1, cols=1,
                subplot_titles=("가격 / 매매 시그널",),
            )

        # 가격 패널
        self._add_candles(fig, df, row=1)
        self._add_bollinger_traces(fig, df, row=1)
        self._add_position_spans(fig, position_spans, df, row=1)
        self._add_signal_markers(fig, signals, df, row=1)

        # Equity 패널
        if has_equity:
            self._add_equity(fig, equity_df, row=2)

        # 레이아웃
        title = f"{self.exchange}/{self.symbol} ({self.timeframe})"
        if title_suffix:
            title += f" — {title_suffix}"
        fig.update_layout(
            title=dict(text=title, x=0.5, xanchor="center", font=dict(color="#e2e8f0", size=18)),
            template="plotly_dark",
            paper_bgcolor="#0f172a",
            plot_bgcolor="#0f172a",
            font=dict(color="#e2e8f0"),
            hovermode="x unified",
            margin=dict(l=40, r=40, t=70, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis_rangeslider_visible=False,
        )
        fig.update_xaxes(gridcolor="#1e293b")
        fig.update_yaxes(gridcolor="#1e293b")

        # 저장
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if filename is None:
            safe_sym = self.symbol.replace("/", "_")
            ts = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
            suffix = f"_{title_suffix}" if title_suffix else ""
            filename = f"chart_{self.exchange}_{safe_sym}_{self.timeframe}{suffix}_{ts}.html"
        filepath = out_dir / filename
        fig.write_html(str(filepath), include_plotlyjs="cdn", full_html=True)
        logger.info(f"차트 생성: {filepath}")
        return filepath

    # ------------------------------------------------------------------
    # 내부: 지표/트레이스 구성
    # ------------------------------------------------------------------

    def _add_bollinger(self, df: pd.DataFrame) -> pd.DataFrame:
        """DataFrame에 BB 상/중/하단을 추가해서 반환한다.

        이미 bb_upper/bb_middle/bb_lower가 있으면 그대로 사용한다.
        """
        if {"bb_upper", "bb_middle", "bb_lower"}.issubset(df.columns):
            return df
        out = df.copy()
        ma = out["close"].rolling(self.bb_period).mean()
        std = out["close"].rolling(self.bb_period).std()
        out["bb_middle"] = ma
        out["bb_upper"] = ma + self.bb_std * std
        out["bb_lower"] = ma - self.bb_std * std
        return out

    def _add_candles(self, fig: go.Figure, df: pd.DataFrame, row: int):
        fig.add_trace(
            go.Candlestick(
                x=df.index,
                open=df["open"], high=df["high"], low=df["low"], close=df["close"],
                name="OHLC",
                increasing_line_color="#22c55e",
                decreasing_line_color="#ef4444",
                showlegend=False,
            ),
            row=row, col=1,
        )

    def _add_bollinger_traces(self, fig: go.Figure, df: pd.DataFrame, row: int):
        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["bb_upper"],
                mode="lines",
                line=dict(color="rgba(148,163,184,0.6)", width=1),
                name=f"BB 상단 ({self.bb_period},{self.bb_std})",
                hovertemplate="BB 상단: %{y:,.2f}<extra></extra>",
            ),
            row=row, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["bb_lower"],
                mode="lines",
                line=dict(color="rgba(148,163,184,0.6)", width=1),
                fill="tonexty", fillcolor="rgba(148,163,184,0.08)",
                name="BB 하단",
                hovertemplate="BB 하단: %{y:,.2f}<extra></extra>",
            ),
            row=row, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=df.index, y=df["bb_middle"],
                mode="lines",
                line=dict(color="rgba(56,189,248,0.7)", width=1, dash="dot"),
                name="BB 중단 (MA)",
                hovertemplate="BB 중단: %{y:,.2f}<extra></extra>",
            ),
            row=row, col=1,
        )

    def _add_signal_markers(
        self, fig: go.Figure, signals: list[Signal], df: pd.DataFrame, row: int,
    ):
        """시그널 종류별로 그룹화하여 마커를 찍는다."""
        if not signals:
            return

        price_range = df["high"].max() - df["low"].min()
        offset_size = price_range * 0.008 if price_range > 0 else 0

        grouped: dict[SignalType, list[Signal]] = {}
        for sig in signals:
            grouped.setdefault(sig.signal_type, []).append(sig)

        for sig_type, sigs in grouped.items():
            cfg = _SIGNAL_MARKERS.get(sig_type)
            if cfg is None:
                continue

            xs, ys, texts = [], [], []
            for s in sigs:
                # 화살표 위치: 캔들 위/아래에 살짝 오프셋
                y = s.price + cfg["offset"] * offset_size
                xs.append(s.timestamp)
                ys.append(y)

                step = f" {s.entry_step}차" if s.entry_step else ""
                texts.append(
                    f"{cfg['label']}{step}<br>"
                    f"시각: {s.timestamp}<br>"
                    f"가격: {s.price:,.2f}<br>"
                    f"레버: {s.leverage}x<br>"
                    f"사유: {s.reason}"
                )

            fig.add_trace(
                go.Scatter(
                    x=xs, y=ys, mode="markers",
                    marker=dict(
                        symbol=cfg["symbol"], size=13,
                        color=cfg["color"],
                        line=dict(color="#0f172a", width=1),
                    ),
                    name=cfg["label"],
                    hovertext=texts, hoverinfo="text",
                ),
                row=row, col=1,
            )

    def _add_position_spans(
        self, fig: go.Figure, spans: list[PositionSpan], df: pd.DataFrame, row: int,
    ):
        """포지션 보유 구간을 배경 음영으로 표시하고, 평단가 선을 그린다."""
        if not spans:
            return

        x_min = df.index[0]
        x_max = df.index[-1]

        for sp in spans:
            x0 = sp.entry_time
            x1 = sp.exit_time if sp.exit_time is not None else x_max
            if x0 is None:
                continue
            if x1 < x_min or x0 > x_max:
                continue

            color = "rgba(34,197,94,0.10)" if sp.side == "long" else "rgba(239,68,68,0.10)"
            fig.add_vrect(
                x0=x0, x1=x1, fillcolor=color, line_width=0,
                layer="below", row=row, col=1,
            )

            # 평단가 선 (진입~청산 구간에만)
            line_color = "#22c55e" if sp.side == "long" else "#ef4444"
            fig.add_trace(
                go.Scatter(
                    x=[x0, x1], y=[sp.entry_price, sp.entry_price],
                    mode="lines",
                    line=dict(color=line_color, width=1, dash="dash"),
                    name=f"{sp.side.upper()} 평단",
                    showlegend=False,
                    hovertemplate=(
                        f"{sp.side.upper()} 평단: {sp.entry_price:,.2f}<extra></extra>"
                    ),
                ),
                row=row, col=1,
            )

    def _add_equity(self, fig: go.Figure, equity_df: pd.DataFrame, row: int):
        col = "equity" if "equity" in equity_df.columns else equity_df.columns[0]
        fig.add_trace(
            go.Scatter(
                x=equity_df.index, y=equity_df[col],
                mode="lines",
                line=dict(color="#38bdf8", width=1.5),
                fill="tozeroy", fillcolor="rgba(56,189,248,0.1)",
                name="Equity",
                hovertemplate="Equity: %{y:,.2f} USDT<extra></extra>",
            ),
            row=row, col=1,
        )
        fig.update_yaxes(title_text="USDT", row=row, col=1)


# ---------------------------------------------------------------------------
# 헬퍼: Trade 리스트 → PositionSpan 리스트
# ---------------------------------------------------------------------------

def trades_to_position_spans(trades: list) -> list[PositionSpan]:
    """백테스트 Trade 객체 리스트에서 포지션 구간을 추출한다.

    같은 position_id를 가진 Trade들을 하나의 PositionSpan으로 묶는다.
    (첫 진입 시각 → 마지막 청산 시각)
    """
    from src.backtest.engine import Trade  # lazy import
    if not trades:
        return []

    groups: dict[int, list[Trade]] = {}
    for t in trades:
        groups.setdefault(t.position_id, []).append(t)

    spans = []
    for pos_id, pos_trades in groups.items():
        pos_trades.sort(key=lambda x: (x.entry_time or pd.Timestamp.min))
        first = pos_trades[0]
        last = pos_trades[-1]
        total_margin = sum(t.position_size for t in pos_trades) or 1.0
        avg_entry = sum(t.entry_price * t.position_size for t in pos_trades) / total_margin
        total_pnl = sum(t.pnl for t in pos_trades)
        spans.append(PositionSpan(
            side=first.side,
            entry_time=first.entry_time,
            exit_time=last.exit_time,
            entry_price=avg_entry,
            exit_price=last.exit_price,
            pnl=total_pnl,
        ))
    return spans


def trade_records_to_position_spans(records: list) -> list[PositionSpan]:
    """실거래 TradeRecord 리스트에서 포지션 구간을 추출한다.

    entry/add 순서대로 진입, exit가 나오면 구간 종료.
    """
    if not records:
        return []

    spans: list[PositionSpan] = []
    open_side: str | None = None
    open_time: pd.Timestamp | None = None
    open_entries: list[tuple[pd.Timestamp, float, float]] = []  # (ts, price, margin)

    def _flush(exit_time: pd.Timestamp, exit_price: float, pnl: float):
        nonlocal open_side, open_time, open_entries
        if not open_entries or open_side is None:
            open_side = None
            open_time = None
            open_entries = []
            return
        total_margin = sum(e[2] for e in open_entries) or 1.0
        avg_price = sum(e[1] * e[2] for e in open_entries) / total_margin
        spans.append(PositionSpan(
            side=open_side,
            entry_time=open_time or open_entries[0][0],
            exit_time=exit_time,
            entry_price=avg_price,
            exit_price=exit_price,
            pnl=pnl,
        ))
        open_side = None
        open_time = None
        open_entries = []

    for r in records:
        ts = pd.to_datetime(r.timestamp) if isinstance(r.timestamp, str) else r.timestamp
        action = r.action
        if action in ("entry", "add"):
            if open_side is None:
                open_side = r.side
                open_time = ts
            open_entries.append((ts, float(r.price), float(r.margin) or 1.0))
        elif action in ("exit", "stop_loss"):
            _flush(ts, float(r.price), float(getattr(r, "pnl", 0.0)))

    # 미청산 포지션도 구간으로 포함 (exit_time=None)
    if open_side is not None and open_entries:
        total_margin = sum(e[2] for e in open_entries) or 1.0
        avg_price = sum(e[1] * e[2] for e in open_entries) / total_margin
        spans.append(PositionSpan(
            side=open_side,
            entry_time=open_time or open_entries[0][0],
            exit_time=None,
            entry_price=avg_price,
            exit_price=None,
            pnl=None,
        ))

    return spans


def trades_df_to_position_spans(trades_df: pd.DataFrame) -> list[PositionSpan]:
    """DB의 trades 테이블(DataFrame)에서 포지션 구간을 추출한다.

    컬럼: datetime, side, action, price, margin, pnl
    """
    if trades_df is None or trades_df.empty:
        return []

    spans: list[PositionSpan] = []
    open_side: str | None = None
    open_time: pd.Timestamp | None = None
    open_entries: list[tuple[pd.Timestamp, float, float]] = []

    def _flush(exit_time, exit_price, pnl):
        nonlocal open_side, open_time, open_entries
        if not open_entries or open_side is None:
            open_side = None
            open_time = None
            open_entries = []
            return
        total_margin = sum(e[2] for e in open_entries) or 1.0
        avg_price = sum(e[1] * e[2] for e in open_entries) / total_margin
        spans.append(PositionSpan(
            side=open_side,
            entry_time=open_time or open_entries[0][0],
            exit_time=exit_time,
            entry_price=avg_price,
            exit_price=exit_price,
            pnl=pnl,
        ))
        open_side = None
        open_time = None
        open_entries = []

    for _, r in trades_df.iterrows():
        ts_raw = r.get("datetime")
        ts = pd.to_datetime(str(ts_raw).replace("+09:00", "")) if ts_raw is not None else pd.NaT
        action = str(r.get("action", "")).lower()
        side = str(r.get("side", ""))
        price = float(r.get("price", 0) or 0)
        margin = float(r.get("margin", 0) or 0) or (float(r.get("amount", 0) or 0) / max(int(r.get("leverage", 1) or 1), 1))
        pnl = float(r.get("pnl", 0) or 0)

        if action in ("entry", "add"):
            if open_side is None:
                open_side = side
                open_time = ts
            open_entries.append((ts, price, margin or 1.0))
        elif action in ("exit", "stop_loss", "stop"):
            _flush(ts, price, pnl)

    if open_side is not None and open_entries:
        total_margin = sum(e[2] for e in open_entries) or 1.0
        avg_price = sum(e[1] * e[2] for e in open_entries) / total_margin
        spans.append(PositionSpan(
            side=open_side,
            entry_time=open_time or open_entries[0][0],
            exit_time=None,
            entry_price=avg_price,
            exit_price=None,
            pnl=None,
        ))

    return spans


def trades_df_to_signals(trades_df: pd.DataFrame) -> list[Signal]:
    """DB trades 테이블(DataFrame)에서 Signal 리스트를 재구성한다.

    차트 마커 표시 목적이므로 필수 필드만 채운다.
    """
    if trades_df is None or trades_df.empty:
        return []

    sigs: list[Signal] = []
    for _, r in trades_df.iterrows():
        ts_raw = r.get("datetime")
        ts = pd.to_datetime(str(ts_raw).replace("+09:00", "")) if ts_raw is not None else pd.NaT
        action = str(r.get("action", "")).lower()
        side = str(r.get("side", ""))
        price = float(r.get("price", 0) or 0)
        leverage = int(r.get("leverage", 1) or 1)
        entry_step = int(r.get("entry_step", 0) or 0)
        reason = str(r.get("reason", "") or "")

        if action in ("entry", "add"):
            st = SignalType.LONG_ENTRY if side == "long" else SignalType.SHORT_ENTRY
        elif action == "exit":
            st = SignalType.LONG_EXIT if side == "long" else SignalType.SHORT_EXIT
        elif action in ("stop_loss", "stop"):
            st = SignalType.STOP_LOSS
        elif action == "take_profit":
            st = SignalType.TAKE_PROFIT
        else:
            continue

        sigs.append(Signal(
            timestamp=ts, signal_type=st, price=price,
            leverage=leverage, entry_step=entry_step, reason=reason,
        ))
    return sigs
