"""TPC-H Q9 «Product Type Profit Measure» — прибыль по типу товара.

Смысл: прибыль от деталей, в названии которых есть слово green, по странам
поставщиков и годам.
Что нагружает: соединение шести таблиц, в том числе по составному ключу
(деталь + поставщик), и строковый поиск по подстроке (LIKE '%green%').
Обычно один из самых тяжёлых запросов TPC-H.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT nation, o_year,                                         -- страна поставщика, год
       SUM(amount) AS sum_profit                               -- суммарная прибыль
FROM (
    SELECT n_name AS nation,                                   -- страна поставщика
           EXTRACT(year FROM o_orderdate) AS o_year,           -- год заказа
           l_extendedprice * (1 - l_discount)                  -- выручка позиции...
             - ps_supplycost * l_quantity AS amount            -- ...минус закупочная стоимость = прибыль
    FROM part, supplier, lineitem, partsupp, orders, nation
    WHERE s_suppkey = l_suppkey                                -- поставщик ↔ позиция
      AND ps_suppkey = l_suppkey                               -- предложение ↔ позиция: тот же поставщик...
      AND ps_partkey = l_partkey                               -- ...и та же деталь (составной ключ)
      AND p_partkey = l_partkey                                -- деталь ↔ позиция
      AND o_orderkey = l_orderkey                              -- заказ ↔ позиция
      AND s_nationkey = n_nationkey                            -- поставщик ↔ страна
      AND p_name LIKE '%green%'                                -- в названии детали есть «green»
) AS profit
GROUP BY nation, o_year
ORDER BY nation, o_year DESC                                   -- страны по алфавиту, годы от новых к старым
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q9 на Polars."""
    green_parts = t["part"].filter(pl.col("p_name").str.contains("green", literal=True))  # literal=True — искать текст, а не регулярное выражение.
    amount = (  # Выражение «прибыль позиции».
        pl.col("l_extendedprice") * (1 - pl.col("l_discount"))  # Выручка со скидкой...
        - pl.col("ps_supplycost") * pl.col("l_quantity")  # ...минус закупочная цена × количество.
    )
    return (
        t["lineitem"]  # Позиции заказов.
        .join(green_parts, left_on="l_partkey", right_on="p_partkey", how="semi")  # Только «зелёные» детали.
        .join(  # + предложение поставщика: соединение по составному ключу.
            t["partsupp"],
            left_on=["l_partkey", "l_suppkey"],  # Деталь и поставщик позиции...
            right_on=["ps_partkey", "ps_suppkey"],  # ...совпадают с деталью и поставщиком предложения.
        )
        .join(t["supplier"], left_on="l_suppkey", right_on="s_suppkey")  # + поставщик (нужна страна).
        .join(t["nation"], left_on="s_nationkey", right_on="n_nationkey")  # + название страны.
        .join(t["orders"], left_on="l_orderkey", right_on="o_orderkey")  # + заказ (нужна дата).
        .group_by(  # GROUP BY.
            pl.col("n_name").alias("nation"),  # Страна (переименована, как в SQL).
            pl.col("o_orderdate").dt.year().alias("o_year"),  # Год заказа.
        )
        .agg(amount.sum().alias("sum_profit"))  # SUM(amount).
        .sort("nation", "o_year", descending=[False, True])  # ORDER BY nation, o_year DESC.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q9",  # Имя для командной строки.
    tables=["lineitem", "nation", "orders", "part", "partsupp", "supplier"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["nation", "o_year"],  # Ключ группировки однозначно задаёт строку.
)
