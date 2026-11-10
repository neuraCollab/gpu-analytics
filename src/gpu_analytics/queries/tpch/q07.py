"""TPC-H Q7 «Volume Shipping» — объём перевозок между странами.

Смысл: выручка от поставок между Францией и Германией (в обе стороны)
по годам 1995 и 1996.
Что нагружает: соединение с одной и той же таблицей nation дважды (страна поставщика
и страна клиента) + извлечение года из даты.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from datetime import date  # Тип «дата».

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT supp_nation, cust_nation, l_year,                       -- страна поставщика, страна клиента, год
       SUM(volume) AS revenue                                  -- выручка
FROM (
    SELECT n1.n_name AS supp_nation,                           -- n1 — страна поставщика
           n2.n_name AS cust_nation,                           -- n2 — страна клиента
           EXTRACT(year FROM l_shipdate) AS l_year,            -- год отгрузки
           l_extendedprice * (1 - l_discount) AS volume        -- выручка позиции со скидкой
    FROM supplier, lineitem, orders, customer, nation n1, nation n2
    WHERE s_suppkey = l_suppkey                                -- поставщик ↔ позиция
      AND o_orderkey = l_orderkey                              -- заказ ↔ позиция
      AND c_custkey = o_custkey                                -- клиент ↔ заказ
      AND s_nationkey = n1.n_nationkey                         -- страна поставщика
      AND c_nationkey = n2.n_nationkey                         -- страна клиента
      AND ((n1.n_name = 'FRANCE' AND n2.n_name = 'GERMANY')    -- из Франции в Германию...
        OR (n1.n_name = 'GERMANY' AND n2.n_name = 'FRANCE'))   -- ...или из Германии во Францию
      AND l_shipdate BETWEEN DATE '1995-01-01' AND DATE '1996-12-31'  -- отгрузки 1995–1996 годов
) AS shipping
GROUP BY supp_nation, cust_nation, l_year
ORDER BY supp_nation, cust_nation, l_year
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q7 на Polars."""
    pair = ["FRANCE", "GERMANY"]  # Две страны, между которыми считаем перевозки.
    supp_nation = (  # Первая «копия» nation — для страны поставщика (колонки переименованы, чтобы не путать).
        t["nation"].filter(pl.col("n_name").is_in(pair))  # Только Франция и Германия.
        .select(pl.col("n_nationkey").alias("supp_nationkey"), pl.col("n_name").alias("supp_nation"))  # Переименование.
    )
    cust_nation = (  # Вторая «копия» nation — для страны клиента.
        t["nation"].filter(pl.col("n_name").is_in(pair))  # Только Франция и Германия.
        .select(pl.col("n_nationkey").alias("cust_nationkey"), pl.col("n_name").alias("cust_nation"))  # Переименование.
    )
    lineitem = t["lineitem"].filter(  # Позиции, отгруженные в 1995–1996 годах.
        pl.col("l_shipdate").is_between(date(1995, 1, 1), date(1996, 12, 31))  # BETWEEN включает обе границы.
    )
    return (
        lineitem.join(t["supplier"], left_on="l_suppkey", right_on="s_suppkey")  # + поставщик (нужна s_nationkey).
        .join(t["orders"], left_on="l_orderkey", right_on="o_orderkey")  # + заказ (нужен o_custkey).
        .join(t["customer"], left_on="o_custkey", right_on="c_custkey")  # + клиент (нужна c_nationkey).
        .join(supp_nation, left_on="s_nationkey", right_on="supp_nationkey")  # Поставщик из Франции или Германии.
        .join(cust_nation, left_on="c_nationkey", right_on="cust_nationkey")  # Клиент из Франции или Германии.
        # Обе страны из пары {FRANCE, GERMANY} и при этом разные — это ровно условие
        # «(FRANCE→GERMANY) или (GERMANY→FRANCE)» из SQL.
        .filter(pl.col("supp_nation") != pl.col("cust_nation"))
        .group_by(  # GROUP BY.
            "supp_nation",  # Страна поставщика.
            "cust_nation",  # Страна клиента.
            pl.col("l_shipdate").dt.year().alias("l_year"),  # EXTRACT(year FROM l_shipdate).
        )
        .agg((pl.col("l_extendedprice") * (1 - pl.col("l_discount"))).sum().alias("revenue"))  # SUM(volume).
        .sort("supp_nation", "cust_nation", "l_year")  # ORDER BY.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q7",  # Имя для командной строки.
    tables=["customer", "lineitem", "nation", "orders", "supplier"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["supp_nation", "cust_nation", "l_year"],  # Ключ группировки однозначно задаёт строку.
)
