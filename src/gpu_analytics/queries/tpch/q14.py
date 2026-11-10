"""TPC-H Q14 «Promotion Effect» — эффект рекламной акции.

Смысл: какой процент выручки за сентябрь 1995 года дали рекламные (PROMO) товары.
Что нагружает: соединение большой таблицы lineitem с part + условная сумма
с проверкой начала строки (LIKE 'PROMO%').
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from datetime import date  # Тип «дата».

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables, sql_sum  # Описание запроса, тип «таблицы Polars», SUM как в SQL.

SQL = """
SELECT 100.00 * SUM(CASE WHEN p_type LIKE 'PROMO%'             -- выручка рекламных деталей...
                         THEN l_extendedprice * (1 - l_discount)
                         ELSE 0 END)
       / SUM(l_extendedprice * (1 - l_discount))               -- ...делённая на всю выручку...
       AS promo_revenue                                        -- ...в процентах
FROM lineitem, part
WHERE l_partkey = p_partkey                                    -- позиция ↔ деталь
  AND l_shipdate >= DATE '1995-09-01'                          -- отгрузки сентября 1995 года
  AND l_shipdate <  DATE '1995-10-01'                          -- (1995-09-01 + 1 месяц)
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q14 на Polars."""
    lineitem = t["lineitem"].filter(  # Позиции, отгруженные в сентябре 1995 года.
        pl.col("l_shipdate") >= date(1995, 9, 1),  # С 01.09.1995.
        pl.col("l_shipdate") < date(1995, 10, 1),  # До 01.10.1995.
    )
    revenue = pl.col("l_extendedprice") * (1 - pl.col("l_discount"))  # Выражение «выручка позиции».
    promo_revenue = pl.when(pl.col("p_type").str.starts_with("PROMO")).then(revenue).otherwise(0)  # CASE WHEN … THEN … ELSE 0.
    return (
        lineitem.join(t["part"], left_on="l_partkey", right_on="p_partkey")  # Позиции + детали (нужен тип детали).
        .select((100.0 * sql_sum(promo_revenue) / sql_sum(revenue)).alias("promo_revenue"))  # Процент рекламной выручки (NULL, если строк нет).
    )


QUERY = Query(  # Собираем описание запроса.
    name="q14",  # Имя для командной строки.
    tables=["lineitem", "part"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=[],  # Одна строка в ответе.
)
