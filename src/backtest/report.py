"""백테스트 리포트 생성.

텍스트 리포트 + HTML 대시보드를 생성한다.
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from src.utils.logger import setup_logger
from src.utils.timeframe import KST
from .engine import Trade
from .evaluator import BacktestMetrics

logger = setup_logger("hantrader.backtest")


class BacktestReport:
    """백테스트 리포트 생성기."""

    def __init__(self, output_dir: str = "data/backtest"):
        self._base_dir = Path(output_dir)
        self._date_str = datetime.now(KST).strftime("%Y%m%d")
        self._time_str = datetime.now(KST).strftime("%H%M%S")
        # output_dir은 _get_output_dir()에서 심볼별로 결정
        self.output_dir = self._base_dir  # 기본값 (하위호환)

    # ------------------------------------------------------------------
    # 국면별/방향별 분석 통계
    # ------------------------------------------------------------------

    @staticmethod
    def _analyze_regime_stats(trades: list[Trade]) -> dict:
        """거래 내역을 국면(횡보/추세)×방향(Long/Short)으로 분류하고 통계를 계산한다.

        Returns:
            dict with keys: "sideways_long", "sideways_short", "trend_long", "trend_short",
                            "sideways", "trend", "long", "short"
            각 값은 dict: count, wins, losses, total_pnl, avg_pnl, win_rate, pnl_list
        """
        # 포지션별로 그룹핑 (첫 진입 기준으로 국면/방향 판단)
        positions: dict[int, list[Trade]] = {}
        for t in trades:
            positions.setdefault(t.position_id, []).append(t)

        categories = {
            "sideways_long": [], "sideways_short": [],
            "trend_long": [], "trend_short": [],
        }

        for pos_id, pos_trades in positions.items():
            first = pos_trades[0]
            total_pnl = sum(t.pnl for t in pos_trades)
            total_margin = sum(t.position_size for t in pos_trades)
            pnl_pct = pos_trades[-1].pnl_pct

            # 국면 판단: 첫 진입 사유 기준
            reason = first.entry_reason or ""
            if reason.startswith("횡보"):
                regime = "sideways"
            elif reason.startswith("추세"):
                regime = "trend"
            else:
                # entry_metadata fallback
                meta_regime = first.entry_metadata.get("regime", "")
                regime = "trend" if "trend" in meta_regime else "sideways"

            direction = first.side  # "long" or "short"
            key = f"{regime}_{direction}"
            categories[key].append({
                "pos_id": pos_id,
                "pnl": total_pnl,
                "pnl_pct": pnl_pct,
                "margin": total_margin,
                "entries": len(pos_trades),
            })

        def _calc_stats(items: list[dict]) -> dict:
            if not items:
                return {
                    "count": 0, "wins": 0, "losses": 0,
                    "total_pnl": 0.0, "avg_pnl": 0.0,
                    "win_rate": 0.0, "avg_pnl_pct": 0.0,
                    "best_pnl": 0.0, "worst_pnl": 0.0,
                }
            pnls = [x["pnl"] for x in items]
            pnl_pcts = [x["pnl_pct"] for x in items]
            wins = sum(1 for p in pnls if p > 0)
            losses = sum(1 for p in pnls if p < 0)
            return {
                "count": len(items),
                "wins": wins,
                "losses": losses,
                "total_pnl": sum(pnls),
                "avg_pnl": sum(pnls) / len(pnls),
                "win_rate": wins / len(pnls) if pnls else 0.0,
                "avg_pnl_pct": sum(pnl_pcts) / len(pnl_pcts) if pnl_pcts else 0.0,
                "best_pnl": max(pnls),
                "worst_pnl": min(pnls),
            }

        result = {}
        for key, items in categories.items():
            result[key] = _calc_stats(items)

        # 국면별 합산
        for regime in ("sideways", "trend"):
            combined = categories[f"{regime}_long"] + categories[f"{regime}_short"]
            result[regime] = _calc_stats(combined)

        # 방향별 합산
        for direction in ("long", "short"):
            combined = categories[f"sideways_{direction}"] + categories[f"trend_{direction}"]
            result[direction] = _calc_stats(combined)

        return result

    def _get_output_dir(self, symbol: str) -> Path:
        """날짜/심볼 하위 폴더를 생성하고 반환한다."""
        safe_symbol = symbol.replace("/", "_")
        out = self._base_dir / self._date_str / safe_symbol
        out.mkdir(parents=True, exist_ok=True)
        return out

    # ------------------------------------------------------------------
    # 텍스트 리포트
    # ------------------------------------------------------------------

    def generate_text(
        self,
        metrics: BacktestMetrics,
        trades: list[Trade],
        exchange: str,
        symbol: str,
        timeframe: str,
        strategy_config=None,
        backtest_config=None,
    ) -> str:
        """텍스트 리포트를 생성한다."""
        lines = []
        sep = "=" * 80

        lines.append(sep)
        lines.append(f"  백테스트 리포트: {exchange}/{symbol} ({timeframe})")
        lines.append(sep)

        # --- 전략 설정 ---
        if strategy_config is not None:
            lines.append("")
            lines.append("[ 전략 설정 ]")
            lines.append(f"  전략:           {strategy_config.name}")
            lines.append(f"  BB:             period={strategy_config.bb_period}, std={strategy_config.bb_std}")
            lines.append(f"  국면 판단:      window={strategy_config.regime_window}, threshold={strategy_config.regime_threshold}")
            lines.append(f"  ADX 진입차단:   {strategy_config.adx_entry_block} (lookback={strategy_config.adx_rise_lookback})")
            lines.append(f"  추세 손절/익절: {strategy_config.stoploss_pct:.1%} / {strategy_config.takeprofit_pct:.1%}")
            lines.append(f"  트레일링:       start={strategy_config.trailing_start_pct:.1%}, stop={strategy_config.trailing_stop_pct:.1%}")
            if strategy_config.name == "bb_mtf":
                lines.append(f"  MTF 가중치:     upper={strategy_config.mtf_weight_upper}, lower={strategy_config.mtf_weight_lower}, threshold={strategy_config.mtf_trend_threshold}")
        if backtest_config is not None:
            lines.append(f"  레버리지:       {backtest_config.leverage_min}~{backtest_config.leverage_max}x (횡보≤{backtest_config.sideways_leverage_max}x)")
            if backtest_config.margin_pct > 0:
                lines.append(f"  마진:           자본의 {backtest_config.margin_pct:.0%}")
            else:
                lines.append(f"  마진:           고정 {backtest_config.max_margin_per_entry} USDT")

        # --- 요약 ---
        lines.append("")
        lines.append("[ 요약 ]")
        lines.append(f"  시작 금액:    {metrics.initial_capital:>15,.2f} USDT")
        lines.append(f"  최종 금액:    {metrics.final_capital:>15,.2f} USDT")
        lines.append(f"  손익 금액:    {metrics.total_pnl:>+15,.2f} USDT")
        lines.append(f"  총 수익률:    {metrics.total_return_pct:>+15.2%}")

        # --- 평가 지표 ---
        lines.append("")
        lines.append("[ 평가 지표 ]")
        lines.append(f"  Sharpe Ratio:   {metrics.sharpe_ratio:>10.3f}   (위험 대비 수익. 1↑ 양호, 2↑ 우수)")
        lines.append(f"  Max Drawdown:   {metrics.max_drawdown_pct:>10.2%}   (고점 대비 최대 하락. 작을수록 좋음)")
        lines.append(f"  Win Rate:       {metrics.win_rate:>10.2%}   (수익 거래 비율)")
        lines.append(f"  Profit Factor:  {metrics.profit_factor:>10.3f}   (총수익/총손실. 1↑ 수익, 2↑ 우수)")

        # --- 거래 통계 ---
        lines.append("")
        lines.append("[ 거래 통계 ]")
        lines.append(f"  총 거래 수:     {metrics.total_trades:>10d}")
        lines.append(f"  수익 거래:      {metrics.winning_trades:>10d}")
        lines.append(f"  손실 거래:      {metrics.losing_trades:>10d}")
        lines.append(f"  평균 수익:    {metrics.avg_win:>+12,.2f} USDT")
        lines.append(f"  평균 손실:    {metrics.avg_loss:>+12,.2f} USDT")
        lines.append(f"  최대 수익:    {metrics.largest_win:>+12,.2f} USDT")
        lines.append(f"  최대 손실:    {metrics.largest_loss:>+12,.2f} USDT")
        lines.append(f"  평균 거래 손익: {metrics.avg_trade_pnl:>+10,.2f} USDT")

        # --- 월별 수익 ---
        if metrics.monthly_returns is not None and not metrics.monthly_returns.empty:
            lines.append("")
            lines.append("[ 월별 수익률 ]")
            for dt, ret in metrics.monthly_returns.items():
                month_str = dt.strftime("%Y-%m")
                lines.append(f"  {month_str}:  {ret:>+8.2%}")

        # --- 거래 내역 (포지션 단위 그룹핑) ---
        lines.append("")
        lines.append("[ 거래 내역 ]")

        # 포지션별로 그룹핑
        positions: dict[int, list[Trade]] = {}
        for t in trades:
            positions.setdefault(t.position_id, []).append(t)

        for pos_id, pos_trades in positions.items():
            first = pos_trades[0]
            last = pos_trades[-1]
            total_margin = sum(t.position_size for t in pos_trades)
            total_qty = sum(t.quantity for t in pos_trades)
            total_pnl = sum(t.pnl for t in pos_trades)
            num_entries = len(pos_trades)

            # 포지션 시간 (진입 ~ 청산)
            entry_ts = first.entry_time.strftime("%Y-%m-%d %H:%M") if first.entry_time else ""
            exit_ts = last.exit_time.strftime("%Y-%m-%d %H:%M") if last.exit_time else ""

            lines.append(f"  ══ 포지션 #{pos_id} ({first.side}) {'═'*48}")
            lines.append(f"    기간: {entry_ts} → {exit_ts}")
            lines.append(f"    총 마진: {total_margin:,.2f} USDT  총 수량: {total_qty:.6f}  "
                         f"물타기: {num_entries}회  레버: {first.leverage}x")
            lines.append(f"    총 손익: {total_pnl:>+,.2f} USDT ({last.pnl_pct:>+.2%})")

            # 각 진입 내역
            for t in pos_trades:
                entry_meta = self._format_entry_meta(t)
                t_entry_ts = t.entry_time.strftime("%m-%d %H:%M") if t.entry_time else ""
                lines.append(f"    ── 진입 {t.entry_step}차 ({t_entry_ts}) ──")
                lines.append(f"      가격: {t.entry_price:>12,.2f}  수량: {t.quantity:.6f}  "
                             f"마진: {t.position_size:,.2f} USDT")
                lines.append(f"      [{entry_meta}]")
                lines.append(f"      사유: {t.entry_reason}")

            # 청산 정보 (공통)
            exit_meta = self._format_exit_meta(last)
            exit_ts_short = last.exit_time.strftime("%m-%d %H:%M") if last.exit_time else ""
            lines.append(f"    ── 청산 ({exit_ts_short}) ──")
            lines.append(f"      가격: {last.exit_price:>12,.2f}  "
                         f"손익: {total_pnl:>+,.2f} USDT ({last.pnl_pct:>+.2%})")
            lines.append(f"      [{exit_meta}]")
            lines.append(f"      사유: {last.exit_reason}")

        # --- 국면별 분석 ---
        regime_stats = self._analyze_regime_stats(trades)
        lines.append("")
        lines.append("[ 국면별 분석 ]")

        def _regime_line(label: str, s: dict) -> list[str]:
            """국면별 통계 한 블록을 문자열 리스트로 반환한다."""
            if s["count"] == 0:
                return [f"  {label}: 거래 없음"]
            result_lines = [
                f"  {label}:",
                f"    거래:  {s['count']}건 (승 {s['wins']} / 패 {s['losses']})",
                f"    승률:  {s['win_rate']:.1%}",
                f"    손익:  {s['total_pnl']:>+,.2f} USDT (평균 {s['avg_pnl']:>+,.2f})",
                f"    수익률: 평균 {s['avg_pnl_pct']:>+.2%}  "
                f"(최고 {s['best_pnl']:>+,.2f} / 최저 {s['worst_pnl']:>+,.2f})",
            ]
            return result_lines

        lines.extend(_regime_line("횡보장 전체", regime_stats["sideways"]))
        lines.extend(_regime_line("  ├ 횡보 Long", regime_stats["sideways_long"]))
        lines.extend(_regime_line("  └ 횡보 Short", regime_stats["sideways_short"]))
        lines.append("")
        lines.extend(_regime_line("추세장 전체", regime_stats["trend"]))
        lines.extend(_regime_line("  ├ 추세 Long", regime_stats["trend_long"]))
        lines.extend(_regime_line("  └ 추세 Short", regime_stats["trend_short"]))

        # 방향별 요약
        lines.append("")
        lines.append("[ 방향별 분석 ]")
        lines.extend(_regime_line("Long 전체", regime_stats["long"]))
        lines.extend(_regime_line("Short 전체", regime_stats["short"]))

        # --- 전략 분석 ---
        lines.append("")
        lines.append("[ 전략 분석 ]")
        if metrics.total_return_pct > 0:
            lines.append(f"  수익성: 양호 (총 수익률 {metrics.total_return_pct:+.2%})")
        else:
            lines.append(f"  수익성: 미흡 (총 수익률 {metrics.total_return_pct:+.2%})")

        if metrics.sharpe_ratio >= 2:
            lines.append("  위험조정수익: 우수 (Sharpe >= 2)")
        elif metrics.sharpe_ratio >= 1:
            lines.append("  위험조정수익: 양호 (Sharpe >= 1)")
        else:
            lines.append(f"  위험조정수익: 개선 필요 (Sharpe = {metrics.sharpe_ratio:.3f})")

        if abs(metrics.max_drawdown_pct) > 0.20:
            lines.append(f"  리스크: MDD {metrics.max_drawdown_pct:.2%} → 낙폭 관리 개선 필요")
        else:
            lines.append(f"  리스크: MDD {metrics.max_drawdown_pct:.2%} → 양호")

        if metrics.profit_factor >= 2:
            lines.append("  수익/손실 비율: 우수 (PF >= 2)")
        elif metrics.profit_factor >= 1:
            lines.append("  수익/손실 비율: 양호 (PF >= 1)")
        else:
            lines.append(f"  수익/손실 비율: 개선 필요 (PF = {metrics.profit_factor:.3f})")

        lines.append(sep)
        return "\n".join(lines)

    @staticmethod
    def _format_entry_meta(t: Trade) -> str:
        """진입 시 지표 메타데이터를 문자열로 포맷한다."""
        if not t.entry_metadata:
            return ""
        parts = []
        if "bbp" in t.entry_metadata:
            parts.append(f"BB%={t.entry_metadata['bbp']:.2%}")
        if "bb_width" in t.entry_metadata:
            parts.append(f"BBW={t.entry_metadata['bb_width']:.4f}")
        if "rsi" in t.entry_metadata:
            parts.append(f"RSI={t.entry_metadata['rsi']:.1f}")
        if "adx" in t.entry_metadata:
            parts.append(f"ADX={t.entry_metadata['adx']:.1f}")
        if "regime" in t.entry_metadata:
            parts.append(f"국면={t.entry_metadata['regime']}")
        return " | ".join(parts)

    @staticmethod
    def _format_exit_meta(t: Trade) -> str:
        """청산 시 지표 메타데이터를 문자열로 포맷한다."""
        if not t.exit_metadata:
            return ""
        parts = []
        if "bbp" in t.exit_metadata:
            parts.append(f"BB%={t.exit_metadata['bbp']:.2%}")
        if "rsi" in t.exit_metadata:
            parts.append(f"RSI={t.exit_metadata['rsi']:.1f}")
        if "adx" in t.exit_metadata:
            parts.append(f"ADX={t.exit_metadata['adx']:.1f}")
        if "regime" in t.exit_metadata:
            parts.append(f"국면={t.exit_metadata['regime']}")
        return " | ".join(parts)

    # ------------------------------------------------------------------
    # 전략 설정 HTML
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_strategy_html(strategy_config, backtest_config) -> str:
        """전략 설정 정보 HTML 블록을 생성한다."""
        if strategy_config is None:
            return ""
        items = [
            ("전략", strategy_config.name),
            ("BB", f"period={strategy_config.bb_period}, std={strategy_config.bb_std}"),
            ("국면 판단", f"window={strategy_config.regime_window}, threshold={strategy_config.regime_threshold}"),
            ("ADX 차단", f"{strategy_config.adx_entry_block} (lookback={strategy_config.adx_rise_lookback})"),
            ("추세 손절/익절", f"{strategy_config.stoploss_pct:.1%} / {strategy_config.takeprofit_pct:.1%}"),
            ("트레일링", f"start={strategy_config.trailing_start_pct:.1%}, stop={strategy_config.trailing_stop_pct:.1%}"),
        ]
        if strategy_config.name == "bb_mtf":
            items.append(("MTF 가중치", f"upper={strategy_config.mtf_weight_upper}, lower={strategy_config.mtf_weight_lower}, threshold={strategy_config.mtf_trend_threshold}"))
        if backtest_config is not None:
            items.append(("레버리지", f"{backtest_config.leverage_min}~{backtest_config.leverage_max}x (횡보≤{backtest_config.sideways_leverage_max}x)"))
            if backtest_config.margin_pct > 0:
                items.append(("마진", f"자본의 {backtest_config.margin_pct:.0%}"))
            else:
                items.append(("마진", f"고정 {backtest_config.max_margin_per_entry} USDT"))

        cells = "".join(
            f'<div class="card"><div class="label">{label}</div><div class="value" style="font-size:14px;">{value}</div></div>'
            for label, value in items
        )
        return f'<div style="background:#1e293b;border-radius:12px;padding:16px;margin-bottom:24px;"><h3 style="margin-bottom:12px;color:#38bdf8;">전략 설정</h3><div class="grid" style="grid-template-columns:repeat(4,1fr);">{cells}</div></div>'

    # ------------------------------------------------------------------
    # 국면별 분석 HTML
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_regime_html(trades: list[Trade]) -> str:
        """국면별/방향별 분석 HTML 블록을 생성한다."""
        stats = BacktestReport._analyze_regime_stats(trades)

        def _stat_row(label: str, s: dict, color: str) -> str:
            if s["count"] == 0:
                return f'<tr><td style="color:{color};font-weight:bold;">{label}</td>' + '<td colspan="5" style="color:#64748b;">거래 없음</td></tr>'
            win_color = "#22c55e" if s["win_rate"] >= 0.5 else "#ef4444"
            pnl_color = "#22c55e" if s["total_pnl"] >= 0 else "#ef4444"
            return (
                f'<tr>'
                f'<td style="color:{color};font-weight:bold;">{label}</td>'
                f'<td>{s["count"]}건</td>'
                f'<td style="color:{win_color}">{s["win_rate"]:.1%} ({s["wins"]}승/{s["losses"]}패)</td>'
                f'<td style="color:{pnl_color}">{s["total_pnl"]:+,.2f}</td>'
                f'<td style="color:{pnl_color}">{s["avg_pnl"]:+,.2f}</td>'
                f'<td style="color:{pnl_color}">{s["avg_pnl_pct"]:+.2%}</td>'
                f'</tr>'
            )

        rows = ""
        rows += _stat_row("횡보장 전체", stats["sideways"], "#38bdf8")
        rows += _stat_row("  횡보 Long", stats["sideways_long"], "#60a5fa")
        rows += _stat_row("  횡보 Short", stats["sideways_short"], "#60a5fa")
        rows += '<tr><td colspan="6" style="border:0;height:8px;"></td></tr>'
        rows += _stat_row("추세장 전체", stats["trend"], "#f59e0b")
        rows += _stat_row("  추세 Long", stats["trend_long"], "#fbbf24")
        rows += _stat_row("  추세 Short", stats["trend_short"], "#fbbf24")
        rows += '<tr><td colspan="6" style="border:0;height:8px;"></td></tr>'
        rows += _stat_row("Long 전체", stats["long"], "#22c55e")
        rows += _stat_row("Short 전체", stats["short"], "#ef4444")

        return f"""<div style="background:#1e293b;border-radius:12px;padding:20px;margin-bottom:24px;">
