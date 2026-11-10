"""NYC Taxi N4 — поездки из аэропортов по месяцам.

Смысл: сколько поездок начинается в аэропортах (JFK, LaGuardia, Newark) и сколько они
в среднем стоят, по месяцам.
Что нагружает: строковый фильтр по справочнику (LIKE) + соединение + извлечение
месяца + группировка.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import polars as pl  # Библиотека Polars.

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».

SQL = """
SELECT EXTRACT(month FROM t.pickup_at) AS month,               -- месяц посадки
       COUNT(*)                        AS trips,               -- число поездок из аэропортов
       AVG(t.total_amount)             AS avg_total            -- средний чек
FROM trips t
JOIN zones z ON t.pu_location_id = z.location_id               -- поездка ↔ район посадки
WHERE z.zone LIKE '%Airport%'                                  -- район — аэропорт
GROUP BY EXTRACT(month FROM t.pickup_at)
ORDER BY month
"""


def polars_plan(t: Tables) -> pl.LazyFrame:
    """N4 на Polars."""
    airports = t["zones"].filter(pl.col("zone").str.contains("Airport", literal=True))  # Районы-аэропорты (literal — искать текст, не регулярное выражение).
    return (
        t["trips"]  # Таблица поездок.
        .join(airports, left_on="pu_location_id", right_on="location_id", how="semi")  # Только поездки из аэропортов.
        .group_by(pl.col("pickup_at").dt.month().alias("month"))  # Группировка по месяцу.
        .agg(  # Агрегаты по месяцу.
            pl.len().alias("trips"),  # COUNT(*).
            pl.col("total_amount").mean().alias("avg_total"),  # AVG(total_amount).
        )
        .sort("month")  # ORDER BY month.
    )


QUERY = Query(  # Собираем описание запроса.
    name="n4",  # Имя для командной строки.
    tables=["trips", "zones"],  # Читаемые таблицы.
    sql=SQL,  # SQL-версия.
    polars=polars_plan,  # Polars-версия.
    sort_by=["month"],  # Месяц однозначно задаёт строку.
)
