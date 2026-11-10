"""TPC-H Q3 «Shipping Priority» — приоритет отгрузки.

Смысл: 10 самых дорогих ещё не отгруженных (на 15.03.1995) заказов клиентов
из сегмента BUILDING.
Что нагружает: соединение трёх таблиц (customer, orders, lineitem) + группировка
с большим числом групп + сортировка с ограничением (top-10).
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from datetime import date  # Тип «дата».

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT l_orderkey,                                             -- номер заказа
       SUM(l_extendedprice * (1 - l_discount)) AS revenue,     -- выручка по заказу со скидкой
       o_orderdate,                                            -- дата заказа
       o_shippriority                                          -- приоритет отгрузки
FROM customer, orders, lineitem
WHERE c_mktsegment = 'BUILDING'                                -- клиенты сегмента BUILDING
  AND c_custkey = o_custkey                                    -- клиент ↔ заказ
  AND l_orderkey = o_orderkey                                  -- заказ ↔ позиции
  AND o_orderdate < DATE '1995-03-15'                          -- заказ сделан до 15.03.1995
  AND l_shipdate  > DATE '1995-03-15'                          -- а позиция отгружена после этой даты
GROUP BY l_orderkey, o_orderdate, o_shippriority
ORDER BY revenue DESC, o_orderdate                             -- самые дорогие заказы первыми
LIMIT 10
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q3 на Polars."""
    customers = t["customer"].filter(pl.col("c_mktsegment") == "BUILDING")  # Клиенты сегмента BUILDING.
    orders = t["orders"].filter(pl.col("o_orderdate") < date(1995, 3, 15))  # Заказы до 15.03.1995.
    lineitem = t["lineitem"].filter(pl.col("l_shipdate") > date(1995, 3, 15))  # Позиции, отгруженные после 15.03.1995.
    return (
        # Начинаем с lineitem: в Polars при соединении по разноимённым ключам остаётся ключ ЛЕВОЙ таблицы,
        # а нам в ответе нужен именно l_orderkey.
        lineitem.join(orders, left_on="l_orderkey", right_on="o_orderkey")  # Позиции + их заказы.
        .join(customers, left_on="o_custkey", right_on="c_custkey")  # + клиенты (оставляет только BUILDING).
        .group_by("l_orderkey", "o_orderdate", "o_shippriority")  # GROUP BY.
        .agg((pl.col("l_extendedprice") * (1 - pl.col("l_discount"))).sum().alias("revenue"))  # Выручка по заказу.
        .select("l_orderkey", "revenue", "o_orderdate", "o_shippriority")  # Порядок колонок как в SQL.
        .sort("revenue", "o_orderdate", descending=[True, False])  # ORDER BY revenue DESC, o_orderdate.
        .head(10)  # LIMIT 10.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q3",  # Имя для командной строки.
    tables=["customer", "lineitem", "orders"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["l_orderkey"],  # Номер заказа однозначно задаёт строку.
)
