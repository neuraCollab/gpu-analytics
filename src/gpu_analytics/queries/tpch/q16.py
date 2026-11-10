"""TPC-H Q16 «Parts/Supplier Relationship» — детали и поставщики.

Смысл: сколько разных поставщиков (без тех, на кого жаловались клиенты) может
поставить детали с заданными характеристиками.
Что нагружает: NOT IN с подзапросом (антисоединение), подсчёт уникальных значений
(COUNT DISTINCT) и группировку по строковым колонкам.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SIZES = [49, 14, 23, 45, 19, 3, 36, 9]  # Размеры деталей — стандартные значения параметров из спецификации.

SQL = """
SELECT p_brand, p_type, p_size,                                -- характеристики детали
       COUNT(DISTINCT ps_suppkey) AS supplier_cnt              -- число РАЗНЫХ поставщиков
FROM partsupp, part
WHERE p_partkey = ps_partkey                                   -- деталь ↔ предложение
  AND p_brand <> 'Brand#45'                                    -- кроме бренда Brand#45
  AND p_type NOT LIKE 'MEDIUM POLISHED%'                       -- тип не начинается с MEDIUM POLISHED
  AND p_size IN (49, 14, 23, 45, 19, 3, 36, 9)                 -- один из восьми размеров
  AND ps_suppkey NOT IN (                                      -- поставщик НЕ из списка...
      SELECT s_suppkey FROM supplier
      WHERE s_comment LIKE '%Customer%Complaints%')            -- ...тех, на кого жаловались
GROUP BY p_brand, p_type, p_size
ORDER BY supplier_cnt DESC, p_brand, p_type, p_size
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q16 на Polars: NOT IN = антисоединение (how="anti")."""
    complained = t["supplier"].filter(pl.col("s_comment").str.contains("Customer.*Complaints"))  # Поставщики с жалобами.
    parts = t["part"].filter(  # Детали с нужными характеристиками.
        pl.col("p_brand") != "Brand#45",  # Не бренд Brand#45.
        ~pl.col("p_type").str.starts_with("MEDIUM POLISHED"),  # Тип не начинается с MEDIUM POLISHED.
        pl.col("p_size").is_in(SIZES),  # Размер из списка.
    )
    return (
        t["partsupp"]  # Предложения поставщиков.
        # Антисоединение: оставить строки, для которых НЕТ пары в другой таблице (= NOT IN / NOT EXISTS).
        .join(complained, left_on="ps_suppkey", right_on="s_suppkey", how="anti")
        .join(parts, left_on="ps_partkey", right_on="p_partkey")  # + характеристики деталей (и фильтр по ним).
        .group_by("p_brand", "p_type", "p_size")  # GROUP BY.
        .agg(pl.col("ps_suppkey").n_unique().alias("supplier_cnt"))  # n_unique() — число уникальных значений (COUNT DISTINCT).
        .sort(  # ORDER BY supplier_cnt DESC, p_brand, p_type, p_size.
            "supplier_cnt", "p_brand", "p_type", "p_size",  # Колонки сортировки.
            descending=[True, False, False, False],  # Только supplier_cnt — по убыванию.
        )
    )


QUERY = Query(  # Собираем описание запроса.
    name="q16",  # Имя для командной строки.
    tables=["part", "partsupp", "supplier"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["p_brand", "p_type", "p_size"],  # Ключ группировки однозначно задаёт строку.
)
