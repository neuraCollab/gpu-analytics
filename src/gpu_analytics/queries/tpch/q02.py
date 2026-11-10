"""TPC-H Q2 «Minimum Cost Supplier» — поставщик с минимальной ценой.

Смысл: для латунных (BRASS) деталей размера 15 найти европейского поставщика,
который продаёт деталь дешевле всех; показать 100 таких поставщиков с наибольшим балансом.
Что нагружает: соединения пяти таблиц + коррелированный подзапрос (минимум по детали).
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT s_acctbal, s_name, n_name, p_partkey, p_mfgr,          -- баланс и имя поставщика, страна, деталь, производитель
       s_address, s_phone, s_comment                           -- контакты поставщика
FROM part, supplier, partsupp, nation, region
WHERE p_partkey = ps_partkey                                   -- деталь ↔ предложение поставщика
  AND s_suppkey = ps_suppkey                                   -- поставщик ↔ его предложение
  AND p_size = 15                                              -- размер детали 15
  AND p_type LIKE '%BRASS'                                     -- тип детали заканчивается на BRASS
  AND s_nationkey = n_nationkey                                -- поставщик ↔ страна
  AND n_regionkey = r_regionkey                                -- страна ↔ регион
  AND r_name = 'EUROPE'                                        -- только Европа
  AND ps_supplycost = (                                        -- цена равна минимальной...
      SELECT MIN(ps_supplycost)                                -- ...минимальная цена этой детали...
      FROM partsupp, supplier, nation, region
      WHERE p_partkey = ps_partkey                             -- ...для той же детали (коррелированный подзапрос)...
        AND s_suppkey = ps_suppkey
        AND s_nationkey = n_nationkey
        AND n_regionkey = r_regionkey
        AND r_name = 'EUROPE')                                 -- ...среди европейских поставщиков
ORDER BY s_acctbal DESC, n_name, s_name, p_partkey             -- сначала самые «богатые» поставщики
LIMIT 100                                                      -- первые 100 строк
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q2 на Polars: коррелированный подзапрос заменяем на «минимум по группе + соединение»."""
    european_offers = (  # Все предложения (partsupp) европейских поставщиков вместе со страной.
        t["region"]  # Начинаем с регионов.
        .filter(pl.col("r_name") == "EUROPE")  # Оставляем только Европу.
        .join(t["nation"], left_on="r_regionkey", right_on="n_regionkey")  # Страны Европы.
        .join(t["supplier"], left_on="n_nationkey", right_on="s_nationkey")  # Поставщики из этих стран.
        .join(t["partsupp"], left_on="s_suppkey", right_on="ps_suppkey")  # Их предложения деталей.
    )
    offers = (  # Предложения только для нужных деталей.
        t["part"]  # Таблица деталей.
        .filter(pl.col("p_size") == 15, pl.col("p_type").str.ends_with("BRASS"))  # Размер 15 и тип «…BRASS».
        .join(european_offers, left_on="p_partkey", right_on="ps_partkey")  # Добавляем европейские предложения этих деталей.
    )
    min_cost = (  # Это и есть подзапрос: минимальная цена каждой детали среди европейцев.
        offers.group_by("p_partkey")  # Группируем по детали.
        .agg(pl.col("ps_supplycost").min().alias("min_cost"))  # Минимальная цена в группе.
    )
    return (
        offers.join(min_cost, on="p_partkey")  # К каждому предложению приписываем минимальную цену его детали.
        .filter(pl.col("ps_supplycost") == pl.col("min_cost"))  # Оставляем предложения с минимальной ценой.
        .select("s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment")  # Колонки как в SQL.
        .sort(  # ORDER BY s_acctbal DESC, n_name, s_name, p_partkey.
            "s_acctbal", "n_name", "s_name", "p_partkey",  # Колонки сортировки по порядку.
            descending=[True, False, False, False],  # Только s_acctbal — по убыванию.
        )
        .head(100)  # LIMIT 100.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q2",  # Имя для командной строки.
    tables=["nation", "part", "partsupp", "region", "supplier"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["p_partkey", "s_name"],  # Пара «деталь + поставщик» однозначно задаёт строку.
)
