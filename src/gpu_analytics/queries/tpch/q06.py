"""TPC-H Q6 «Forecasting Revenue Change» — прогноз изменения выручки.

Смысл: насколько выросла бы выручка, если убрать небольшие скидки в 1994 году
у позиций с малым количеством товара.
Что нагружает: почти чистое сканирование lineitem с несколькими фильтрами и одной
суммой. Здесь GPU выигрывает за счёт пропускной способности памяти — если данные
успевают доехать до GPU.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from datetime import date  # Тип «дата».

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables, sql_sum  # Описание запроса, тип «таблицы Polars», SUM как в SQL.

SQL = """
SELECT
    SUM(l_extendedprice * l_discount) AS revenue              -- выручка, «потерянная» на скидках
FROM lineitem
WHERE l_shipdate >= DATE '1994-01-01'                         -- с начала 1994 года
  AND l_shipdate <  DATE '1995-01-01'                         -- до начала 1995 года
  AND l_discount BETWEEN 0.05 AND 0.07                        -- скидка от 5% до 7%
  AND l_quantity < 24                                         -- количество меньше 24
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q6 на Polars."""
    return (
        t["lineitem"]  # Берём таблицу позиций заказов.
        .filter(  # WHERE: все условия перечислены через запятую — Polars объединяет их через AND.
            pl.col("l_shipdate") >= date(1994, 1, 1),  # С начала 1994 года.
            pl.col("l_shipdate") < date(1995, 1, 1),  # До начала 1995 года.
            pl.col("l_discount").is_between(0.05, 0.07),  # Скидка от 5% до 7% включительно (как BETWEEN в SQL).
            pl.col("l_quantity") < 24,  # Количество меньше 24.
        )
        .select(sql_sum(pl.col("l_extendedprice") * pl.col("l_discount")).alias("revenue"))  # SUM(цена × скидка); NULL, если строк нет — как в SQL.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q6",  # Имя для командной строки.
    tables=["lineitem"],  # Читает только lineitem.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=[],  # Одна строка в ответе — сортировать нечего.
)