<h3 style="margin-bottom:12px;color:#38bdf8;">국면별 / 방향별 분석</h3>
<table style="width:100%;border-collapse:collapse;font-size:14px;">
<thead><tr style="border-bottom:2px solid #475569;">
<th style="text-align:left;padding:8px;">구분</th>
<th style="padding:8px;">거래수</th>
<th style="padding:8px;">승률</th>
<th style="padding:8px;">총 손익 (USDT)</th>
<th style="padding:8px;">평균 손익 (USDT)</th>
<th style="padding:8px;">평균 수익률</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>
</div>"""

    # ------------------------------------------------------------------
    # HTML 대시보드
    # ------------------------------------------------------------------

    def generate_dashboard(
        self,
        metrics: BacktestMetrics,
        trades: list[Trade],
        equity_df: pd.DataFrame,
        exchange: str,
        symbol: str,
        timeframe: str,
        strategy_config=None,
        backtest_config=None,
    ) -> Path:
        """HTML 대시보드를 생성한다."""
        out = self._get_output_dir(symbol)
        filepath = out / f"dashboard_{timeframe}_{self._time_str}.html"

        equity_labels = ""
        equity_data = ""
        if not equity_df.empty:
            sampled = equity_df.iloc[::max(1, len(equity_df) // 200)]
            equity_labels = ",".join(f'"{ts.strftime("%Y-%m-%d %H:%M")}"' for ts in sampled.index)
            equity_data = ",".join(f"{v:.2f}" for v in sampled["equity"])

        monthly_labels = ""
        monthly_data = ""
        monthly_colors = ""
        if metrics.monthly_returns is not None and not metrics.monthly_returns.empty:
            monthly_labels = ",".join(f'"{dt.strftime("%Y-%m")}"' for dt in metrics.monthly_returns.index)
            monthly_data = ",".join(f"{v*100:.2f}" for v in metrics.monthly_returns.values)
            monthly_colors = ",".join(
                f'"{"#22c55e" if v >= 0 else "#ef4444"}"' for v in metrics.monthly_returns.values
            )

        trades_rows = ""
        for t in trades:
            pnl_class = "win" if t.pnl > 0 else "lose"
            e_bbp = f"{t.entry_bbp:.2%}" if t.entry_bbp else "-"
            x_bbp = f"{t.exit_bbp:.2%}" if t.exit_bbp else "-"
            e_rsi = f"{t.entry_metadata.get('rsi', 0):.1f}" if t.entry_metadata.get("rsi") else "-"
            x_rsi = f"{t.exit_metadata.get('rsi', 0):.1f}" if t.exit_metadata.get("rsi") else "-"
            trades_rows += f"""<tr class="{pnl_class}">
                <td>{t.position_id}</td><td>{t.trade_id}</td><td>{t.side}</td>
                <td>{t.entry_time.strftime("%Y-%m-%d %H:%M") if t.entry_time else ""}</td>
                <td>{t.entry_price:,.2f}</td><td>{t.quantity:.6f}</td><td>{t.position_size:,.2f}</td>
                <td>{e_bbp}</td><td>{e_rsi}</td>
                <td>{t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else ""}</td>
                <td>{t.exit_price:,.2f}</td><td>{x_bbp}</td><td>{x_rsi}</td>
                <td>{t.leverage}x</td><td>{t.pnl:+,.2f} USDT</td><td>{t.pnl_pct:+.2%}</td>
                <td class="reason">{t.entry_reason}</td><td class="reason">{t.exit_reason}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>백테스트 대시보드 - {exchange}/{symbol}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:'Segoe UI',sans-serif; background:#0f172a; color:#e2e8f0; padding:20px; }}
    h1 {{ text-align:center; margin-bottom:20px; color:#38bdf8; }}
    .grid {{ display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-bottom:24px; }}
    .card {{ background:#1e293b; border-radius:12px; padding:16px; text-align:center; }}
    .card .label {{ font-size:12px; color:#94a3b8; margin-bottom:4px; }}
    .card .value {{ font-size:22px; font-weight:bold; }}
    .card .desc {{ font-size:10px; color:#64748b; margin-top:4px; }}
    .positive {{ color:#22c55e; }}
    .negative {{ color:#ef4444; }}
    .chart-container {{ background:#1e293b; border-radius:12px; padding:20px; margin-bottom:24px; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th {{ background:#334155; padding:8px; text-align:left; position:sticky; top:0; }}
    td {{ padding:6px 8px; border-bottom:1px solid #334155; }}
    tr.win td {{ background:#052e16; }}
    tr.lose td {{ background:#450a0a; }}
    .reason {{ max-width:200px; font-size:11px; color:#94a3b8; }}
    .table-wrap {{ background:#1e293b; border-radius:12px; padding:20px; max-height:500px; overflow-y:auto; }}
</style>
</head>
<body>
<h1>백테스트 대시보드: {exchange}/{symbol} ({timeframe})</h1>

{self._generate_strategy_html(strategy_config, backtest_config)}

<div class="grid">
    <div class="card">
        <div class="label">시작 금액</div>
        <div class="value">{metrics.initial_capital:,.0f}</div>
    </div>
    <div class="card">
        <div class="label">최종 금액</div>
        <div class="value {'positive' if metrics.total_pnl >= 0 else 'negative'}">{metrics.final_capital:,.0f}</div>
    </div>
    <div class="card">
        <div class="label">총 수익률</div>
        <div class="value {'positive' if metrics.total_return_pct >= 0 else 'negative'}">{metrics.total_return_pct:+.2%}</div>
        <div class="desc">Total Return</div>
    </div>
    <div class="card">
        <div class="label">Sharpe Ratio</div>
        <div class="value">{metrics.sharpe_ratio:.3f}</div>
        <div class="desc">위험 대비 수익 (1↑양호, 2↑우수)</div>
    </div>
    <div class="card">
        <div class="label">Max Drawdown</div>
        <div class="value negative">{metrics.max_drawdown_pct:.2%}</div>
        <div class="desc">고점 대비 최대 하락</div>
    </div>
</div>

<div class="grid">
    <div class="card">
        <div class="label">Win Rate</div>
        <div class="value">{metrics.win_rate:.1%}</div>
        <div class="desc">승률</div>
    </div>
    <div class="card">
        <div class="label">Profit Factor</div>
        <div class="value">{metrics.profit_factor:.3f}</div>
        <div class="desc">총수익/총손실 (1↑수익)</div>
    </div>
    <div class="card">
        <div class="label">총 거래</div>
        <div class="value">{metrics.total_trades}</div>
        <div class="desc">승 {metrics.winning_trades} / 패 {metrics.losing_trades}</div>
    </div>
    <div class="card">
        <div class="label">평균 거래 손익</div>
        <div class="value {'positive' if metrics.avg_trade_pnl >= 0 else 'negative'}">{metrics.avg_trade_pnl:+,.2f}</div>
    </div>
    <div class="card">
        <div class="label">손익 금액</div>
        <div class="value {'positive' if metrics.total_pnl >= 0 else 'negative'}">{metrics.total_pnl:+,.0f}</div>
    </div>
</div>

<div class="chart-container">
    <canvas id="equityChart" height="80"></canvas>
</div>

<div class="chart-container">
    <canvas id="monthlyChart" height="60"></canvas>
</div>

{self._generate_regime_html(trades)}

<div class="table-wrap">
    <h3 style="margin-bottom:12px;">거래 내역</h3>
    <table>
        <thead>
            <tr><th>포지션</th><th>ID</th><th>방향</th>
            <th>진입시간</th><th>진입가</th><th>수량</th><th>마진</th><th>진입BB%</th><th>진입RSI</th>
            <th>청산시간</th><th>청산가</th><th>청산BB%</th><th>청산RSI</th>
            <th>레버</th><th>손익(USDT)</th><th>수익률</th>
            <th>진입사유</th><th>청산사유</th></tr>
        </thead>
        <tbody>{trades_rows}</tbody>
    </table>
</div>

<script>
new Chart(document.getElementById('equityChart'), {{
    type: 'line',
    data: {{
        labels: [{equity_labels}],
        datasets: [{{
            label: 'Equity Curve',
            data: [{equity_data}],
            borderColor: '#38bdf8',
            backgroundColor: 'rgba(56,189,248,0.1)',
            fill: true,
            pointRadius: 0,
            tension: 0.3
        }}]
    }},
    options: {{
        plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }},
        scales: {{
            x: {{ ticks: {{ color: '#64748b', maxTicksLimit: 12 }} }},
            y: {{ ticks: {{ color: '#64748b' }} }}
        }}
    }}
}});

new Chart(document.getElementById('monthlyChart'), {{
    type: 'bar',
    data: {{
        labels: [{monthly_labels}],
        datasets: [{{
            label: '월별 수익률 (%)',
            data: [{monthly_data}],
            backgroundColor: [{monthly_colors}]
        }}]
    }},
    options: {{
        plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }},
        scales: {{
            x: {{ ticks: {{ color: '#64748b' }} }},
            y: {{ ticks: {{ color: '#64748b' }} }}
        }}
    }}
}});
</script>
</body>
</html>"""

        filepath.write_text(html, encoding="utf-8")
        logger.info(f"대시보드 생성: {filepath}")
        return filepath

    # ------------------------------------------------------------------
    # 저장
    # ------------------------------------------------------------------

    def save_text(
        self, text: str, exchange: str, symbol: str, timeframe: str,
    ) -> Path:
        """텍스트 리포트를 파일로 저장한다."""
        out = self._get_output_dir(symbol)
        filepath = out / f"report_{timeframe}_{self._time_str}.txt"
        filepath.write_text(text, encoding="utf-8")
        logger.info(f"텍스트 리포트 저장: {filepath}")
        return filepath

    def save_trades_csv(
        self, trades_df: pd.DataFrame, exchange: str, symbol: str, timeframe: str,
    ) -> Path:
        """거래 내역 CSV를 저장한다."""
        out = self._get_output_dir(symbol)
        filepath = out / f"trades_{timeframe}_{self._time_str}.csv"
        trades_df.to_csv(filepath, index=False)
        logger.info(f"거래 내역 CSV 저장: {filepath}")
        return filepath
