"""TPC-H Q22 «Global Sales Opportunity» — потенциальные клиенты.

Смысл: клиенты из семи стран (по коду в номере телефона), у которых на счету больше
среднего, но которые ни разу ничего не заказывали.
Что нагружает: работа с подстроками, скалярный подзапрос (среднее) и NOT EXISTS.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

COUNTRY_CODES = ["13", "31", "23", "29", "30", "18", "17"]  # Коды стран — стандартные значения параметров.

SQL = """
SELECT cntrycode,                                              -- код страны
       COUNT(*) AS numcust,                                    -- число таких клиентов
       SUM(c_acctbal) AS totacctbal                            -- их суммарный баланс
FROM (
    SELECT SUBSTRING(c_phone, 1, 2) AS cntrycode,              -- первые 2 символа телефона = код страны
           c_acctbal
    FROM customer
    WHERE SUBSTRING(c_phone, 1, 2) IN ('13', '31', '23', '29', '30', '18', '17')  -- одна из семи стран
      AND c_acctbal > (                                        -- баланс больше...
          SELECT AVG(c_acctbal) FROM customer                  -- ...среднего баланса...
          WHERE c_acctbal > 0.00                               -- ...среди клиентов с положительным балансом...
            AND SUBSTRING(c_phone, 1, 2) IN ('13', '31', '23', '29', '30', '18', '17'))  -- ...из тех же стран
      AND NOT EXISTS (                                         -- и у клиента нет...
          SELECT * FROM orders
          WHERE o_custkey = c_custkey)                         -- ...ни одного заказа
) AS custsale
GROUP BY cntrycode
ORDER BY cntrycode
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q22 на Polars."""
    customers = (  # Клиенты из семи стран вместе с кодом страны.
        t["customer"]  # Таблица клиентов.
        .with_columns(pl.col("c_phone").str.slice(0, 2).alias("cntrycode"))  # Подстрока: с позиции 0 (в SQL — с 1) длиной 2.
        .filter(pl.col("cntrycode").is_in(COUNTRY_CODES))  # Только нужные страны.
    )
    average = (  # Скалярный подзапрос: средний положительный баланс (одна строка, одна колонка).
        customers.filter(pl.col("c_acctbal") > 0.0)  # Только положительные балансы.
        .select(pl.col("c_acctbal").mean().alias("avg_acctbal"))  # Среднее.
    )
    return (
        customers.join(t["orders"], left_on="c_custkey", right_on="o_custkey", how="anti")  # NOT EXISTS: клиенты без заказов.
        .join(average, how="cross")  # Добавляем среднее в каждую строку.
        .filter(pl.col("c_acctbal") > pl.col("avg_acctbal"))  # Баланс больше среднего.
        .group_by("cntrycode")  # GROUP BY cntrycode.
        .agg(  # Агрегаты по стране.
            pl.len().alias("numcust"),  # COUNT(*).
            pl.col("c_acctbal").sum().alias("totacctbal"),  # SUM(c_acctbal).
        )
        .sort("cntrycode")  # ORDER BY cntrycode.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q22",  # Имя для командной строки.
    tables=["customer", "orders"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["cntrycode"],  # Код страны однозначно задаёт строку.
)
