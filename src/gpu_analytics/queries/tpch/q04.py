"""TPC-H Q4 «Order Priority Checking» — проверка приоритетов заказов.

Смысл: сколько заказов 3-го квартала 1993 года имели хотя бы одну позицию,
доставленную позже обещанной даты, — по каждому приоритету заказа.
Что нагружает: подзапрос EXISTS, то есть «полусоединение» (semi join).
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from datetime import date  # Тип «дата».

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT o_orderpriority,                                        -- приоритет заказа
       COUNT(*) AS order_count                                 -- число заказов
FROM orders
WHERE o_orderdate >= DATE '1993-07-01'                         -- с 01.07.1993...
  AND o_orderdate <  DATE '1993-10-01'                         -- ...по 30.09.1993 (1993-07-01 + 3 месяца)
  AND EXISTS (                                                 -- существует хотя бы одна...
      SELECT * FROM lineitem
      WHERE l_orderkey = o_orderkey                            -- ...позиция этого заказа...
        AND l_commitdate < l_receiptdate)                      -- ...полученная позже обещанной даты
GROUP BY o_orderpriority
ORDER BY o_orderpriority
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q4 на Polars: EXISTS = полусоединение (how="semi")."""
    late_lines = t["lineitem"].filter(pl.col("l_commitdate") < pl.col("l_receiptdate"))  # Позиции, доставленные с опозданием.
    return (
        t["orders"]  # Таблица заказов.
        .filter(  # Заказы 3-го квартала 1993 года.
            pl.col("o_orderdate") >= date(1993, 7, 1),  # С 01.07.1993.
            pl.col("o_orderdate") < date(1993, 10, 1),  # До 01.10.1993.
        )
        # Полусоединение: оставить заказ, если у него есть хоть одна опоздавшая позиция.
        # В отличие от обычного join, строки заказа не размножаются и колонки lineitem не добавляются.
        .join(late_lines, left_on="o_orderkey", right_on="l_orderkey", how="semi")
        .group_by("o_orderpriority")  # GROUP BY o_orderpriority.
        .agg(pl.len().alias("order_count"))  # COUNT(*).
        .sort("o_orderpriority")  # ORDER BY o_orderpriority.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q4",  # Имя для командной строки.
    tables=["lineitem", "orders"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["o_orderpriority"],  # Приоритет однозначно задаёт строку.
)
