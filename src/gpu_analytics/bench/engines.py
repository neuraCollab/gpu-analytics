"""Адаптеры движков: единый способ запустить один и тот же запрос на разных движках.

Идея: у каждого движка свой API (DuckDB понимает SQL, Polars — цепочки методов).
Чтобы бенчмарк был одинаковым для всех, каждый движок «оборачиваем» в класс
с двумя методами:
  * prepare(data_dir, tables) — разовая подготовка (вне замера): указать, где лежат файлы;
  * execute(query)           — выполнить запрос и вернуть результат как polars.DataFrame
                               (это и замеряется).

Важно для честного сравнения: все движки читают одни и те же Parquet-файлы
на каждом запуске, а результат приводят к одному формату (polars.DataFrame).
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import os  # Переменные окружения (JAVA_HOME) и число ядер CPU.
import shutil  # shutil.which: есть ли программа java в PATH.
from pathlib import Path  # Пути к файлам.

import duckdb  # CPU-движок DuckDB.
import polars as pl  # Polars (CPU и GPU).

from gpu_analytics.queries.base import Query, Tables  # Описание запроса и тип «таблицы Polars».


class Engine:
    """Базовый класс движка. Конкретные движки переопределяют prepare и execute."""

    name = "base"  # Имя движка в отчётах; переопределяется в наследниках.

    def prepare(self, data_dir: Path, tables: list[str]) -> None:
        """Разовая подготовка перед замерами (не входит во время запроса)."""
        raise NotImplementedError  # Базовый класс сам ничего не умеет — метод обязан реализовать наследник.

    def execute(self, query: Query) -> pl.DataFrame:
        """Выполнить запрос и вернуть результат как polars.DataFrame."""
        raise NotImplementedError  # То же самое: реализация — в наследнике.

    def close(self) -> None:
        """Освободить ресурсы после всех замеров (по умолчанию освобождать нечего)."""
        return None  # Наследники, которые держат тяжёлые ресурсы (Spark держит JVM), переопределяют метод.


class DuckDBEngine(Engine):
    """DuckDB: выполняет SQL-версию запроса. Это наш самый сильный CPU-базис."""

    name = "duckdb"  # Имя в отчётах.

    def __init__(self) -> None:
        self.con = duckdb.connect()  # Соединение с DuckDB в памяти (без файла базы данных).

    def prepare(self, data_dir: Path, tables: list[str]) -> None:
        for table in tables:  # Для каждой нужной таблицы...
            path = (data_dir / f"{table}.parquet").as_posix()  # ...путь к её Parquet-файлу (с «/» для DuckDB).
            self.con.execute(  # ...создаём представление (VIEW): имя таблицы → чтение Parquet-файла.
                f"CREATE OR REPLACE VIEW {table} AS SELECT * FROM read_parquet('{path}')"
            )  # VIEW не копирует данные: файл читается заново при каждом запросе — как и у других движков.

    def execute(self, query: Query) -> pl.DataFrame:
        # con.sql(...) возвращает «отношение» (relation) — ленивый результат запроса;
        # метод .pl() выполняет его и отдаёт результат как polars.DataFrame.
        # (В DuckDB 2.0 метода .pl() у самого соединения больше нет — только у relation.)
        return self.con.sql(query.sql).pl()


class PolarsEngine(Engine):
    """Polars: выполняет Polars-версию запроса на CPU или на GPU."""

    def __init__(self, gpu: bool = False) -> None:
        self.gpu = gpu  # Запоминаем режим: True — GPU-движок, False — обычный CPU-движок.
        self.name = "polars_gpu" if gpu else "polars_cpu"  # Имя зависит от режима.
        self.tables: Tables = {}  # Сюда prepare положит ленивые таблицы.

    def prepare(self, data_dir: Path, tables: list[str]) -> None:
        self.tables = {  # Для каждой таблицы создаём ленивое чтение Parquet (scan_parquet).
            table: pl.scan_parquet(data_dir / f"{table}.parquet")  # scan — ничего не читает сразу, только запоминает файл.
            for table in tables
        }

    def execute(self, query: Query) -> pl.DataFrame:
        plan = query.polars(self.tables)  # Строим план запроса (ленивый, ещё без вычислений).
        if not self.gpu:  # CPU-режим...
            return plan.collect()  # ...обычное выполнение на CPU.
        # GPU-режим. raise_on_fail=True: если GPU-движок не поддерживает какую-то операцию,
        # Polars по умолчанию тихо выполнит запрос на CPU. Нам это не подходит — мы хотим
        # ЗНАТЬ о таких откатах (это результат способа 1), поэтому просим бросить ошибку.
        # (Название параметра сверять с документацией текущей версии Polars.)
        return plan.collect(engine=pl.GPUEngine(raise_on_fail=True))  # Выполняем на GPU.


def ensure_java() -> None:
    """Убедиться, что Spark найдёт Java; иначе — понятная ошибка.

    Spark работает внутри виртуальной машины Java (JVM), поэтому без Java он не запустится.
    Порядок поиска: переменная окружения JAVA_HOME → программа java в PATH →
    JDK, установленный в папку ~/.jdk (так его ставит пакет install-jdk, см. README).
    """
    if os.environ.get("JAVA_HOME") or shutil.which("java"):  # Java уже указана явно или есть в PATH.
        return  # Ничего делать не нужно.
    candidates = sorted(Path.home().glob(".jdk/jdk-*"))  # Ищем JDK в ~/.jdk (glob — поиск по шаблону имени).
    if not candidates:  # Ничего не нашли.
        raise RuntimeError(  # Объясняем, что делать, вместо непонятной ошибки Spark.
            "Для spark_cpu нужна Java 17+. Задайте JAVA_HOME или установите JDK: "
            "python -c \"import jdk; jdk.install('17', path='~/.jdk')\""
        )
    os.environ["JAVA_HOME"] = str(candidates[-1])  # Берём последний по имени (самую новую версию) и сообщаем Spark через JAVA_HOME.


class SparkEngine(Engine):
    """Apache Spark в локальном режиме: выполняет SQL-версию запроса на всех ядрах CPU.

    Зачем Spark, если есть DuckDB: Spark — стандарт индустрии для распределённой обработки,
    и именно его ускоряет плагин Spark RAPIDS (способ 1). Spark CPU — базис для сравнения с ним.
    На одной машине Spark почти всегда медленнее DuckDB: он рассчитан на кластер,
    и у него есть постоянные накладные расходы (планирование задач, JVM).
    """

    name = "spark_cpu"  # Имя в отчётах.

    def __init__(self, driver_memory: str = "6g") -> None:
        from pyspark.sql import SparkSession  # Импорт внутри метода: pyspark — необязательная зависимость (extra «spark»).

        ensure_java()  # Без Java Spark не стартует — проверяем заранее.
        cores = os.cpu_count() or 1  # Число логических ядер CPU (or 1 — на случай, если ОС не сообщила).
        self.spark = (  # Создаём (или берём уже созданную) сессию Spark.
            SparkSession.builder  # «Строитель» сессии: настройки задаются цепочкой .config(...).
            .master("local[*]")  # Локальный режим: всё в одном процессе, [*] — использовать все ядра.
            .appName("gpu-analytics")  # Имя приложения (видно в логах).
            .config("spark.driver.memory", driver_memory)  # Память JVM. Действует, только если JVM ещё не запущена.
            # Число частей (партиций) после перемешивания данных (shuffle) при join и group by.
            # По умолчанию 200 — это для кластера; на одной машине столько мелких задач только тормозят.
            .config("spark.sql.shuffle.partitions", str(cores * 2))
            # Часовой пояс сессии — UTC. Иначе Spark переводит временные метки в пояс компьютера,
            # и EXTRACT(hour/month …) в NYC Taxi может дать не тот час, что у DuckDB и Polars.
            .config("spark.sql.session.timeZone", "UTC")
            .config("spark.ui.enabled", "false")  # Не запускать веб-интерфейс Spark UI (не нужен в замерах).
            .config("spark.ui.showConsoleProgress", "false")  # Не печатать полоски прогресса в консоль.
            .getOrCreate()  # Создать сессию (запускает JVM — это несколько секунд, вне замеров).
        )
        self.spark.sparkContext.setLogLevel("ERROR")  # Печатать только ошибки, без потока предупреждений.

    def prepare(self, data_dir: Path, tables: list[str]) -> None:
        for table in tables:  # Для каждой нужной таблицы...
            uri = (data_dir / f"{table}.parquet").resolve().as_uri()  # ...полный путь в виде file:///… (так Spark понимает пути и на Windows).
            self.spark.read.parquet(uri).createOrReplaceTempView(table)  # ...временное представление: как VIEW в DuckDB, файл читается при каждом запросе.

    def execute(self, query: Query) -> pl.DataFrame:
        # spark.sql(...) строит план; toArrow() выполняет его и собирает результат на «драйвер»
        # в формате Apache Arrow; pl.from_arrow превращает Arrow-таблицу в polars.DataFrame без копирования.
        return pl.from_arrow(self.spark.sql(query.sql).toArrow())

    def close(self) -> None:
        self.spark.stop()  # Останавливаем сессию и JVM: освобождаем несколько гигабайт памяти для следующих движков.


def make_engine(name: str) -> Engine:
    """Создать движок по имени из командной строки."""
    if name == "duckdb":  # DuckDB на CPU.
        return DuckDBEngine()
    if name == "polars_cpu":  # Polars на CPU.
        return PolarsEngine(gpu=False)
    if name == "polars_gpu":  # Polars на GPU.
        return PolarsEngine(gpu=True)
    if name == "spark_cpu":  # Spark на CPU (локальный режим).
        return SparkEngine()
    raise ValueError(f"Неизвестный движок: {name}. Доступны: {', '.join(ENGINE_NAMES)}")  # Понятная ошибка вместо падения дальше.


ENGINE_NAMES = ["duckdb", "polars_cpu", "polars_gpu", "spark_cpu"]  # Доступные движки (дальше: spark_rapids, cudf_pandas, dask_cudf).
