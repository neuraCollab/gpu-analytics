"""TPC-H Q19 «Discounted Revenue» — выручка со скидкой.

Смысл: выручка от трёх групп товаров (по бренду, упаковке, размеру и количеству),
доставленных воздухом и вручённых лично.
Что нагружает: сложное условие из трёх веток, соединённых OR, по колонкам двух таблиц.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables, sql_sum  # Описание запроса, тип «таблицы Polars», SUM как в SQL.

SQL = """
SELECT SUM(l_extendedprice * (1 - l_discount)) AS revenue      -- выручка со скидкой
FROM lineitem, part
WHERE (    p_partkey = l_partkey                               -- ветка 1: мелкие упаковки
       AND p_brand = 'Brand#12'
       AND p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG')
       AND l_quantity >= 1 AND l_quantity <= 1 + 10
       AND p_size BETWEEN 1 AND 5
       AND l_shipmode IN ('AIR', 'AIR REG')
       AND l_shipinstruct = 'DELIVER IN PERSON')
   OR (    p_partkey = l_partkey                               -- ветка 2: средние упаковки
       AND p_brand = 'Brand#23'
       AND p_container IN ('MED BAG', 'MED BOX', 'MED PKG', 'MED PACK')
       AND l_quantity >= 10 AND l_quantity <= 10 + 10
       AND p_size BETWEEN 1 AND 10
       AND l_shipmode IN ('AIR', 'AIR REG')
       AND l_shipinstruct = 'DELIVER IN PERSON')
   OR (    p_partkey = l_partkey                               -- ветка 3: крупные упаковки
       AND p_brand = 'Brand#34'
       AND p_container IN ('LG CASE', 'LG BOX', 'LG PACK', 'LG PKG')
       AND l_quantity >= 20 AND l_quantity <= 20 + 10
       AND p_size BETWEEN 1 AND 15
       AND l_shipmode IN ('AIR', 'AIR REG')
       AND l_shipinstruct = 'DELIVER IN PERSON')
"""


def branch(brand: str, containers: list[str], min_qty: int, max_size: int) -> pl.Expr:
    """Одна ветка условия: бренд, упаковка, диапазон количества и размера."""
    return (
        (pl.col("p_brand") == brand)  # Бренд детали.
        & pl.col("p_container").is_in(containers)  # Упаковка — одна из четырёх.
        & pl.col("l_quantity").is_between(min_qty, min_qty + 10)  # Количество от min_qty до min_qty + 10 включительно.
        & pl.col("p_size").is_between(1, max_size)  # Размер от 1 до max_size включительно.
    )  # «&» — логическое И для выражений Polars (слово and здесь не работает).


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q19 на Polars."""
    # Условия про способ доставки и вручение одинаковы во всех трёх ветках — выносим их
    # в общий фильтр до соединения: так в соединение попадёт гораздо меньше строк.
    lineitem = t["lineitem"].filter(
        pl.col("l_shipmode").is_in(["AIR", "AIR REG"]),  # Доставка воздухом.
        pl.col("l_shipinstruct") == "DELIVER IN PERSON",  # Вручить лично.
    )
    return (
        lineitem.join(t["part"], left_on="l_partkey", right_on="p_partkey")  # Позиции + детали.
        .filter(  # «|» — логическое ИЛИ: подходит любая из трёх веток.
            branch("Brand#12", ["SM CASE", "SM BOX", "SM PACK", "SM PKG"], min_qty=1, max_size=5)  # Ветка 1.
            | branch("Brand#23", ["MED BAG", "MED BOX", "MED PKG", "MED PACK"], min_qty=10, max_size=10)  # Ветка 2.
            | branch("Brand#34", ["LG CASE", "LG BOX", "LG PACK", "LG PKG"], min_qty=20, max_size=15)  # Ветка 3.
        )
        .select(sql_sum(pl.col("l_extendedprice") * (1 - pl.col("l_discount"))).alias("revenue"))  # Выручка (NULL, если строк нет — как в SQL).
    )


QUERY = Query(  # Собираем описание запроса.
    name="q19",  # Имя для командной строки.
    tables=["lineitem", "part"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=[],  # Одна строка в ответе.
)
