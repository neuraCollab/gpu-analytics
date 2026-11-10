"""TPC-H Q13 «Customer Distribution» — распределение клиентов по числу заказов.

Смысл: сколько клиентов сделали 0, 1, 2, … заказов (не считая заказов с комментарием
про «special requests»).
Что нагружает: внешнее левое соединение (LEFT JOIN — клиенты без заказов тоже нужны),
поиск по шаблону в строках и две группировки подряд.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT c_count,                                                -- сколько заказов у клиента
       COUNT(*) AS custdist                                    -- сколько клиентов с таким числом заказов
FROM (
    SELECT c_custkey,
           COUNT(o_orderkey) AS c_count                        -- COUNT(колонка) не считает NULL: клиент без заказов → 0
    FROM customer
    LEFT OUTER JOIN orders                                     -- LEFT: клиенты без заказов остаются (с NULL в колонках orders)
      ON c_custkey = o_custkey
     AND o_comment NOT LIKE '%special%requests%'               -- не учитываем заказы с таким комментарием
    GROUP BY c_custkey
) AS c_orders
GROUP BY c_count
ORDER BY custdist DESC, c_count DESC
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q13 на Polars."""
    # LIKE '%special%requests%' — «special», потом что угодно, потом «requests».
    # В регулярном выражении это записывается как special.*requests («.*» — любые символы).
    orders = t["orders"].filter(~pl.col("o_comment").str.contains("special.*requests"))  # «~» — НЕ: убираем такие заказы.
    return (
        t["customer"].join(orders, left_on="c_custkey", right_on="o_custkey", how="left")  # LEFT JOIN: все клиенты остаются.
        .group_by("c_custkey")  # Первая группировка — по клиенту.
        .agg(pl.col("o_orderkey").count().alias("c_count"))  # count() по колонке не считает пропуски (null) — как COUNT(o_orderkey).
        .group_by("c_count")  # Вторая группировка — по числу заказов.
        .agg(pl.len().alias("custdist"))  # Сколько клиентов в каждой группе.
        .sort("custdist", "c_count", descending=[True, True])  # ORDER BY custdist DESC, c_count DESC.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q13",  # Имя для командной строки.
    tables=["customer", "orders"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["c_count"],  # Число заказов однозначно задаёт строку.
)
