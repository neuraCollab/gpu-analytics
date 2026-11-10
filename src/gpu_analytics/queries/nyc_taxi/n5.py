"""NYC Taxi N5 — потоки поездок между боро.

Смысл: сколько поездок идёт из каждого боро (Manhattan, Brooklyn, Queens, …) в каждое,
какое у них среднее расстояние и средний тариф.
Что нагружает: два соединения большой таблицы с одним и тем же справочником
(для района посадки и района высадки) + группировка по паре строк. Аналог TPC-H Q7.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT pz.borough AS pu_borough,                               -- боро посадки
       dz.borough AS do_borough,                               -- боро высадки
       COUNT(*)             AS trips,                          -- число поездок
       AVG(t.trip_distance) AS avg_distance,                   -- среднее расстояние, мили
       AVG(t.fare_amount)   AS avg_fare                        -- средний тариф, $
FROM trips t
JOIN zones pz ON t.pu_location_id = pz.location_id             -- pz — справочник в роли «район посадки»
JOIN zones dz ON t.do_location_id = dz.location_id             -- dz — тот же справочник в роли «район высадки»
GROUP BY pz.borough, dz.borough
ORDER BY trips DESC
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """N5 на Polars: две «копии» справочника с переименованными колонками."""
    pickup_zones = t["zones"].select(  # Справочник в роли «район посадки».
        pl.col("location_id").alias("pu_id"),  # Ключ.
        pl.col("borough").alias("pu_borough"),  # Боро посадки.
    )
    dropoff_zones = t["zones"].select(  # Справочник в роли «район высадки».
        pl.col("location_id").alias("do_id"),  # Ключ.
        pl.col("borough").alias("do_borough"),  # Боро высадки.
    )
    return (
        t["trips"]  # Таблица поездок.
        .join(pickup_zones, left_on="pu_location_id", right_on="pu_id")  # + боро посадки.
        .join(dropoff_zones, left_on="do_location_id", right_on="do_id")  # + боро высадки.
        .group_by("pu_borough", "do_borough")  # GROUP BY пары боро.
        .agg(  # Агрегаты по паре.
            pl.len().alias("trips"),  # COUNT(*).
            pl.col("trip_distance").mean().alias("avg_distance"),  # AVG(trip_distance).
            pl.col("fare_amount").mean().alias("avg_fare"),  # AVG(fare_amount).
        )
        .sort("trips", descending=True)  # ORDER BY trips DESC.
    )


QUERY = Query(  # Собираем описание запроса.
    name="n5",  # Имя для командной строки.
    tables=["trips", "zones"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["pu_borough", "do_borough"],  # Пара боро однозначно задаёт строку.
)
