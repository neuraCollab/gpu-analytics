"""Тест запросов NYC Taxi на крошечных синтетических данных.

Настоящие данные весят 700 MB и скачиваются из интернета — для автоматических тестов
(и для CI) это слишком долго. Поэтому здесь генерируем 2000 «поездок» случайно,
но с той же схемой колонок, и проверяем, что DuckDB и Polars дают одинаковые ответы.
"""

import random  # Генератор случайных чисел из стандартной библиотеки.
from datetime import datetime, timedelta  # Дата-время и интервал — для временных меток поездок.

import polars as pl  # Таблицы синтетических данных.
import pytest  # Фреймворк тестов.

from gpu_analytics.bench.run import run_benchmark  # Бенчмарк целиком.
from gpu_analytics.queries import SUITES  # Наборы запросов.


@pytest.fixture(scope="module")  # Данные создаются один раз на весь файл.
def tiny_taxi(tmp_path_factory):
    """Создать trips.parquet и zones.parquet с синтетическими данными и вернуть папку."""
    out = tmp_path_factory.mktemp("nyc_taxi")  # Временная папка.
    rng = random.Random(42)  # Генератор с фиксированным зерном: данные одинаковы при каждом запуске.
    ints = lambda low, high: [rng.randint(low, high) for _ in range(n)]  # n случайных целых от low до high включительно.
    floats = lambda low, high: [round(rng.uniform(low, high), 2) for _ in range(n)]  # n случайных дробных, округлённых до центов.
    n = 2000  # Число синтетических поездок.
    zones = pl.DataFrame({  # Маленький справочник районов.
        "location_id": [1, 2, 3, 4, 5],  # Номера районов.
        "borough": ["EWR", "Queens", "Manhattan", "Manhattan", "Brooklyn"],  # Боро.
        "zone": ["Newark Airport", "JFK Airport", "Midtown", "SoHo", "Park Slope"],  # Названия (два аэропорта).
        "service_zone": ["EWR", "Airports", "Yellow Zone", "Yellow Zone", "Boro Zone"],  # Тип зоны.
    }).with_columns(pl.col("location_id").cast(pl.Int32))  # Тип ключа — как в настоящих данных (INTEGER).
    start = datetime(2024, 1, 1)  # Начало года.
    pickup = [start + timedelta(minutes=m) for m in ints(0, 365 * 24 * 60 - 1)]  # Случайные моменты посадки в течение года.
    trips = pl.DataFrame({  # Таблица поездок с той же схемой, что делает download_nyc_taxi.
        "vendor_id": ints(1, 2),  # Оператор 1 или 2.
        "pickup_at": pickup,  # Время посадки.
        "dropoff_at": [p + timedelta(minutes=d) for p, d in zip(pickup, ints(1, 89))],  # Высадка через 1–89 минут.
        "passenger_count": ints(1, 4),  # 1–4 пассажира.
        "trip_distance": floats(0.1, 30.0),  # Расстояние, мили.
        "pu_location_id": ints(1, 5),  # Район посадки 1–5.
        "do_location_id": ints(1, 5),  # Район высадки 1–5.
        "payment_type": ints(0, 4),  # Способ оплаты 0–4.
        "fare_amount": floats(-5.0, 80.0),  # Тариф; бывают отрицательные — как в реальных данных.
        "tip_amount": floats(0.0, 15.0),  # Чаевые.
        "tolls_amount": floats(0.0, 7.0),  # Платные дороги.
        "total_amount": floats(3.0, 120.0),  # Итого.
    }).with_columns(  # Приводим целые колонки к INTEGER (Int32), как в настоящих данных.
        pl.col("vendor_id", "passenger_count", "pu_location_id", "do_location_id", "payment_type").cast(pl.Int32)
    )
    trips.write_parquet(out / "trips.parquet")  # Сохраняем поездки.
    zones.write_parquet(out / "zones.parquet")  # Сохраняем справочник.
    return out  # Отдаём путь тестам.


def test_nyc_taxi_cpu_engines_agree(tiny_taxi):
    """DuckDB и Polars CPU выполняют все запросы NYC Taxi и дают одинаковые ответы."""
    names = list(SUITES["nyc_taxi"])  # ["n1", …, "n5"].
    results = run_benchmark(tiny_taxi, ["duckdb", "polars_cpu"], names, warmup=0, repeats=1,
                            reference="duckdb", suite="nyc_taxi")  # Минимальный прогон.
    assert results["status"].to_list() == ["ok"] * 2 * len(names), results["error"].to_list()  # Все без ошибок.
    polars_rows = results.filter(results["engine"] == "polars_cpu")  # Строки Polars.
    wrong = polars_rows.filter(~polars_rows["correct"])  # Расхождения с DuckDB.
    assert wrong.height == 0, wrong.select("query", "error").rows()  # Их быть не должно.
