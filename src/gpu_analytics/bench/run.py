"""Запуск бенчмарка: все выбранные запросы на всех выбранных движках.

Что делает:
  1. Записывает «паспорт» окружения (железо и версии библиотек).
  2. Для каждого движка и запроса замеряет время по протоколу из timer.py.
  3. Сверяет ответ каждого движка с эталонным движком (по умолчанию DuckDB).
  4. Сохраняет таблицу результатов (CSV) и паспорт (JSON) в папку results/.

Запуск (пример):
  python -m gpu_analytics.bench.run --data data/tpch_sf1 --engines duckdb polars_cpu --queries q1 q6
  python -m gpu_analytics.bench.run --suite nyc_taxi --data data/nyc_taxi --engines duckdb polars_cpu spark_cpu
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import argparse  # Разбор аргументов командной строки.
import json  # Сохранение паспорта окружения.
import sys  # Нужен sys.stdout — настроить кодировку вывода в консоль.
from datetime import datetime  # Метка времени для имени файла результатов.
from pathlib import Path  # Пути к файлам.

import polars as pl  # Таблица результатов собирается в polars.DataFrame.

from gpu_analytics.bench.correctness import compare  # Сверка ответов.
from gpu_analytics.bench.engines import ENGINE_NAMES, make_engine  # Движки.
from gpu_analytics.bench.timer import measure  # Протокол замеров.
from gpu_analytics.env_check import environment_passport  # Паспорт окружения.
from gpu_analytics.queries import SUITES  # Наборы запросов: «tpch» и «nyc_taxi»; в каждом — имя → Query.


def short_error(error: Exception, limit: int = 300) -> str:
    """Коротко описать ошибку для таблицы результатов.

    Ошибки Spark приходят из Java и содержат стек на сотни строк, а первые строки — служебная
    обёртка («Exception thrown in awaitResult»). Настоящая причина — в последней строке
    «Caused by: …», поэтому берём её. Для обычных ошибок Python — первая строка текста.
    """
    lines = [line.strip() for line in str(error).splitlines() if line.strip()]  # Непустые строки текста ошибки.
    causes = [line for line in lines if line.startswith("Caused by:")]  # Строки с причинами (бывают только у Java-ошибок).
    message = causes[-1] if causes else (lines[0] if lines else "")  # Самая глубокая причина или первая строка.
    return f"{type(error).__name__}: {message}"[:limit]  # Тип ошибки + суть, обрезанные до limit символов.


def run_benchmark(data_dir: Path, engine_names: list[str], query_names: list[str],
                  warmup: int, repeats: int, reference: str, suite: str = "tpch") -> pl.DataFrame:
    """Выполнить бенчмарк и вернуть таблицу результатов (одна строка = движок × запрос)."""
    queries = SUITES[suite]  # Реестр запросов выбранного набора.
    tables = sorted({t for q in query_names for t in queries[q].tables})  # Все таблицы, нужные выбранным запросам (без повторов).
    rows = []  # Строки будущей таблицы результатов.
    answers: dict[tuple[str, str], pl.DataFrame] = {}  # Ответы: (движок, запрос) → результат; нужны для сверки.

    for engine_name in engine_names:  # Перебираем движки.
        engine = make_engine(engine_name)  # Создаём объект движка по имени.
        engine.prepare(data_dir, tables)  # Разовая подготовка (вне замера).
        for query_name in query_names:  # Перебираем запросы.
            query = queries[query_name]  # Берём описание запроса из реестра.
            row = {"engine": engine_name, "query": query_name, "status": "ok", "error": ""}  # Заготовка строки результата.
            try:  # Запрос может упасть (например, GPU не поддерживает операцию) — ловим ошибку, чтобы не останавливать весь бенчмарк.
                timing, result = measure(lambda: engine.execute(query), warmup=warmup, repeats=repeats)  # Замер по протоколу.
                row.update(median_s=timing.median, q1_s=timing.q1, q3_s=timing.q3, iqr_s=timing.iqr)  # Записываем статистику.
                answers[(engine_name, query_name)] = result  # Сохраняем ответ для сверки.
            except Exception as error:  # Любая ошибка выполнения.
                row.update(status="error", error=short_error(error))  # Записываем суть ошибки (см. short_error).
            rows.append(row)  # Добавляем строку в таблицу.
            print(f"{engine_name:12s} {query_name:4s} {row['status']:6s} "  # Печатаем прогресс в консоль.
                  f"{row.get('median_s', float('nan')):8.3f} с", flush=True)  # flush — печатать сразу, а не копить в буфере.
        engine.close()  # Освобождаем ресурсы движка (Spark останавливает JVM), прежде чем запускать следующий.

    for row in rows:  # Второй проход: сверка ответов с эталонным движком.
        ref_answer = answers.get((reference, row["query"]))  # Ответ эталонного движка на тот же запрос.
        answer = answers.get((row["engine"], row["query"]))  # Ответ текущего движка.
        if row["engine"] == reference or ref_answer is None or answer is None:  # Эталон сам с собой не сверяем; без ответов сверить нельзя.
            row["correct"] = None  # None — «не проверялось».
            continue  # Переходим к следующей строке.
        problems = compare(ref_answer, answer, queries[row["query"]].sort_by)  # Сверяем.
        row["correct"] = not problems  # True, если расхождений нет.
        if problems:  # Если есть расхождения — дописываем их в поле error для отчёта.
            row["error"] = "; ".join(problems)[:300]

    return pl.DataFrame(rows)  # Превращаем список словарей в таблицу.


def main() -> None:
    """Точка входа для командной строки."""
    sys.stdout.reconfigure(encoding="utf-8")  # Консоль Windows по умолчанию в cp1251 и не умеет печатать рамки таблиц Polars — переключаем на UTF-8.
    parser = argparse.ArgumentParser(description="Бенчмарк аналитических запросов на CPU и GPU")  # Разборщик аргументов.
    parser.add_argument("--data", type=Path, required=True, help="папка с Parquet-файлами TPC-H")  # Где данные.
    parser.add_argument("--engines", nargs="+", default=["duckdb", "polars_cpu"], choices=ENGINE_NAMES)  # Какие движки (несколько через пробел).
    parser.add_argument("--suite", default="tpch", choices=list(SUITES), help="набор запросов")  # TPC-H или NYC Taxi.
    parser.add_argument("--queries", nargs="+", help="какие запросы (по умолчанию — все запросы набора)")  # Например: q1 q6.
    parser.add_argument("--warmup", type=int, default=1, help="число прогревочных запусков")  # Прогрев.
    parser.add_argument("--repeats", type=int, default=5, help="число учтённых запусков")  # Повторы.
    parser.add_argument("--reference", default="duckdb", help="эталонный движок для сверки ответов")  # Эталон.
    parser.add_argument("--out", type=Path, default=Path("results"), help="папка для результатов")  # Куда сохранять.
    args = parser.parse_args()  # Разбираем аргументы.
    query_names = args.queries or list(SUITES[args.suite])  # Если запросы не указаны — берём все запросы набора.
    unknown = set(query_names) - set(SUITES[args.suite])  # Имена, которых нет в наборе.
    if unknown:  # Сообщаем об опечатке сразу, а не после долгого прогона.
        parser.error(f"нет таких запросов в наборе {args.suite}: {sorted(unknown)}")  # parser.error печатает ошибку и завершает программу.

    args.out.mkdir(parents=True, exist_ok=True)  # Создаём папку результатов, если её нет.
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # Метка времени, например 20261110_153000.
    passport = environment_passport()  # Собираем паспорт окружения.
    (args.out / f"passport_{stamp}.json").write_text(  # Сохраняем паспорт в JSON-файл.
        json.dumps(passport, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    results = run_benchmark(args.data, args.engines, query_names, args.warmup, args.repeats, args.reference, args.suite)  # Запускаем бенчмарк.
    results = results.with_columns(  # Добавляем к каждой строке контекст эксперимента.
        pl.lit(str(args.data)).alias("data"),  # Какие данные использовались.
        pl.lit(args.suite).alias("suite"),  # Какой набор запросов.
        pl.lit(stamp).alias("run_id"),  # Идентификатор прогона (совпадает с именем файла паспорта).
    )
    csv_path = args.out / f"results_{stamp}.csv"  # Путь к файлу результатов.
    results.write_csv(csv_path)  # Сохраняем таблицу в CSV.

    with pl.Config(tbl_rows=100, tbl_width_chars=160):  # Настройки печати: показывать до 100 строк и широкие таблицы.
        print(results.select("engine", "query", "status", "median_s", "iqr_s", "correct"))  # Печатаем краткую сводку.
    print(f"\nРезультаты: {csv_path}")  # Где лежит полный файл.


if __name__ == "__main__":  # Выполняется только при запуске файла напрямую.
    main()  # Вызываем главную функцию.
