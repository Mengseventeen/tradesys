from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from tradesys.workflows.common import (
    clip_text,
    report_stance,
    reports_from_state,
)

if TYPE_CHECKING:
    from tradesys.agents.utils.agent_states import AgentState
else:
    AgentState = dict[str, Any]


@dataclass(frozen=True)
class TradingOperatorSpec:
    name: str
    category: str
    input_keys: tuple[str, ...]
    output_keys: tuple[str, ...]
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.name,
            "category": self.category,
            "input_keys": list(self.input_keys),
            "output_keys": list(self.output_keys),
            "description": self.description,
        }


TRADING_OPERATOR_REGISTRY = [
    TradingOperatorSpec(
        "read_market_data",
        "data_loading",
        ("raw_evidence", "data_profile"),
        ("market_context",),
        "Read current-date technical, fundamental, news, and policy evidence into one market context.",
    ),
    TradingOperatorSpec(
        "bullish_signal",
        "bullish_bearish",
        ("market_context",),
        ("bullish_view",),
        "Build the buy-side thesis and bullish score from current evidence.",
    ),
    TradingOperatorSpec(
        "bearish_signal",
        "bullish_bearish",
        ("market_context",),
        ("bearish_view",),
        "Build the sell/hold risk thesis and bearish score from current evidence.",
    ),
    TradingOperatorSpec(
        "disagreement_detection",
        "disagreement_detection",
        ("bullish_view", "bearish_view", "market_context"),
        ("disagreement_report",),
        "Detect directional disagreement between bullish and bearish evidence branches.",
    ),
    TradingOperatorSpec(
        "risk_management",
        "risk_management",
        ("market_context", "bearish_view", "disagreement_report"),
        ("risk_profile",),
        "Apply volatility, drawdown, policy, data, and disagreement risk controls.",
    ),
    TradingOperatorSpec(
        "position_sizing",
        "position_sizing",
        ("bullish_view", "bearish_view", "risk_profile", "disagreement_report"),
        ("trade_instruction",),
        "Convert signal and risk outputs into BUY, SELL, or HOLD plus position percentage.",
    ),
    TradingOperatorSpec(
        "join",
        "final_decision",
        ("trade_instruction",),
        ("final_decision",),
        "Normalize the final decision contract: action in BUY/SELL/HOLD and position_pct as percent.",
    ),
]


REQUIRED_TRADING_OPERATORS = (
    "read_market_data",
    "bullish_signal",
    "bearish_signal",
    "disagreement_detection",
    "risk_management",
    "position_sizing",
    "join",
)


TRADING_TEMPLATES = {
    "signal_decomposition": {
        "name": "Signal decomposition",
        "description": "Split current evidence into bullish and bearish reasoning branches.",
        "abstract_steps_count": 3,
        "use_cases": ["separate buy thesis from sell/hold thesis", "make directional evidence explicit"],
    },
    "risk_control": {
        "name": "Risk control",
        "description": "Apply volatility, drawdown, macro, data-quality, and conflict risk controls.",
        "abstract_steps_count": 2,
        "use_cases": ["reduce exposure under high uncertainty", "block buys when exit risk is active"],
    },
    "position_construction": {
        "name": "Position construction",
        "description": "Translate signal and risk outputs into a percentage position.",
        "abstract_steps_count": 2,
        "use_cases": ["produce buy/sell/hold", "cap position by risk controls"],
    },
    "disagreement_resolution": {
        "name": "Disagreement resolution",
        "description": "Detect conflict between bullish and bearish branches before sizing.",
        "abstract_steps_count": 2,
        "use_cases": ["identify mixed evidence", "lower sizing when branches disagree"],
    },
}


def operator_manual() -> list[dict[str, Any]]:
    return [spec.to_dict() for spec in TRADING_OPERATOR_REGISTRY]


def operator_specs_by_name() -> dict[str, TradingOperatorSpec]:
    return {spec.name: spec for spec in TRADING_OPERATOR_REGISTRY}


def build_current_data_profile(state: AgentState) -> dict[str, Any]:
    local = state.get("local_evidence", {})
    reports = reports_from_state(state)
    technical = local.get("technical", {})
    fundamental = local.get("fundamental", {})
    news = local.get("news", {})
    policy = local.get("policy", {})
    return {
        "ticker": state.get("ticker", ""),
        "trade_date": state.get("trade_date", ""),
        "raw_blocks": sorted(local.keys()),
        "raw_fields": {
            block: sorted(value.keys()) if isinstance(value, dict) else []
            for block, value in local.items()
        },
        "report_stances": {name: report_stance(text) for name, text in reports.items()},
        "technical": {
            "matched_trade_date": technical.get("matched_trade_date"),
            "mode": technical.get("mode"),
            "buy_signal": bool(technical.get("buy_signal")),
            "sell_signal": bool(technical.get("sell_signal")),
            "entry_position_pct": technical.get("entry_position_pct"),
            "daily_return_pct": technical.get("daily_return_pct"),
            "from_low20_pct": technical.get("from_low20_pct"),
            "drawdown60_pct": technical.get("drawdown60_pct"),
            "volatility_pct": technical.get("volatility_pct"),
            "rsi": technical.get("rsi"),
            "macd_histogram": technical.get("macd_histogram"),
        },
        "fundamental": {
            "stance": fundamental.get("stance"),
            "score": fundamental.get("score"),
            "net_margin_pct": fundamental.get("net_margin_pct"),
            "current_ratio": fundamental.get("current_ratio"),
            "debt_to_equity": fundamental.get("debt_to_equity"),
        },
        "news": {
            "stance": news.get("stance"),
            "article_count": news.get("article_count"),
            "positive_hits": news.get("positive_hits"),
            "negative_hits": news.get("negative_hits"),
            "top_titles": news.get("top_titles", []),
        },
        "policy": {
            "stance": policy.get("stance"),
            "restrictive_policy": bool(policy.get("restrictive_policy")),
        },
        "reports_excerpt": {name: clip_text(text, 900) for name, text in reports.items()},
    }


def field_info_from_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_fields": profile.get("raw_fields", {}),
        "seed_fields": [],
        "new_fields": [
            "market_context",
            "bullish_view",
            "bearish_view",
            "disagreement_report",
            "risk_profile",
            "trade_instruction",
            "final_decision",
        ],
        "note": "This project has no seed data; DAG generation uses only current raw evidence.",
    }

