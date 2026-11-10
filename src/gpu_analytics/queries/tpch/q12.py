"""TPC-H Q12 «Shipping Modes and Order Priority» — способы доставки и приоритет.

Смысл: влияет ли дешёвый способ доставки (MAIL, SHIP) на то, что срочные заказы
приходят с опозданием. Считаем опоздавшие позиции 1994 года отдельно для срочных
и несрочных заказов.
Что нагружает: соединение двух больших таблиц + фильтр со сравнением колонок между собой
+ условные суммы (CASE).
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from datetime import date  # Тип «дата».

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT l_shipmode,                                             -- способ доставки
       SUM(CASE WHEN o_orderpriority = '1-URGENT'
                  OR o_orderpriority = '2-HIGH'
                THEN 1 ELSE 0 END) AS high_line_count,         -- число позиций срочных заказов
       SUM(CASE WHEN o_orderpriority <> '1-URGENT'
                 AND o_orderpriority <> '2-HIGH'
                THEN 1 ELSE 0 END) AS low_line_count           -- число позиций остальных заказов
FROM orders, lineitem
WHERE o_orderkey = l_orderkey                                  -- заказ ↔ позиции
  AND l_shipmode IN ('MAIL', 'SHIP')                           -- только почта и морская доставка
  AND l_commitdate < l_receiptdate                             -- получено позже обещанного
  AND l_shipdate < l_commitdate                                -- хотя отгружено вовремя
  AND l_receiptdate >= DATE '1994-01-01'                       -- получено в 1994 году
  AND l_receiptdate <  DATE '1995-01-01'
GROUP BY l_shipmode
ORDER BY l_shipmode
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q12 на Polars."""
    lineitem = t["lineitem"].filter(  # Опоздавшие позиции 1994 года с нужными способами доставки.
        pl.col("l_shipmode").is_in(["MAIL", "SHIP"]),  # Только MAIL и SHIP.
        pl.col("l_commitdate") < pl.col("l_receiptdate"),  # Получено позже обещанного.
        pl.col("l_shipdate") < pl.col("l_commitdate"),  # Отгружено до обещанной даты.
        pl.col("l_receiptdate") >= date(1994, 1, 1),  # Получено с 01.01.1994...
        pl.col("l_receiptdate") < date(1995, 1, 1),  # ...по 31.12.1994.
    )
    is_high = pl.col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"])  # Выражение: заказ срочный (True/False).
    return (
        t["orders"].join(lineitem, left_on="o_orderkey", right_on="l_orderkey")  # Заказы + их позиции.
        .group_by("l_shipmode")  # GROUP BY l_shipmode.
        .agg(  # Сумма логических значений = число True (True считается как 1).
            is_high.sum().alias("high_line_count"),  # Позиции срочных заказов.
            (~is_high).sum().alias("low_line_count"),  # «~» — логическое НЕ: позиции несрочных заказов.
        )
        .sort("l_shipmode")  # ORDER BY l_shipmode.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q12",  # Имя для командной строки.
    tables=["lineitem", "orders"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["l_shipmode"],  # Способ доставки однозначно задаёт строку.
)
