from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tradesys.agents.utils.agent_states import AgentState
else:
    AgentState = dict[str, Any]


DATA_ROOT = Path(__file__).resolve().parents[1] / "data_portfolio"
STOCK_ROOT = DATA_ROOT / "stock_data"
NEWS_ROOT = DATA_ROOT / "news_data"
ECONOMIC_ROOT = DATA_ROOT / "economic_data"


def create_local_research_state(
    ticker: str,
    trade_date: str,
    max_position_pct: float = 100.0,
) -> AgentState:
    """Build a deterministic evidence state so experiments do not require an API key."""
    signal = technical_signal_snapshot(ticker, trade_date)
    evidence = {
        "technical": signal,
        "fundamental": fundamental_snapshot(ticker, trade_date),
        "news": news_snapshot(ticker, trade_date),
        "policy": policy_snapshot(trade_date),
    }
    return {
        "messages": [],
        "technical_messages": [],
        "fundamental_messages": [],
        "news_messages": [],
        "policy_messages": [],
        "ticker": ticker,
        "trade_date": trade_date,
        "max_position_pct": _bounded_pct(max_position_pct, 100.0),
        "technical_report": render_technical_report(signal),
        "fundamental_report": render_fundamental_report(evidence["fundamental"]),
        "news_report": render_news_report(evidence["news"]),
        "policy_report": render_policy_report(evidence["policy"]),
        "analyst_reports": [],
        "errors": [],
        "error": None,
        "workflow_mode": "",
        "team_plan": {},
        "generated_skills": [],
        "expert_agents": [],
        "expert_outputs": [],
        "module_outputs": {},
        "team_discussion_summary": "",
        "team_summary": {},
        "final_decision_structured": {},
        "final_decision": "",
        "local_evidence": evidence,
        "workflow_plan": {},
        "workflow_outputs": {},
        "workflow_status": "not_started",
    }


def ensure_local_evidence(state: AgentState) -> AgentState:
    if state.get("local_evidence"):
        return state
    ticker = str(state.get("ticker", "")).upper()
    trade_date = str(state.get("trade_date", ""))
    max_position_pct = _bounded_pct(state.get("max_position_pct"), 100.0)
    local_state = create_local_research_state(ticker, trade_date, max_position_pct)
    merged = dict(local_state)
    merged.update({key: value for key, value in state.items() if value not in ("", None, [], {})})
    merged["local_evidence"] = local_state["local_evidence"]
    for key in ("technical_report", "fundamental_report", "news_report", "policy_report"):
        if not state.get(key):
            merged[key] = local_state[key]
    return merged


def technical_signal_snapshot(ticker: str, trade_date: str) -> dict[str, Any]:
    prices = _read_csv_rows(STOCK_ROOT / ticker / "daily_prices.csv")
    indicators = {row["date"]: row for row in _read_csv_rows(STOCK_ROOT / ticker / "technical_indicators.csv")}
    rows = [row for row in prices if row.get("date", "") <= trade_date]
    if not rows:
        raise ValueError(f"No price rows for {ticker} on or before {trade_date}")

    row = rows[-1]
    indicator = indicators.get(row["date"], {})
    closes10 = [_float(item.get("adjusted_close")) for item in rows[-10:]]
    closes20 = [_float(item.get("adjusted_close")) for item in rows[-20:]]
    closes60 = [_float(item.get("adjusted_close")) for item in rows[-60:]]
    ma10 = sum(closes10) / len(closes10)
    ma20 = sum(closes20) / len(closes20)
    low20 = min(closes20)
    high60 = max(closes60)
    adjusted_close = _float(row.get("adjusted_close"))
    previous_close = _float(rows[-2].get("adjusted_close")) if len(rows) >= 2 else adjusted_close
    daily_return_pct = (adjusted_close / previous_close - 1.0) * 100.0 if previous_close else 0.0
    rsi = _float_or_none(indicator.get("rsi"))
    stoch_k = _float_or_none(indicator.get("stoch_k"))
    macd_histogram = _float(indicator.get("macd_histogram"), default=0.0)
    atr = _float(indicator.get("atr"), default=0.0)
    from_low20_pct = (adjusted_close / low20 - 1.0) * 100.0 if low20 else 0.0
    drawdown60_pct = (adjusted_close / high60 - 1.0) * 100.0 if high60 else 0.0
    volatility_pct = atr / adjusted_close * 100.0 if adjusted_close else 0.0

    repair_mode = drawdown60_pct <= -15.0
    if repair_mode:
        mode = "drawdown_repair"
        buy_signal = bool(rsi is not None and stoch_k is not None and rsi > 45.0 and stoch_k > 50.0)
        sell_signal = adjusted_close < ma10
        entry_position_pct = 30.0
        allocation_posture = "drawdown_repair_entry"
        entry_reason = "Deep 60-day drawdown uses a lighter RSI/stochastic repair entry."
        exit_reason = "Drawdown repair mode exits when adjusted close falls below the 10-day average."
    else:
        mode = "rebound_trend_capture"
        buy_signal = from_low20_pct > 5.0 and adjusted_close >= ma10
        sell_signal = adjusted_close < ma20
        entry_position_pct = 100.0
        allocation_posture = "rebound_trend_capture"
        entry_reason = "Price is more than 5% above the trailing 20-day low and above the 10-day average."
        exit_reason = "Rebound trend mode exits when adjusted close falls below the 20-day average."

    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "matched_trade_date": row["date"],
        "adjusted_close": adjusted_close,
        "previous_close": previous_close,
        "daily_return_pct": daily_return_pct,
        "ma10": ma10,
        "ma20": ma20,
        "low20": low20,
        "high60": high60,
        "from_low20_pct": from_low20_pct,
        "drawdown60_pct": drawdown60_pct,
        "volatility_pct": volatility_pct,
        "rsi": rsi,
        "stoch_k": stoch_k,
        "macd_histogram": macd_histogram,
        "mode": mode,
        "entry_position_pct": entry_position_pct,
        "allocation_posture": allocation_posture,
        "entry_reason": entry_reason,
        "exit_reason": exit_reason,
        "buy_signal": buy_signal,
        "sell_signal": sell_signal,
    }


