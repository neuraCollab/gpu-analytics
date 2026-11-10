"""Генерация данных TPC-H в формате Parquet с помощью DuckDB.

Что такое TPC-H: стандартный аналитический бенчмарк. Это 8 таблиц (заказы,
позиции заказов, клиенты, поставщики и т.д.) и 22 SQL-запроса к ним.
Параметр scale factor (SF) задаёт объём: SF1 ≈ 1 GB, SF10 ≈ 10 GB, SF100 ≈ 100 GB.

Как генерируем: в DuckDB есть расширение tpch с функцией dbgen — официальным
генератором данных. Мы генерируем таблицы внутри DuckDB, а затем выгружаем
каждую в отдельный Parquet-файл, который потом читают все движки.

Про DECIMAL: dbgen создаёт денежные колонки с типом DECIMAL (число с фиксированной
точкой). Часть GPU-движков поддерживает DECIMAL не во всех операциях, поэтому по
умолчанию мы приводим такие колонки к DOUBLE (число с плавающей точкой). Это
стандартное упрощение в бенчмарках; оно описывается в методике ВКР.

Запуск:  python -m gpu_analytics.data.generate_tpch --sf 1 --out data/tpch_sf1
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import argparse  # Разбор аргументов командной строки (--sf, --out и т.д.).
import sys  # Нужен sys.stdout — настроить кодировку вывода в консоль.
import time  # Замер времени генерации.
from pathlib import Path  # Удобная работа с путями к файлам и папкам.

import duckdb  # Движок DuckDB: в нём есть генератор TPC-H.


def decimal_columns(con: duckdb.DuckDBPyConnection, table: str) -> list[str]:
    """Вернуть имена колонок таблицы, у которых тип DECIMAL."""
    rows = con.execute(  # Выполняем SQL-запрос к системному каталогу DuckDB.
        "SELECT column_name FROM information_schema.columns "  # Берём имена колонок...
        "WHERE table_name = ? AND data_type LIKE 'DECIMAL%'",  # ...этой таблицы, у которых тип начинается с DECIMAL.
        [table],  # Значение для знака «?» — имя таблицы (так безопаснее, чем вставлять строку в SQL).
    ).fetchall()  # Забираем все строки результата как список кортежей.
    return [row[0] for row in rows]  # Из каждого кортежа берём первое поле — имя колонки.


def select_expression(table: str, decimals: list[str], decimal_as_double: bool) -> str:
    """Построить SELECT, который при необходимости приводит DECIMAL к DOUBLE."""
    if not decimal_as_double or not decimals:  # Если приводить не нужно или DECIMAL-колонок нет...
        return f"SELECT * FROM {table}"  # ...берём таблицу как есть.
    casts = ", ".join(f"CAST({col} AS DOUBLE) AS {col}" for col in decimals)  # Для каждой DECIMAL-колонки пишем приведение к DOUBLE.
    return f"SELECT * REPLACE ({casts}) FROM {table}"  # REPLACE в DuckDB: взять все колонки, но перечисленные заменить выражениями.


def generate(sf: float, out_dir: Path, decimal_as_double: bool = True, row_group_size: int = 1_000_000) -> dict[str, Path]:
    """Сгенерировать TPC-H с масштабом sf и сохранить каждую таблицу в Parquet.

    Возвращает словарь «имя таблицы → путь к Parquet-файлу».
    row_group_size — сколько строк в одной группе строк Parquet (это параметр раскладки,
    который мы будем исследовать в способе 2; здесь — значение по умолчанию).
    """
    out_dir.mkdir(parents=True, exist_ok=True)  # Создаём папку для результата (и родительские папки), если её нет.
    db_file = out_dir / "tpch.duckdb"  # Временная база DuckDB на диске: так генерация больших SF не упрётся в RAM.
    con = duckdb.connect(str(db_file))  # Открываем (или создаём) файл базы DuckDB.
    con.execute("INSTALL tpch")  # Скачиваем расширение tpch (нужно один раз; потом берётся из кэша).
    con.execute("LOAD tpch")  # Подключаем расширение в текущую сессию.
    con.execute(f"CALL dbgen(sf = {sf})")  # Генерируем все 8 таблиц TPC-H с нужным масштабом.
    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]  # Получаем список созданных таблиц.
    paths = {}  # Сюда запишем пути к готовым Parquet-файлам.
    for table in tables:  # Обрабатываем таблицы по одной.
        target = out_dir / f"{table}.parquet"  # Путь к Parquet-файлу этой таблицы.
        query = select_expression(table, decimal_columns(con, table), decimal_as_double)  # SELECT с приведением типов.
        con.execute(  # Выгружаем результат SELECT в Parquet-файл командой COPY.
            f"COPY ({query}) TO '{target.as_posix()}' "  # as_posix() даёт путь с «/», который DuckDB понимает и на Windows.
            f"(FORMAT PARQUET, ROW_GROUP_SIZE {row_group_size}, COMPRESSION SNAPPY)"  # Формат, размер группы строк, сжатие Snappy.
        )
        paths[table] = target  # Запоминаем путь к файлу.
    con.close()  # Закрываем соединение с базой.
    db_file.unlink(missing_ok=True)  # Удаляем временную базу DuckDB: дальше нужны только Parquet-файлы.
    db_file.with_suffix(".duckdb.wal").unlink(missing_ok=True)  # Удаляем журнал изменений DuckDB, если он остался.
    return paths  # Возвращаем словарь путей.


def main() -> None:
    """Точка входа для командной строки."""
    sys.stdout.reconfigure(encoding="utf-8")  # Консоль Windows по умолчанию в cp1251 — переключаем вывод на UTF-8, чтобы кириллица печаталась без ошибок.
    parser = argparse.ArgumentParser(description="Генерация TPC-H в Parquet через DuckDB")  # Создаём разборщик аргументов.
    parser.add_argument("--sf", type=float, default=1, help="scale factor: 1 ≈ 1 GB, 10 ≈ 10 GB")  # Масштаб данных.
    parser.add_argument("--out", type=Path, required=True, help="папка для Parquet-файлов")  # Куда сохранить.
    parser.add_argument("--keep-decimal", action="store_true", help="не приводить DECIMAL к DOUBLE")  # Флаг-переключатель.
    parser.add_argument("--row-group-size", type=int, default=1_000_000, help="строк в группе строк Parquet")  # Параметр раскладки.
    args = parser.parse_args()  # Разбираем аргументы, переданные в командной строке.

    start = time.perf_counter()  # Засекаем время начала (perf_counter — самый точный таймер для замеров).
    paths = generate(args.sf, args.out, decimal_as_double=not args.keep_decimal, row_group_size=args.row_group_size)  # Генерируем.
    elapsed = time.perf_counter() - start  # Сколько секунд заняла генерация.

    for table, path in sorted(paths.items()):  # Печатаем список файлов в алфавитном порядке таблиц.
        size_mb = path.stat().st_size / 1024**2  # Размер файла в мегабайтах.
        print(f"{table:10s} {size_mb:10.1f} MB  {path}")  # Выравниваем столбцы для читаемости.
    print(f"Готово за {elapsed:.1f} с")  # Итоговое время.


if __name__ == "__main__":  # Выполняется только при запуске файла напрямую.
    main()  # Вызываем главную функцию.
