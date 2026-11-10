"""TPC-H Q17 «Small-Quantity-Order Revenue» — выручка от мелких заказов.

Смысл: сколько в среднем за год теряется выручки, если перестать принимать мелкие
заказы (меньше 20% от среднего количества) деталей бренда Brand#23 в упаковке MED BOX.
Что нагружает: коррелированный подзапрос со средним значением по детали.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables, sql_sum  # Описание запроса, тип «таблицы Polars», SUM как в SQL.

SQL = """
SELECT SUM(l_extendedprice) / 7.0 AS avg_yearly                -- выручка за 7 лет данных → в среднем за год
FROM lineitem, part
WHERE p_partkey = l_partkey                                    -- позиция ↔ деталь
  AND p_brand = 'Brand#23'                                     -- бренд
  AND p_container = 'MED BOX'                                  -- упаковка
  AND l_quantity < (                                           -- количество меньше...
      SELECT 0.2 * AVG(l_quantity)                             -- ...20% от среднего количества...
      FROM lineitem
      WHERE l_partkey = p_partkey)                             -- ...по этой же детали (коррелированный подзапрос)
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q17 на Polars: подзапрос = «среднее по группе + соединение»."""
    parts = t["part"].filter(pl.col("p_brand") == "Brand#23", pl.col("p_container") == "MED BOX")  # Нужные детали.
    lineitem = t["lineitem"].join(parts, left_on="l_partkey", right_on="p_partkey", how="semi")  # Все позиции этих деталей.
    threshold = (  # Порог для каждой детали — это и есть подзапрос.
        lineitem.group_by("l_partkey")  # Группируем по детали (позиции здесь — ВСЕ позиции детали, как в подзапросе).
        .agg((0.2 * pl.col("l_quantity").mean()).alias("threshold"))  # 20% от среднего количества.
    )
    return (
        lineitem.join(threshold, on="l_partkey")  # К каждой позиции приписываем порог её детали.
        .filter(pl.col("l_quantity") < pl.col("threshold"))  # Только мелкие позиции.
        .select((sql_sum(pl.col("l_extendedprice")) / 7.0).alias("avg_yearly"))  # Средняя выручка за год (NULL, если строк нет — как в SQL).
    )


QUERY = Query(  # Собираем описание запроса.
    name="q17",  # Имя для командной строки.
    tables=["lineitem", "part"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=[],  # Одна строка в ответе.
)
