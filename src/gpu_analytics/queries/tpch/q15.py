"""TPC-H Q15 «Top Supplier» — лучший поставщик.

Смысл: поставщик (или поставщики), принёсший наибольшую выручку в 1-м квартале 1996 года.
Что нагружает: промежуточный результат, который используется дважды
(для поиска максимума и для отбора строк с этим максимумом).

Отличие от спецификации: в оригинале создаётся VIEW revenue0, а максимум ищется
подзапросом к нему, то есть выручка считается ДВАЖДЫ. С числами с плавающей точкой
это опасно: при втором подсчёте порядок сложения может отличиться, суммы разойдутся
в последнем знаке, и проверка «total_revenue = максимум» не найдёт ни одной строки.
Поэтому максимум берём оконной функцией MAX(...) OVER () из тех же самых значений —
выручка считается один раз. Такой SQL одинаково понимают DuckDB и Spark
(вариант WITH … AS MATERIALIZED Spark не поддерживает).
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from datetime import date  # Тип «дата».

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
WITH revenue AS (                                              -- выручка каждого поставщика
    SELECT l_suppkey AS supplier_no,                           -- поставщик
           SUM(l_extendedprice * (1 - l_discount)) AS total_revenue  -- его выручка
    FROM lineitem
    WHERE l_shipdate >= DATE '1996-01-01'                      -- 1-й квартал 1996 года
      AND l_shipdate <  DATE '1996-04-01'                      -- (1996-01-01 + 3 месяца)
    GROUP BY l_suppkey
),
with_max AS (                                                  -- те же строки + максимум по всем строкам
    SELECT supplier_no, total_revenue,
           MAX(total_revenue) OVER () AS max_revenue           -- OVER () — окно из всей таблицы: максимум приписывается каждой строке
    FROM revenue
)
SELECT s_suppkey, s_name, s_address, s_phone,                  -- поставщик и его контакты
       total_revenue                                           -- его выручка
FROM supplier, with_max
WHERE s_suppkey = supplier_no                                  -- поставщик ↔ его выручка
  AND total_revenue = max_revenue                              -- выручка равна максимальной
ORDER BY s_suppkey
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q15 на Polars."""
    revenue = (  # Выручка каждого поставщика за 1-й квартал 1996 года.
        t["lineitem"].filter(  # Позиции 1-го квартала 1996 года.
            pl.col("l_shipdate") >= date(1996, 1, 1),  # С 01.01.1996.
            pl.col("l_shipdate") < date(1996, 4, 1),  # До 01.04.1996.
        )
        .group_by("l_suppkey")  # Группируем по поставщику.
        .agg((pl.col("l_extendedprice") * (1 - pl.col("l_discount"))).sum().alias("total_revenue"))  # Его выручка.
    )
    return (
        t["supplier"].join(revenue, left_on="s_suppkey", right_on="l_suppkey")  # Поставщики + их выручка.
        # Выражение pl.col(...).max() внутри filter считается по всей таблице и сравнивается с каждой строкой.
        .filter(pl.col("total_revenue") == pl.col("total_revenue").max())  # Только строки с максимальной выручкой.
        .select("s_suppkey", "s_name", "s_address", "s_phone", "total_revenue")  # Колонки как в SQL.
        .sort("s_suppkey")  # ORDER BY s_suppkey.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q15",  # Имя для командной строки.
    tables=["lineitem", "supplier"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["s_suppkey"],  # Поставщик однозначно задаёт строку.
)
