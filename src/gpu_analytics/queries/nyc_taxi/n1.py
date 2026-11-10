"""NYC Taxi N1 — поездки и выручка по месяцам.

Смысл: сколько было поездок, сколько заплатили и какое среднее расстояние в каждом месяце.
Что нагружает: сканирование всей таблицы + извлечение месяца из временной метки +
группировка с малым числом групп (12). Аналог TPC-H Q1 на реальных данных.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT EXTRACT(month FROM pickup_at) AS month,                 -- номер месяца посадки
       COUNT(*)                      AS trips,                 -- число поездок
       SUM(total_amount)             AS revenue,               -- сколько заплачено всего
       AVG(trip_distance)            AS avg_distance           -- среднее расстояние, мили
FROM trips
GROUP BY EXTRACT(month FROM pickup_at)
ORDER BY month
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """N1 на Polars."""
    return (
        t["trips"]  # Таблица поездок.
        .group_by(pl.col("pickup_at").dt.month().alias("month"))  # Группировка по месяцу посадки.
        .agg(  # Агрегаты по месяцу.
            pl.len().alias("trips"),  # COUNT(*).
            pl.col("total_amount").sum().alias("revenue"),  # SUM(total_amount).
            pl.col("trip_distance").mean().alias("avg_distance"),  # AVG(trip_distance).
        )
        .sort("month")  # ORDER BY month.
    )


QUERY = Query(  # Собираем описание запроса.
    name="n1",  # Имя для командной строки.
    tables=["trips"],  # Читает только поездки.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["month"],  # Месяц однозначно задаёт строку.
)
