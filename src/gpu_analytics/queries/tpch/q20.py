"""TPC-H Q20 «Potential Part Promotion» — кандидаты на акцию.

Смысл: канадские поставщики, у которых на складе деталей «forest…» больше половины
того, что они продали за 1994 год, — им можно предложить акцию.
Что нагружает: вложенные подзапросы IN и коррелированный подзапрос с суммой
по составному ключу (деталь + поставщик).
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from datetime import date  # Тип «дата».

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT s_name, s_address                                       -- имя и адрес поставщика
FROM supplier, nation
WHERE s_suppkey IN (                                           -- поставщик входит в список...
      SELECT ps_suppkey FROM partsupp
      WHERE ps_partkey IN (                                    -- ...предложений деталей...
            SELECT p_partkey FROM part
            WHERE p_name LIKE 'forest%')                       -- ...с названием на «forest»...
        AND ps_availqty > (                                    -- ...у которых запас больше...
            SELECT 0.5 * SUM(l_quantity)                       -- ...половины проданного...
            FROM lineitem
            WHERE l_partkey = ps_partkey                       -- ...этой детали...
              AND l_suppkey = ps_suppkey                       -- ...этим поставщиком...
              AND l_shipdate >= DATE '1994-01-01'              -- ...за 1994 год
              AND l_shipdate <  DATE '1995-01-01'))
  AND s_nationkey = n_nationkey                                -- поставщик ↔ страна
  AND n_name = 'CANADA'                                        -- только Канада
ORDER BY s_name
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q20 на Polars: подзапросы IN = полусоединения, коррелированная сумма = группировка + соединение."""
    sold_1994 = (  # Половина проданного за 1994 год для каждой пары «деталь + поставщик».
        t["lineitem"].filter(  # Позиции 1994 года.
            pl.col("l_shipdate") >= date(1994, 1, 1),  # С 01.01.1994.
            pl.col("l_shipdate") < date(1995, 1, 1),  # До 01.01.1995.
        )
        .group_by("l_partkey", "l_suppkey")  # Группируем по паре «деталь + поставщик».
        .agg((0.5 * pl.col("l_quantity").sum()).alias("half_sold"))  # 0.5 × SUM(l_quantity).
    )
    forest_parts = t["part"].filter(pl.col("p_name").str.starts_with("forest"))  # LIKE 'forest%' — начинается с «forest».
    candidate_suppliers = (  # Поставщики, у которых запас «forest»-деталей больше половины проданного.
        t["partsupp"]  # Предложения поставщиков.
        .join(forest_parts, left_on="ps_partkey", right_on="p_partkey", how="semi")  # Только «forest»-детали.
        # Обычное (внутреннее) соединение: если продаж не было, в SQL сумма = NULL и сравнение
        # «> NULL» ложно — такая пара отбрасывается. Внутреннее соединение делает то же самое.
        .join(sold_1994, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"])
        .filter(pl.col("ps_availqty") > pl.col("half_sold"))  # Запас больше половины проданного.
    )
    return (
        t["nation"].filter(pl.col("n_name") == "CANADA")  # Страна «Канада».
        .join(t["supplier"], left_on="n_nationkey", right_on="s_nationkey")  # Канадские поставщики.
        .join(candidate_suppliers, left_on="s_suppkey", right_on="ps_suppkey", how="semi")  # Только из списка кандидатов.
        .select("s_name", "s_address")  # Колонки как в SQL.
        .sort("s_name")  # ORDER BY s_name.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q20",  # Имя для командной строки.
    tables=["lineitem", "nation", "part", "partsupp", "supplier"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["s_name"],  # Имя поставщика уникально.
)
