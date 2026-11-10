"""NYC Taxi N3 — 20 районов посадки с наибольшей выручкой.

Что нагружает: соединение большой таблицы (41 млн строк) с маленьким справочником
(265 строк) + группировка + top-20. Типичная «звезда» из хранилища данных:
таблица фактов + таблица-измерение.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT z.location_id, z.borough, z.zone,                       -- район посадки
       COUNT(*)            AS trips,                           -- число поездок оттуда
       SUM(t.total_amount) AS revenue                          -- выручка
FROM trips t
JOIN zones z ON t.pu_location_id = z.location_id               -- поездка ↔ район посадки
GROUP BY z.location_id, z.borough, z.zone
ORDER BY revenue DESC
LIMIT 20
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """N3 на Polars."""
    return (
        # Начинаем со справочника: тогда в результате останется ключ location_id (ключ левой таблицы).
        t["zones"].join(t["trips"], left_on="location_id", right_on="pu_location_id")  # Район + его поездки.
        .group_by("location_id", "borough", "zone")  # GROUP BY.
        .agg(  # Агрегаты по району.
            pl.len().alias("trips"),  # COUNT(*).
            pl.col("total_amount").sum().alias("revenue"),  # SUM(total_amount).
        )
        .sort("revenue", descending=True)  # ORDER BY revenue DESC.
        .head(20)  # LIMIT 20.
    )


QUERY = Query(  # Собираем описание запроса.
    name="n3",  # Имя для командной строки.
    tables=["trips", "zones"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["location_id"],  # Номер района однозначно задаёт строку.
)