def fundamental_snapshot(ticker: str, trade_date: str) -> dict[str, Any]:
    income = _latest_statement_row(ticker, "income_statement.json", trade_date)
    balance = _latest_statement_row(ticker, "balance_sheet.json", trade_date)
    cashflow = _latest_statement_row(ticker, "cashflow.json", trade_date)
    revenue = _float(income.get("totalRevenue"))
    net_income = _float(income.get("netIncome"))
    operating_income = _float(income.get("operatingIncome"))
    operating_cashflow = _float(cashflow.get("operatingCashflow"))
    capex = _float(cashflow.get("capitalExpenditures"))
    current_assets = _float(balance.get("totalCurrentAssets"))
    current_liabilities = _float(balance.get("totalCurrentLiabilities"))
    long_debt = _float(balance.get("longTermDebt"))
    equity = _float(balance.get("totalShareholderEquity"))
    free_cashflow = operating_cashflow - abs(capex)
    net_margin_pct = net_income / revenue * 100.0 if revenue else 0.0
    current_ratio = current_assets / current_liabilities if current_liabilities else 0.0
    debt_to_equity = long_debt / equity if equity else 0.0
    score = 0
    score += 1 if revenue > 0 else -1
    score += 1 if net_income > 0 else -1
    score += 1 if operating_income > 0 else -1
    score += 1 if free_cashflow > 0 else -1
    score += 1 if current_ratio >= 1.0 else -1
    stance = "bullish" if score >= 3 else "bearish" if score <= -2 else "neutral"
    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "latest_income_date": income.get("fiscalDateEnding"),
        "latest_balance_date": balance.get("fiscalDateEnding"),
        "latest_cashflow_date": cashflow.get("fiscalDateEnding"),
        "revenue": revenue,
        "net_income": net_income,
        "operating_income": operating_income,
        "operating_cashflow": operating_cashflow,
        "free_cashflow": free_cashflow,
        "net_margin_pct": net_margin_pct,
        "current_ratio": current_ratio,
        "debt_to_equity": debt_to_equity,
        "score": score,
        "stance": stance,
    }


def news_snapshot(ticker: str, trade_date: str, lookback_days: int = 7) -> dict[str, Any]:
    path = NEWS_ROOT / f"{ticker}_news.json"
    data = _read_json(path)
    end_dt = _parse_date(trade_date) + timedelta(days=1)
    start_dt = end_dt - timedelta(days=lookback_days)
    articles = []
    for article in data.get("feed", []):
        try:
            article_dt = datetime.strptime(article["time_published"], "%Y%m%dT%H%M%S")
        except (KeyError, ValueError):
            continue
        if start_dt <= article_dt < end_dt:
            articles.append(article)
    articles.sort(key=lambda item: item.get("time_published", ""), reverse=True)
    text = " ".join(
        f"{item.get('title', '')} {item.get('summary', '')} {item.get('raw_text', '')}"
        for item in articles[:20]
    ).lower()
    positive_hits = _keyword_count(text, ["beat", "growth", "strong", "upgrade", "surge", "profit", "buy"])
    negative_hits = _keyword_count(text, ["miss", "weak", "downgrade", "lawsuit", "probe", "layoff", "loss", "sell"])
    stance = "bullish" if positive_hits > negative_hits else "bearish" if negative_hits > positive_hits else "neutral"
    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "lookback_days": lookback_days,
        "article_count": len(articles),
        "positive_hits": positive_hits,
        "negative_hits": negative_hits,
        "stance": stance,
        "top_titles": [str(item.get("title", ""))[:180] for item in articles[:5]],
    }


