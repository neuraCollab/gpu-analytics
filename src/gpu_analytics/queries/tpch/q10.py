"""TPC-H Q10 «Returned Item Reporting» — отчёт о возвратах.

Смысл: 20 клиентов, вернувших товаров на самую большую сумму в 4-м квартале 1993 года.
Что нагружает: соединение четырёх таблиц + группировка по многим колонкам
(в том числе длинным строкам: адрес, комментарий) + top-20.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from datetime import date  # Тип «дата».

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT c_custkey, c_name,                                      -- клиент
       SUM(l_extendedprice * (1 - l_discount)) AS revenue,     -- сумма возвращённого товара
       c_acctbal, n_name, c_address, c_phone, c_comment        -- баланс, страна и контакты клиента
FROM customer, orders, lineitem, nation
WHERE c_custkey = o_custkey                                    -- клиент ↔ заказ
  AND l_orderkey = o_orderkey                                  -- заказ ↔ позиции
  AND o_orderdate >= DATE '1993-10-01'                         -- заказы 4-го квартала 1993 года
  AND o_orderdate <  DATE '1994-01-01'                         -- (1993-10-01 + 3 месяца)
  AND l_returnflag = 'R'                                       -- позиция возвращена
  AND c_nationkey = n_nationkey                                -- клиент ↔ страна
GROUP BY c_custkey, c_name, c_acctbal, c_phone, n_name, c_address, c_comment
ORDER BY revenue DESC
LIMIT 20
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q10 на Polars."""
    orders = t["orders"].filter(  # Заказы 4-го квартала 1993 года.
        pl.col("o_orderdate") >= date(1993, 10, 1),  # С 01.10.1993.
        pl.col("o_orderdate") < date(1994, 1, 1),  # До 01.01.1994.
    )
    returned = t["lineitem"].filter(pl.col("l_returnflag") == "R")  # Возвращённые позиции.
    return (
        # Начинаем с customer, чтобы в результате остался ключ c_custkey (ключ левой таблицы).
        t["customer"].join(orders, left_on="c_custkey", right_on="o_custkey")  # Клиенты + их заказы.
        .join(returned, left_on="o_orderkey", right_on="l_orderkey")  # + возвращённые позиции.
        .join(t["nation"], left_on="c_nationkey", right_on="n_nationkey")  # + страна клиента.
        .group_by("c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment")  # GROUP BY.
        .agg((pl.col("l_extendedprice") * (1 - pl.col("l_discount"))).sum().alias("revenue"))  # Сумма возвратов.
        .select("c_custkey", "c_name", "revenue", "c_acctbal", "n_name", "c_address", "c_phone", "c_comment")  # Порядок как в SQL.
        .sort("revenue", descending=True)  # ORDER BY revenue DESC.
        .head(20)  # LIMIT 20.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q10",  # Имя для командной строки.
    tables=["customer", "lineitem", "nation", "orders"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["c_custkey"],  # Клиент однозначно задаёт строку.
)
