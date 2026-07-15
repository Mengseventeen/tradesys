import os
from datetime import datetime
from typing import Optional


DEFAULT_REPORTS_DIR = "reports"


class ReportLogger:
    def __init__(self, base_dir: Optional[str] = None):
        configured_dir = os.environ.get("TRADESYS_REPORTS_DIR")
        if base_dir is not None:
            self.base_dir = base_dir
        elif configured_dir:
            self.base_dir = configured_dir
        else:
            run_timestamp = os.environ.setdefault(
                "TRADESYS_REPORTS_TIMESTAMP",
                datetime.now().strftime("%Y%m%d_%H%M%S"),
            )
            self.base_dir = os.path.join(DEFAULT_REPORTS_DIR, run_timestamp)

        os.makedirs(self.base_dir, exist_ok=True)

    def log_report(
        self,
        agent_name: str,
        report: str,
        ticker: str,
        trade_date: str,
        report_type: Optional[str] = None,
    ) -> str | None:
        if not report or not report.strip():
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{report_type}" if report_type else ""
        filename = f"{ticker}_{trade_date}_{agent_name}{suffix}_{timestamp}.md"
        file_path = os.path.join(self.base_dir, filename)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# {agent_name} Report\n")
            f.write(f"Ticker: {ticker}\n")
            f.write(f"Trade Date: {trade_date}\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(report)

        return file_path

    def log_technical_report(self, report: str, ticker: str, trade_date: str) -> str | None:
        return self.log_report("technical_analyst", report, ticker, trade_date, "technical")

    def log_fundamental_report(self, report: str, ticker: str, trade_date: str) -> str | None:
        return self.log_report("fundamental_analyst", report, ticker, trade_date, "fundamental")

    def log_policy_report(self, report: str, ticker: str, trade_date: str) -> str | None:
        return self.log_report("policy_analyst", report, ticker, trade_date, "policy")

    def log_news_report(self, report: str, ticker: str, trade_date: str) -> str | None:
        return self.log_report("news_analyst", report, ticker, trade_date, "news")


_global_report_logger: Optional[ReportLogger] = None


def get_report_logger() -> ReportLogger:
    global _global_report_logger
    if _global_report_logger is None:
        _global_report_logger = ReportLogger()
    return _global_report_logger
