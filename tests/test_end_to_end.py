"""Сквозной тест: генерируем крошечный TPC-H и прогоняем все 22 запроса.

Проверяет, что все части работают вместе: генерация → движки → замер → сверка.
SF 0.01 — это примерно 10 MB данных, тест идёт несколько секунд.
"""

import pytest  # Фреймворк тестов.

from gpu_analytics.bench.run import run_benchmark  # Бенчмарк целиком.
from gpu_analytics.data.generate_tpch import generate  # Генератор данных.
from gpu_analytics.queries.tpch import QUERIES  # Реестр запросов.

ALL_QUERIES = list(QUERIES)  # Имена всех запросов: ["q1", "q2", …, "q22"].


@pytest.fixture(scope="module")  # Фикстура: данные генерируются один раз на весь файл тестов.
def tiny_tpch(tmp_path_factory):
    """Сгенерировать TPC-H SF 0.01 во временную папку и вернуть путь к ней."""
    out = tmp_path_factory.mktemp("tpch")  # Временная папка, которую pytest удалит сам.
    generate(0.01, out)  # Генерируем крошечные данные.
    return out  # Отдаём путь тестам.


def test_registry_has_all_22_queries():
    """В реестре ровно 22 запроса с именами q1 … q22 и у каждого указаны таблицы."""
    assert ALL_QUERIES == [f"q{i}" for i in range(1, 23)]  # Имена и порядок.
    assert all(QUERIES[name].tables for name in ALL_QUERIES)  # Список таблиц не пустой.


def test_cpu_engines_agree(tiny_tpch):
    """DuckDB и Polars CPU выполняют все 22 запроса и дают одинаковые ответы."""
    results = run_benchmark(tiny_tpch, ["duckdb", "polars_cpu"], ALL_QUERIES, warmup=0, repeats=1, reference="duckdb")  # Минимальный прогон.
    assert results["status"].to_list() == ["ok"] * 2 * len(ALL_QUERIES), results["error"].to_list()  # Все без ошибок.
    polars_rows = results.filter(results["engine"] == "polars_cpu")  # Строки Polars.
    wrong = polars_rows.filter(~polars_rows["correct"])  # Запросы, где ответ Polars не совпал с DuckDB.
    assert wrong.height == 0, wrong.select("query", "error").rows()  # Если есть — покажем, какие и почему.


@pytest.mark.spark  # Пометка: тест запускает Spark (около 30 с); пропустить: pytest -m "not spark".
def test_spark_engine_agrees(tiny_tpch):
    """Spark CPU выполняет все 22 запроса (тот же SQL, что у DuckDB) и даёт те же ответы."""
    pytest.importorskip("pyspark")  # Если группа [spark] не установлена — тест пропускается, а не падает.
    from gpu_analytics.bench.engines import ensure_java  # Проверка Java.
    try:  # Без Java Spark не запустится...
        ensure_java()
    except RuntimeError as error:  # ...тогда тоже пропускаем тест с пояснением.
        pytest.skip(str(error))
    results = run_benchmark(tiny_tpch, ["duckdb", "spark_cpu"], ALL_QUERIES, warmup=0, repeats=1, reference="duckdb")  # Прогон.
    spark_rows = results.filter(results["engine"] == "spark_cpu")  # Строки Spark.
    assert spark_rows["status"].to_list() == ["ok"] * len(ALL_QUERIES), spark_rows.select("query", "error").rows()  # Без ошибок.
    wrong = spark_rows.filter(~spark_rows["correct"])  # Расхождения с DuckDB.
    assert wrong.height == 0, wrong.select("query", "error").rows()  # Их быть не должно.


@pytest.mark.gpu  # Пометка: тест требует GPU; на машине без GPU запускайте pytest -m "not gpu".
def test_gpu_engine_agrees(tiny_tpch):
    """Polars GPU: всё, что выполнилось на GPU, совпало с DuckDB.

    Неподдерживаемые на GPU запросы (status == "error") здесь не считаются провалом теста:
    список таких запросов — это результат способа 1, а не ошибка в нашем коде.
    Но простые Q1 и Q6 обязаны работать.
    """
    results = run_benchmark(tiny_tpch, ["duckdb", "polars_gpu"], ALL_QUERIES, warmup=0, repeats=1, reference="duckdb")  # Прогон с GPU.
    gpu_rows = results.filter(results["engine"] == "polars_gpu")  # Строки GPU-движка.
    ok_rows = gpu_rows.filter(gpu_rows["status"] == "ok")  # Запросы, которые выполнились.
    assert {"q1", "q6"} <= set(ok_rows["query"].to_list()), gpu_rows.select("query", "error").rows()  # Q1 и Q6 среди выполненных.
    wrong = ok_rows.filter(~ok_rows["correct"])  # Выполнились, но ответ не совпал.
    assert wrong.height == 0, wrong.select("query", "error").rows()  # Таких быть не должно.