def policy_snapshot(trade_date: str) -> dict[str, Any]:
    indicators: dict[str, dict[str, Any]] = {}
    for name in [
        "federal_funds_rate",
        "treasury_yield_3m",
        "treasury_yield_10y",
        "inflation",
        "unemployment",
        "consumer_sentiment",
    ]:
        data = _read_json(ECONOMIC_ROOT / f"{name}.json")
        rows = [row for row in data.get("data", []) if str(row.get("date", "")) <= trade_date]
        latest = rows[-1] if rows else {}
        indicators[name] = {
            "latest_date": latest.get("date"),
            "latest_value": _float_or_none(latest.get("value")),
            "description": data.get("description", name),
        }
    fed = indicators["federal_funds_rate"]["latest_value"] or 0.0
    inflation = indicators["inflation"]["latest_value"] or 0.0
    sentiment = indicators["consumer_sentiment"]["latest_value"] or 0.0
    restrictive = fed >= 4.0 or inflation >= 5.0
    stance = "bearish" if restrictive and sentiment < 75 else "neutral" if restrictive else "bullish"
    return {
        "trade_date": trade_date,
        "indicators": indicators,
        "restrictive_policy": restrictive,
        "stance": stance,
    }


def recent_seed_examples(ticker: str, trade_date: str, lookback: int = 24) -> list[dict[str, Any]]:
    rows = [row for row in _read_csv_rows(STOCK_ROOT / ticker / "daily_prices.csv") if row.get("date", "") < trade_date]
    rows = rows[-lookback:]
    seeds = []
    for index, row in enumerate(rows):
        current_close = _float(row.get("adjusted_close"))
        next_close = _float(rows[index + 1].get("adjusted_close")) if index + 1 < len(rows) else current_close
        forward_return_pct = (next_close / current_close - 1.0) * 100.0 if current_close else 0.0
        if forward_return_pct > 1.5:
            target_action = "BUY"
            target_pct = 60.0
        elif forward_return_pct < -1.5:
            target_action = "SELL"
            target_pct = -100.0
        else:
            target_action = "HOLD"
            target_pct = 0.0
        seeds.append({
            "ticker": ticker,
            "trade_date": row.get("date", ""),
            "close": current_close,
            "forward_return_pct": forward_return_pct,
            "target_action": target_action,
            "target_position_pct": target_pct,
        })
    return seeds


def decision_from_instruction(
    instruction: dict[str, Any],
    max_position_pct: float,
    source: str,
) -> dict[str, Any]:
    action = str(instruction.get("action") or "HOLD").upper()
    if action not in {"BUY", "SELL", "HOLD"}:
        action = "HOLD"
    raw_position = _bounded_position_pct(instruction.get("position_pct", 0.0))
    max_position_pct = _bounded_pct(max_position_pct, 100.0)
    if action == "BUY":
        position_pct = min(max_position_pct, max(0.0, raw_position))
    elif action == "SELL":
        position_pct = -abs(raw_position or 100.0)
    else:
        position_pct = 0.0
    position_pct = round(position_pct, 2)
    return {
        "action": action,
        "position_pct": position_pct,
        "position_pct_display": f"{position_pct:.2f}%",
        "position_size": position_pct,
        "max_position_pct": max_position_pct,
        "max_buy_position_pct": max_position_pct,
        "allocation_posture": str(instruction.get("allocation_posture") or f"{source}_no_position"),
        "reasoning": str(instruction.get("reasoning") or instruction.get("reason") or ""),
        "supporting_evidence": _as_list(instruction.get("supporting_evidence")),
        "opposing_evidence": _as_list(instruction.get("opposing_evidence")),
        "key_risks": _as_list(instruction.get("key_risks")),
        "decision_source": source,
    }


def format_final_decision(decision: dict[str, Any]) -> str:
    lines = [
        f"Final Decision: {decision.get('action', 'HOLD')}",
        f"Position Percentage: {decision.get('position_pct_display', '0.00%')}",
        f"Allocation Posture: {decision.get('allocation_posture', '')}",
        "",
        f"Reasoning: {decision.get('reasoning', '')}",
    ]
    if decision.get("supporting_evidence"):
        lines.append("Supporting Evidence: " + "; ".join(_as_list(decision.get("supporting_evidence"))))
    if decision.get("opposing_evidence"):
        lines.append("Opposing Evidence: " + "; ".join(_as_list(decision.get("opposing_evidence"))))
    if decision.get("key_risks"):
        lines.append("Key Risks: " + "; ".join(_as_list(decision.get("key_risks"))))
    return "\n".join(lines)


