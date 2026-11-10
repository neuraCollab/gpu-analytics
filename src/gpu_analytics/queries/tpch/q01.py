"""TPC-H Q1 «Pricing Summary Report» — сводный отчёт по ценам.

Смысл: отчёт по позициям заказов, отгруженным до 02.09.1998, сгруппированный
по флагу возврата и статусу позиции.
Что нагружает: сканирование большой таблицы lineitem + группировка с малым числом
групп (4) + много агрегатов. Типичная «отчётная» нагрузка.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from datetime import date  # Тип «дата» из стандартной библиотеки.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT
    l_returnflag,                                             -- флаг возврата (A, N, R)
    l_linestatus,                                             -- статус позиции (F, O)
    SUM(l_quantity)                                           AS sum_qty,         -- суммарное количество
    SUM(l_extendedprice)                                      AS sum_base_price,  -- суммарная цена
    SUM(l_extendedprice * (1 - l_discount))                   AS sum_disc_price,  -- цена со скидкой
    SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax))     AS sum_charge,      -- цена со скидкой и налогом
    AVG(l_quantity)                                           AS avg_qty,         -- среднее количество
    AVG(l_extendedprice)                                      AS avg_price,       -- средняя цена
    AVG(l_discount)                                           AS avg_disc,        -- средняя скидка
    COUNT(*)                                                  AS count_order      -- число позиций
FROM lineitem
WHERE l_shipdate <= DATE '1998-09-02'                         -- 1998-12-01 минус 90 дней
GROUP BY l_returnflag, l_linestatus
ORDER BY l_returnflag, l_linestatus
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q1 на Polars: то же самое, что SQL выше, но цепочкой методов."""
    disc_price = pl.col("l_extendedprice") * (1 - pl.col("l_discount"))  # Выражение «цена со скидкой» — используем дважды.
    return (
        t["lineitem"]  # Берём таблицу позиций заказов.
        .filter(pl.col("l_shipdate") <= date(1998, 9, 2))  # WHERE: только позиции, отгруженные не позже 02.09.1998.
        .group_by("l_returnflag", "l_linestatus")  # GROUP BY по флагу возврата и статусу.
        .agg(  # Агрегаты для каждой группы (аналог списка в SELECT).
            pl.col("l_quantity").sum().alias("sum_qty"),  # SUM(l_quantity).
            pl.col("l_extendedprice").sum().alias("sum_base_price"),  # SUM(l_extendedprice).
            disc_price.sum().alias("sum_disc_price"),  # SUM(цена со скидкой).
            (disc_price * (1 + pl.col("l_tax"))).sum().alias("sum_charge"),  # SUM(цена со скидкой и налогом).
            pl.col("l_quantity").mean().alias("avg_qty"),  # AVG(l_quantity).
            pl.col("l_extendedprice").mean().alias("avg_price"),  # AVG(l_extendedprice).
            pl.col("l_discount").mean().alias("avg_disc"),  # AVG(l_discount).
            pl.len().alias("count_order"),  # COUNT(*) — число строк в группе.
        )
        .sort("l_returnflag", "l_linestatus")  # ORDER BY.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q1",  # Имя для командной строки.
    tables=["lineitem"],  # Читает только lineitem.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["l_returnflag", "l_linestatus"],  # Ключ группировки однозначно задаёт строку.
)
