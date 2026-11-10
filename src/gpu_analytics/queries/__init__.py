"""Подпакет queries: аналитические запросы в двух видах — SQL и Polars.

Наборы запросов (suite):
  * tpch     — 22 запроса стандартного бенчмарка TPC-H (синтетические данные);
  * nyc_taxi — 5 запросов к реальным поездкам такси Нью-Йорка.
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from gpu_analytics.queries import nyc_taxi, tpch  # Оба набора.
from gpu_analytics.queries.base import Query  # Описание запроса.

# Имя набора → реестр его запросов. Имя набора выбирают в командной строке: --suite tpch.
SUITES: dict[str, dict[str, Query]] = {
    "tpch": tpch.QUERIES,  # TPC-H.
    "nyc_taxi": nyc_taxi.QUERIES,  # NYC Taxi.
}
