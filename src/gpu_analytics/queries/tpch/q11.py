"""TPC-H Q11 «Important Stock Identification» — важные складские запасы.

Смысл: детали, запас которых у немецких поставщиков стоит больше 0,01% стоимости
всего немецкого запаса.
Что нагружает: группировка + условие HAVING со скалярным подзапросом (общая сумма).

Про параметр 0.0001: по спецификации доля равна 0.0001 / SF. Мы берём 0.0001 при любом SF:
для сравнения движков важно лишь, что все они считают один и тот же запрос. На SF ≠ 1
ответ просто содержит больше строк, чем «официальный».
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT ps_partkey,                                             -- деталь
       SUM(ps_supplycost * ps_availqty) AS value               -- стоимость её запаса у немецких поставщиков
FROM partsupp, supplier, nation
WHERE ps_suppkey = s_suppkey                                   -- предложение ↔ поставщик
  AND s_nationkey = n_nationkey                                -- поставщик ↔ страна
  AND n_name = 'GERMANY'                                       -- только Германия
GROUP BY ps_partkey
HAVING SUM(ps_supplycost * ps_availqty) > (                    -- оставить детали дороже порога...
    SELECT SUM(ps_supplycost * ps_availqty) * 0.0001           -- ...порог = 0,01% всего немецкого запаса
    FROM partsupp, supplier, nation
    WHERE ps_suppkey = s_suppkey
      AND s_nationkey = n_nationkey
      AND n_name = 'GERMANY')
ORDER BY value DESC
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """Q11 на Polars: скалярный подзапрос считаем отдельно и «приклеиваем» перекрёстным соединением."""
    german_stock = (  # Предложения немецких поставщиков со стоимостью запаса.
        t["nation"].filter(pl.col("n_name") == "GERMANY")  # Страна «Германия».
        .join(t["supplier"], left_on="n_nationkey", right_on="s_nationkey")  # Её поставщики.
        .join(t["partsupp"], left_on="s_suppkey", right_on="ps_suppkey")  # Их предложения.
        .with_columns((pl.col("ps_supplycost") * pl.col("ps_availqty")).alias("value"))  # Стоимость запаса = цена × количество.
    )
    threshold = german_stock.select((pl.col("value").sum() * 0.0001).alias("threshold"))  # Подзапрос: одна строка с порогом.
    return (
        german_stock.group_by("ps_partkey")  # GROUP BY ps_partkey.
        .agg(pl.col("value").sum())  # SUM(стоимость) по детали; имя колонки остаётся value.
        .join(threshold, how="cross")  # Перекрёстное соединение с одной строкой = добавить порог в каждую строку.
        .filter(pl.col("value") > pl.col("threshold"))  # HAVING value > порог.
        .select("ps_partkey", "value")  # Убираем служебную колонку threshold.
        .sort("value", descending=True)  # ORDER BY value DESC.
    )


QUERY = Query(  # Собираем описание запроса.
    name="q11",  # Имя для командной строки.
    tables=["nation", "partsupp", "supplier"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["ps_partkey"],  # Деталь однозначно задаёт строку.
)
