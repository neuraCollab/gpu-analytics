"""Запросы к реальным данным NYC Taxi (поездки жёлтого такси, 2024 год).

Таблицы: trips (≈41 млн поездок) и zones (справочник из 265 районов).
Данные готовит скрипт gpu_analytics.data.download_nyc_taxi.

Пять запросов подобраны так, чтобы покрыть основные типы операций TPC-H, но на реальных
данных с перекосами и пропусками: группировка по времени (N1), арифметика и фильтр (N2),
соединение со справочником и top-N (N3), строковый фильтр (N4), двойное соединение (N5).
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

from gpu_analytics.queries.base import Query  # Описание запроса.
from gpu_analytics.queries.nyc_taxi import n1, n2, n3, n4, n5  # Модули пяти запросов.

# Реестр: имя ("n1") → Query. Порядок — n1, …, n5.
QUERIES: dict[str, Query] = {module.QUERY.name: module.QUERY for module in (n1, n2, n3, n4, n5)}
