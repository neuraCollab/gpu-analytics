"""TPC-H Q5 «Local Supplier Volume» — объём местных поставок.

Смысл: выручка в 1994 году по странам Азии от сделок, где клиент и поставщик
из одной и той же страны.
Что нагружает: соединение шести таблиц, одно из соединений — по двум ключам сразу.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from datetime import date  # Тип «дата».

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT n_name,                                                 -- страна
       SUM(l_extendedprice * (1 - l_discount)) AS revenue      -- выручка со скидкой
FROM customer, orders, lineitem, supplier, nation, region
WHERE c_custkey = o_custkey                                    -- клиент ↔ заказ
  AND l_orderkey = o_orderkey                                  -- заказ ↔ позиции
  AND l_suppkey = s_suppkey                                    -- позиция ↔ поставщик
  AND c_nationkey = s_nationkey                                -- клиент и поставщик из одной страны
  AND s_nationkey = n_nationkey                                -- поставщик ↔ страна
  AND n_regionkey = r_regionkey                                -- страна ↔ регион
  AND r_name = 'ASIA'                                          -- только Азия
  AND o_orderdate >= DATE '1994-01-01'                         -- заказы 1994 года
  AND o_orderdate <  DATE '1995-01-01'
GROUP BY n_name
ORDER BY revenue DESC
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q5 на Polars."""
    asian_suppliers = (  # Поставщики из стран Азии (вместе с названием страны).
        t["region"].filter(pl.col("r_name") == "ASIA")  # Регион «Азия».
        .join(t["nation"], left_on="r_regionkey", right_on="n_regionkey")  # Страны Азии.
        .join(t["supplier"], left_on="n_nationkey", right_on="s_nationkey")  # Поставщики из них; ключ n_nationkey остаётся.
    )
    orders = t["orders"].filter(  # Заказы 1994 года.
        pl.col("o_orderdate") >= date(1994, 1, 1),  # С 01.01.1994.
        pl.col("o_orderdate") < date(1995, 1, 1),  # До 01.01.1995.
    )
    return (
        t["lineitem"]  # Позиции заказов.
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")  # + заказы 1994 года.
        .join(t["customer"], left_on="o_custkey", right_on="c_custkey")  # + клиенты (нужна их страна c_nationkey).
        .join(  # + азиатские поставщики, причём сразу по двум условиям:
            asian_suppliers,
            left_on=["l_suppkey", "c_nationkey"],  # поставщик позиции И страна клиента...
            right_on=["s_suppkey", "n_nationkey"],  # ...должны совпасть с поставщиком и его страной.
        )
        .group_by("n_name")  # GROUP BY n_name.
        .agg((pl.col("l_extendedprice") * (1 - pl.col("l_discount"))).sum().alias("revenue"))  # Выручка.
        .sort("revenue", descending=True)  # ORDER BY revenue DESC.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q5",  # Имя для командной строки.
    tables=["customer", "lineitem", "nation", "orders", "region", "supplier"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["n_name"],  # Страна однозначно задаёт строку.
)
