"""TPC-H Q8 «National Market Share» — доля страны на рынке.

Смысл: какую долю рынка деталей типа ECONOMY ANODIZED STEEL в Америке занимали
поставщики из Бразилии в 1995 и 1996 годах.
Что нагружает: соединение восьми таблиц (самое широкое в TPC-H) + условная сумма (CASE).
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from datetime import date  # Тип «дата».

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT o_year,                                                 -- год заказа
       SUM(CASE WHEN nation = 'BRAZIL' THEN volume ELSE 0 END) -- выручка бразильских поставщиков...
         / SUM(volume) AS mkt_share                            -- ...делённая на всю выручку = доля рынка
FROM (
    SELECT EXTRACT(year FROM o_orderdate) AS o_year,           -- год заказа
           l_extendedprice * (1 - l_discount) AS volume,       -- выручка позиции
           n2.n_name AS nation                                 -- страна ПОСТАВЩИКА
    FROM part, supplier, lineitem, orders, customer, nation n1, nation n2, region
    WHERE p_partkey = l_partkey                                -- деталь ↔ позиция
      AND s_suppkey = l_suppkey                                -- поставщик ↔ позиция
      AND l_orderkey = o_orderkey                              -- заказ ↔ позиция
      AND o_custkey = c_custkey                                -- клиент ↔ заказ
      AND c_nationkey = n1.n_nationkey                         -- n1 — страна КЛИЕНТА...
      AND n1.n_regionkey = r_regionkey                         -- ...её регион...
      AND r_name = 'AMERICA'                                   -- ...должен быть Америкой
      AND s_nationkey = n2.n_nationkey                         -- n2 — страна поставщика
      AND o_orderdate BETWEEN DATE '1995-01-01' AND DATE '1996-12-31'  -- заказы 1995–1996 годов
      AND p_type = 'ECONOMY ANODIZED STEEL'                    -- только этот тип деталей
) AS all_nations
GROUP BY o_year
ORDER BY o_year
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q8 на Polars."""
    american_nations = (  # Ключи стран Америки (для фильтра клиентов).
        t["region"].filter(pl.col("r_name") == "AMERICA")  # Регион «Америка».
        .join(t["nation"], left_on="r_regionkey", right_on="n_regionkey")  # Его страны.
        .select("n_nationkey")  # Нужны только ключи стран.
    )
    supp_nation = t["nation"].select(  # Копия nation для страны поставщика.
        pl.col("n_nationkey").alias("supp_nationkey"),  # Ключ страны поставщика.
        pl.col("n_name").alias("nation"),  # Название — как колонка nation в SQL.
    )
    parts = t["part"].filter(pl.col("p_type") == "ECONOMY ANODIZED STEEL")  # Только нужный тип деталей.
    orders = t["orders"].filter(  # Заказы 1995–1996 годов.
        pl.col("o_orderdate").is_between(date(1995, 1, 1), date(1996, 12, 31))  # Обе границы включены.
    )
    volume = pl.col("l_extendedprice") * (1 - pl.col("l_discount"))  # Выражение «выручка позиции».
    return (
        t["lineitem"]  # Позиции заказов.
        .join(parts, left_on="l_partkey", right_on="p_partkey", how="semi")  # Только позиции с нужными деталями.
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")  # + заказы 1995–1996 (нужны дата и клиент).
        .join(t["customer"], left_on="o_custkey", right_on="c_custkey")  # + клиент (нужна его страна).
        .join(american_nations, left_on="c_nationkey", right_on="n_nationkey", how="semi")  # Только клиенты из Америки.
        .join(t["supplier"], left_on="l_suppkey", right_on="s_suppkey")  # + поставщик (нужна его страна).
        .join(supp_nation, left_on="s_nationkey", right_on="supp_nationkey")  # + название страны поставщика.
        .group_by(pl.col("o_orderdate").dt.year().alias("o_year"))  # GROUP BY год заказа.
        .agg(  # Доля рынка в каждом году.
            (
                pl.when(pl.col("nation") == "BRAZIL").then(volume).otherwise(0).sum()  # CASE WHEN … — выручка Бразилии.
                / volume.sum()  # Делим на всю выручку.
            ).alias("mkt_share")
        )
        .sort("o_year")  # ORDER BY o_year.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q8",  # Имя для командной строки.
    tables=["customer", "lineitem", "nation", "orders", "part", "region", "supplier"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["o_year"],  # Год однозначно задаёт строку.
)
