"""TPC-H Q21 «Suppliers Who Kept Orders Waiting» — поставщики, задержавшие заказы.

Смысл: саудовские поставщики, которые оказались ЕДИНСТВЕННЫМ опоздавшим поставщиком
в заказе с несколькими поставщиками.
Что нагружает: EXISTS и NOT EXISTS с условием «другой поставщик того же заказа» —
одна из самых сложных для оптимизатора конструкций в TPC-H.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT s_name,                                                 -- поставщик
       COUNT(*) AS numwait                                     -- сколько его позиций задержали заказы
FROM supplier, lineitem l1, orders, nation
WHERE s_suppkey = l1.l_suppkey                                 -- поставщик ↔ его позиция l1
  AND o_orderkey = l1.l_orderkey                               -- заказ ↔ позиция
  AND o_orderstatus = 'F'                                      -- заказ выполнен полностью
  AND l1.l_receiptdate > l1.l_commitdate                       -- позиция l1 опоздала
  AND EXISTS (                                                 -- в заказе есть позиция...
      SELECT * FROM lineitem l2
      WHERE l2.l_orderkey = l1.l_orderkey
        AND l2.l_suppkey <> l1.l_suppkey)                      -- ...ДРУГОГО поставщика
  AND NOT EXISTS (                                             -- и нет позиции...
      SELECT * FROM lineitem l3
      WHERE l3.l_orderkey = l1.l_orderkey
        AND l3.l_suppkey <> l1.l_suppkey                       -- ...другого поставщика...
        AND l3.l_receiptdate > l3.l_commitdate)                -- ...которая тоже опоздала
  AND s_nationkey = n_nationkey                                -- поставщик ↔ страна
  AND n_name = 'SAUDI ARABIA'                                  -- только Саудовская Аравия
GROUP BY s_name
ORDER BY numwait DESC, s_name
LIMIT 100
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q21 на Polars.

    Подзапросы переформулированы через число уникальных поставщиков в заказе:
      * EXISTS «есть другой поставщик» ⇔ в заказе больше одного уникального поставщика;
      * NOT EXISTS «другой поставщик тоже опоздал» ⇔ среди опоздавших позиций заказа
        ровно один уникальный поставщик (это сам поставщик позиции l1, ведь l1 опоздала).
    """
    late = t["lineitem"].filter(pl.col("l_receiptdate") > pl.col("l_commitdate"))  # Все опоздавшие позиции.
    multi_supplier_orders = (  # Заказы, в которых больше одного поставщика (условие EXISTS).
        t["lineitem"].group_by("l_orderkey")  # Группируем все позиции по заказу.
        .agg(pl.col("l_suppkey").n_unique().alias("n_suppliers"))  # Число уникальных поставщиков в заказе.
        .filter(pl.col("n_suppliers") > 1)  # Больше одного.
    )
    single_late_orders = (  # Заказы, где опоздал ровно один поставщик (условие NOT EXISTS).
        late.group_by("l_orderkey")  # Группируем опоздавшие позиции по заказу.
        .agg(pl.col("l_suppkey").n_unique().alias("n_late_suppliers"))  # Число уникальных опоздавших поставщиков.
        .filter(pl.col("n_late_suppliers") == 1)  # Ровно один.
    )
    saudi_suppliers = (  # Поставщики из Саудовской Аравии.
        t["nation"].filter(pl.col("n_name") == "SAUDI ARABIA")  # Страна.
        .join(t["supplier"], left_on="n_nationkey", right_on="s_nationkey")  # Её поставщики.
    )
    finished_orders = t["orders"].filter(pl.col("o_orderstatus") == "F")  # Полностью выполненные заказы.
    return (
        late  # Опоздавшие позиции — это l1 из SQL.
        .join(multi_supplier_orders, on="l_orderkey", how="semi")  # EXISTS: в заказе есть другой поставщик.
        .join(single_late_orders, on="l_orderkey", how="semi")  # NOT EXISTS: больше никто не опоздал.
        .join(finished_orders, left_on="l_orderkey", right_on="o_orderkey", how="semi")  # Заказ со статусом F.
        .join(saudi_suppliers, left_on="l_suppkey", right_on="s_suppkey")  # Поставщик из Саудовской Аравии (+ его имя).
        .group_by("s_name")  # GROUP BY s_name.
        .agg(pl.len().alias("numwait"))  # COUNT(*).
        .sort("numwait", "s_name", descending=[True, False])  # ORDER BY numwait DESC, s_name.
        .head(100)  # LIMIT 100.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q21",  # Имя для командной строки.
    tables=["lineitem", "nation", "orders", "supplier"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["s_name"],  # Имя поставщика уникально.
)
