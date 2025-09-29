from pathlib import Path
import pandas as pd

BASE_COLUMNS = ["url", "name", "email", "comment", "status", "notes"]
TPL_COLUMNS  = [
    "tpl_ta_sel", "tpl_name_sel", "tpl_email_sel", "tpl_btn_sel",
    "tpl_ta_iframe", "tpl_btn_iframe", "tpl_scope",
]
COLUMNS = BASE_COLUMNS + TPL_COLUMNS

def _ensure_cols(df: pd.DataFrame) -> pd.DataFrame:
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df = df[COLUMNS]
    # ép string để tránh FutureWarning của pandas
    return df.astype("string").fillna("")

def load_rows(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return _ensure_cols(pd.DataFrame(columns=COLUMNS))
    df = pd.read_excel(p, dtype=str, engine="openpyxl")
    return _ensure_cols(df)

def save_rows(df: pd.DataFrame, path: str) -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    _ensure_cols(df.copy()).to_excel(p, index=False, engine="openpyxl")
