import os
import json
import pandas as pd
from pathlib import Path
from typing import Optional


DATA_ROOT = Path(__file__).parent.parent / "data_portfolio"

def get_data_path(data_type: str, ticker: Optional[str] = None) -> Path:
    if ticker:
        return DATA_ROOT / data_type / ticker
    return DATA_ROOT / data_type


def read_json_file(file_path: Path) -> dict:
    if not file_path.exists():
        return {}
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def read_csv_file(file_path: Path) -> pd.DataFrame:
    if not file_path.exists():
        raise FileNotFoundError(f"Data file not found: {file_path}")
    
    return pd.read_csv(file_path)


def format_json_output(data: dict, indent: int = 2) -> str:
    return json.dumps(data, indent=indent, ensure_ascii=False)
