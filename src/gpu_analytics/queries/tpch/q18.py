"""TPC-H Q18 «Large Volume Customer» — крупные клиенты.

Смысл: 100 самых дорогих заказов, в которых суммарно заказано больше 300 единиц товара.
Что нагружает: группировка всей таблицы lineitem по заказу (очень много групп) +
подзапрос IN + соединения + top-100.

Отличие от спецификации: колонка SUM(l_quantity) получила имя sum_quantity
(в спецификации у неё нет имени, а разные движки называют её по-разному).
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice,  -- клиент и заказ
       SUM(l_quantity) AS sum_quantity                         -- сколько единиц в заказе
FROM customer, orders, lineitem
WHERE o_orderkey IN (                                          -- заказ входит в список...
      SELECT l_orderkey FROM lineitem
      GROUP BY l_orderkey
      HAVING SUM(l_quantity) > 300)                            -- ...заказов больше чем на 300 единиц
  AND c_custkey = o_custkey                                    -- клиент ↔ заказ
  AND o_orderkey = l_orderkey                                  -- заказ ↔ позиции
GROUP BY c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice
ORDER BY o_totalprice DESC, o_orderdate
LIMIT 100
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q18 на Polars."""
    big_orders = (  # Подзапрос: заказы больше чем на 300 единиц вместе с их суммой.
        t["lineitem"].group_by("l_orderkey")  # Группируем позиции по заказу.
        .agg(pl.col("l_quantity").sum().alias("sum_quantity"))  # Сумма количества в заказе.
        .filter(pl.col("sum_quantity") > 300)  # HAVING SUM(l_quantity) > 300.
    )
    # Упрощение: внешний SUM(l_quantity) в SQL — это та же сумма по позициям заказа,
    # что уже посчитана в big_orders. Поэтому второй раз соединять с lineitem не нужно.
    return (
        t["customer"].join(t["orders"], left_on="c_custkey", right_on="o_custkey")  # Клиенты + их заказы (ключ c_custkey остаётся).
        .join(big_orders, left_on="o_orderkey", right_on="l_orderkey")  # Только крупные заказы (+ их сумма).
        .select("c_name", "c_custkey", "o_orderkey", "o_orderdate", "o_totalprice", "sum_quantity")  # Колонки как в SQL.
        .sort("o_totalprice", "o_orderdate", descending=[True, False])  # ORDER BY o_totalprice DESC, o_orderdate.
        .head(100)  # LIMIT 100.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q18",  # Имя для командной строки.
    tables=["customer", "lineitem", "orders"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["o_orderkey"],  # Заказ однозначно задаёт строку.
)
