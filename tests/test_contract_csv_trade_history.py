import pandas as pd
import pytest

from ogami_oanda.adapters.repositories.csv_trade_history import (
    CsvTradeHistoryRepository,
)
from ogami_oanda.infrastructure.config.legacy_tokens import settings_from_tokens


@pytest.mark.contract
def test_csv_trade_history_preserves_first_record_column_order_and_appends(tmp_path):
    repository = CsvTradeHistoryRepository(tmp_path / "nested" / "history.csv")
    first = {"name": "first", "res": 1, "pair": "USD_JPY"}
    second = {"name": "second", "res": -1, "pair": "USD_JPY"}

    repository.append(first)
    repository.append(second)

    history = pd.read_csv(repository.path)
    assert list(history.columns) == ["name", "res", "pair"]
    assert history.to_dict("records") == [first, second]


@pytest.mark.contract
def test_csv_trade_history_appends_once_and_reads_existing_trade_ids(tmp_path):
    repository = CsvTradeHistoryRepository(tmp_path / "history.csv")
    record = {
        "name": "closed",
        "pair": "USD_JPY",
        "tradeID": "trade-1",
        "res": "20",
        "pl_per_units": 2,
    }

    assert repository.append_once(record, unique_field="tradeID") is True
    assert repository.append_once(record, unique_field="tradeID") is False
    assert repository.read_all() == (
        {
            "name": "closed",
            "pair": "USD_JPY",
            "tradeID": "trade-1",
            "res": "20",
            "pl_per_units": "2",
        },
    )


@pytest.mark.contract
def test_token_settings_maps_legacy_history_folder_to_history_file():
    import tokens

    tokens.history_folder_path = "results/"
    settings = settings_from_tokens(tokens)

    assert settings.paths.history_file == "results/history.csv"
