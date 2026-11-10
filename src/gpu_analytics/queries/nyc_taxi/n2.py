"""NYC Taxi N2 — чаевые по способу оплаты.

Смысл: средние чаевые и средняя доля чаевых от тарифа для каждого способа оплаты
(1 — карта, 2 — наличные, 3 — бесплатно, 4 — спор, 0 — «гибкий тариф»).
Что нагружает: фильтр + арифметика (деление) в каждой строке + группировка.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT payment_type,                                           -- способ оплаты
       COUNT(*)                      AS trips,                 -- число поездок
       AVG(tip_amount)               AS avg_tip,               -- средние чаевые, $
       AVG(tip_amount / fare_amount) AS avg_tip_share          -- средняя доля чаевых от тарифа
FROM trips
WHERE fare_amount > 0                                          -- без нулевых и отрицательных тарифов (иначе деление на 0)
GROUP BY payment_type
ORDER BY payment_type
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """N2 на Polars."""
    return (
        t["trips"]  # Таблица поездок.
        .filter(pl.col("fare_amount") > 0)  # WHERE fare_amount > 0.
        .group_by("payment_type")  # GROUP BY payment_type.
        .agg(  # Агрегаты по способу оплаты.
            pl.len().alias("trips"),  # COUNT(*).
            pl.col("tip_amount").mean().alias("avg_tip"),  # AVG(tip_amount).
            (pl.col("tip_amount") / pl.col("fare_amount")).mean().alias("avg_tip_share"),  # AVG(чаевые / тариф).
        )
        .sort("payment_type")  # ORDER BY payment_type.
    )


QUERY = Query(  # Собираем описание запроса.
    name="n2",  # Имя для командной строки.
    tables=["trips"],  # Читает только поездки.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["payment_type"],  # Способ оплаты однозначно задаёт строку.
)