def fallback_decision(max_position_pct: float, reason: str, source: str) -> dict[str, Any]:
    return decision_from_instruction(
        {
            "action": "HOLD",
            "position_pct": 0.0,
            "allocation_posture": f"{source}_fallback_no_position",
            "reasoning": reason,
            "key_risks": [reason],
        },
        max_position_pct=max_position_pct,
        source=f"{source}_fallback",
    )


def reports_from_state(state: AgentState) -> dict[str, str]:
    return {
        "technical": str(state.get("technical_report", "") or ""),
        "fundamental": str(state.get("fundamental_report", "") or ""),
        "news": str(state.get("news_report", "") or ""),
        "policy": str(state.get("policy_report", "") or ""),
    }


def report_stance(text: str) -> str:
    match = re.search(r"final\s+view\s*:\s*(bullish|bearish|neutral)", str(text), flags=re.IGNORECASE)
    if match:
        return match.group(1).lower()
    lowered = str(text).lower()
    if "bullish" in lowered:
        return "bullish"
    if "bearish" in lowered:
        return "bearish"
    if "neutral" in lowered:
        return "neutral"
    return "unknown"


def first_sentence(text: Any) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return parts[0][:260] if parts else cleaned[:260]


def clip_text(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "\n...[truncated]"


def render_technical_report(signal: dict[str, Any]) -> str:
    stance = "bullish" if signal["buy_signal"] else "bearish" if signal["sell_signal"] else "neutral"
    return (
        f"Key observations: close={signal['adjusted_close']:.2f}, ma10={signal['ma10']:.2f}, "
        f"ma20={signal['ma20']:.2f}, from_20d_low={signal['from_low20_pct']:.2f}%, "
        f"drawdown60={signal['drawdown60_pct']:.2f}%, rsi={_fmt_optional(signal.get('rsi'))}. "
        f"Trading implications: buy_signal={signal['buy_signal']}, sell_signal={signal['sell_signal']}; "
        f"mode={signal['mode']}. Final view: {stance}"
    )


def render_fundamental_report(snapshot: dict[str, Any]) -> str:
    return (
        f"Fundamental facts: latest income date={snapshot.get('latest_income_date')}, "
        f"revenue={snapshot['revenue']:.0f}, net_income={snapshot['net_income']:.0f}, "
        f"free_cashflow={snapshot['free_cashflow']:.0f}, current_ratio={snapshot['current_ratio']:.2f}, "
        f"debt_to_equity={snapshot['debt_to_equity']:.2f}. "
        f"Final view: {snapshot['stance']}"
    )


def render_news_report(snapshot: dict[str, Any]) -> str:
    titles = "; ".join(snapshot.get("top_titles") or []) or "no recent local headlines"
    return (
        f"Key news: recent article count={snapshot['article_count']}; "
        f"positive_hits={snapshot['positive_hits']}; negative_hits={snapshot['negative_hits']}. "
        f"Top titles: {titles}. Final view: {snapshot['stance']}"
    )


def render_policy_report(snapshot: dict[str, Any]) -> str:
    indicators = snapshot.get("indicators", {})
    fed = indicators.get("federal_funds_rate", {}).get("latest_value")
    inflation = indicators.get("inflation", {}).get("latest_value")
    sentiment = indicators.get("consumer_sentiment", {}).get("latest_value")
    return (
        f"Macro backdrop: fed_funds={_fmt_optional(fed)}, inflation={_fmt_optional(inflation)}, "
        f"consumer_sentiment={_fmt_optional(sentiment)}, restrictive_policy={snapshot['restrictive_policy']}. "
        f"Final view: {snapshot['stance']}"
    )


def _latest_statement_row(ticker: str, filename: str, trade_date: str) -> dict[str, Any]:
    data = _read_json(STOCK_ROOT / ticker / filename)
    candidates = []
    for key in ("quarterlyReports", "annualReports"):
        for row in data.get(key, []):
            date_value = str(row.get("fiscalDateEnding", ""))
            if date_value and date_value <= trade_date:
                candidates.append(row)
    if not candidates:
        return {}
    return sorted(candidates, key=lambda item: str(item.get("fiscalDateEnding", "")), reverse=True)[0]


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def _float(value: Any, default: float = 0.0) -> float:
    parsed = _float_or_none(value)
    return default if parsed is None else parsed


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "none":
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _bounded_pct(value: Any, default: float) -> float:
    try:
        return min(100.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return default


def _bounded_position_pct(value: Any) -> float:
    try:
        return min(100.0, max(-100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _keyword_count(text: str, keywords: list[str]) -> int:
    return sum(text.count(keyword) for keyword in keywords)


def _fmt_optional(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "n/a"
