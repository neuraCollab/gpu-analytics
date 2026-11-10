"""Загрузка открытых данных NYC Taxi (жёлтое такси Нью-Йорка) и подготовка к бенчмарку.

Зачем второй набор данных: TPC-H — синтетика с «идеальными» равномерными данными.
NYC Taxi — реальные поездки: пропуски, перекосы (одни районы встречаются в сотни
раз чаще других), временные метки. Это проверка того, что выводы не зависят
от синтетики, и отложенная выборка для автовыбора движка (способ 6).

Источник: NYC Taxi & Limousine Commission (TLC) публикует поездки помесячно в Parquet.
Один месяц — около 50–65 MB и 3–4 млн поездок; 2024 год целиком — около 660 MB.

Что делает скрипт:
  1. Скачивает месячные файлы в папку <out>/raw (уже скачанные пропускает).
  2. Собирает их в одну таблицу trips.parquet с единообразными именами и типами колонок
     и только с поездками выбранного года (в исходных файлах встречаются ошибочные даты).
  3. Сохраняет справочник районов zones.parquet (номер района → название и боро).

Запуск:  python -m gpu_analytics.data.download_nyc_taxi --year 2024 --out data/nyc_taxi
"""

from __future__ import annotations  # Подсказки типов нового стиля во всех версиях Python 3.

import argparse  # Разбор аргументов командной строки.
import sys  # Нужен sys.stdout — настроить кодировку вывода в консоль.
import time  # Замер времени подготовки.
import urllib.request  # Скачивание файлов по HTTP из стандартной библиотеки (без сторонних пакетов).
from pathlib import Path  # Пути к файлам.

import duckdb  # DuckDB собирает месячные файлы в одну таблицу.

BASE_URL = "https://d37ci6vzurychx.cloudfront.net"  # Официальный адрес, с которого TLC раздаёт файлы.
ZONES_URL = f"{BASE_URL}/misc/taxi_zone_lookup.csv"  # Справочник районов (CSV, ~12 KB).

# Какие колонки берём и к каким типам приводим. Имена — в нижнем регистре и понятнее исходных.
# Типы фиксируем явно: в разных месяцах TLC иногда меняет тип колонки (например, INT ↔ DOUBLE).
COLUMNS = """
    CAST(VendorID AS INTEGER)              AS vendor_id,       -- компания-оператор
    CAST(tpep_pickup_datetime AS TIMESTAMP)  AS pickup_at,     -- когда пассажира забрали
    CAST(tpep_dropoff_datetime AS TIMESTAMP) AS dropoff_at,    -- когда высадили
    CAST(passenger_count AS INTEGER)       AS passenger_count, -- число пассажиров (бывает пропуск)
    CAST(trip_distance AS DOUBLE)          AS trip_distance,   -- расстояние в милях
    CAST(PULocationID AS INTEGER)          AS pu_location_id,  -- район посадки
    CAST(DOLocationID AS INTEGER)          AS do_location_id,  -- район высадки
    CAST(payment_type AS INTEGER)          AS payment_type,    -- способ оплаты: 1 карта, 2 наличные, …
    CAST(fare_amount AS DOUBLE)            AS fare_amount,     -- тариф по счётчику
    CAST(tip_amount AS DOUBLE)             AS tip_amount,      -- чаевые (только при оплате картой)
    CAST(tolls_amount AS DOUBLE)           AS tolls_amount,    -- платные дороги
    CAST(total_amount AS DOUBLE)           AS total_amount     -- итого заплачено
"""


def download(url: str, target: Path) -> None:
    """Скачать файл по адресу url в target, если его там ещё нет."""
    if target.exists():  # Уже скачан раньше — не тратим время и трафик.
        print(f"  есть      {target.name}")  # Сообщаем, что файл пропущен.
        return  # Выходим из функции.
    partial = target.with_suffix(target.suffix + ".part")  # Временное имя: если загрузка оборвётся, «полуфайл» не примем за готовый.
    urllib.request.urlretrieve(url, partial)  # Скачиваем файл целиком на диск.
    partial.rename(target)  # Загрузка закончилась — переименовываем в окончательное имя.
    print(f"  скачан    {target.name}  {target.stat().st_size / 1024**2:6.1f} MB")  # Печатаем размер.


def prepare(year: int, months: list[int], out_dir: Path, row_group_size: int = 1_000_000) -> dict[str, Path]:
    """Скачать месяцы года и собрать trips.parquet и zones.parquet. Вернуть «таблица → путь»."""
    raw_dir = out_dir / "raw"  # Папка для исходных файлов в том виде, как их отдаёт TLC.
    raw_dir.mkdir(parents=True, exist_ok=True)  # Создаём её (вместе с out_dir), если нет.

    for month in months:  # Скачиваем месяцы по одному.
        name = f"yellow_tripdata_{year}-{month:02d}.parquet"  # Имя файла у TLC; {month:02d} — номер месяца с ведущим нулём (01, 02, …).
        download(f"{BASE_URL}/trip-data/{name}", raw_dir / name)  # Скачиваем, если ещё нет.
    download(ZONES_URL, raw_dir / "taxi_zone_lookup.csv")  # Справочник районов.

    con = duckdb.connect()  # DuckDB в памяти: читает Parquet и CSV и пишет Parquet.
    raw_glob = (raw_dir / f"yellow_tripdata_{year}-*.parquet").as_posix()  # Шаблон «все месяцы года» (* — любые символы).
    trips = out_dir / "trips.parquet"  # Итоговая таблица поездок.
    con.execute(  # Собираем все месяцы в один файл.
        f"COPY (SELECT {COLUMNS} "  # Нужные колонки с приведением типов.
        f"FROM read_parquet('{raw_glob}', union_by_name = true) "  # union_by_name — склеивать файлы по именам колонок, а не по их порядку.
        f"WHERE tpep_pickup_datetime >= TIMESTAMP '{year}-01-01' "  # Отбрасываем поездки с ошибочной датой:
        f"AND tpep_pickup_datetime < TIMESTAMP '{year + 1}-01-01' "  # оставляем только выбранный год.
        f"ORDER BY tpep_pickup_datetime) "  # Сортируем по времени: так данные выглядят, как в реальном хранилище.
        f"TO '{trips.as_posix()}' (FORMAT PARQUET, ROW_GROUP_SIZE {row_group_size}, COMPRESSION SNAPPY)"  # Те же настройки, что у TPC-H.
    )
    zones = out_dir / "zones.parquet"  # Итоговый справочник районов.
    con.execute(  # Переводим справочник из CSV в Parquet, чтобы все движки читали один формат.
        f"COPY (SELECT CAST(LocationID AS INTEGER) AS location_id, "  # Номер района.
        f"Borough AS borough, Zone AS zone, service_zone "  # Боро (Manhattan, Queens, …), район, тип зоны.
        f"FROM read_csv('{(raw_dir / 'taxi_zone_lookup.csv').as_posix()}', header = true)) "  # CSV с заголовком.
        f"TO '{zones.as_posix()}' (FORMAT PARQUET)"
    )
    con.close()  # Закрываем соединение.
    return {"trips": trips, "zones": zones}  # Пути к готовым таблицам.


def main() -> None:
    """Точка входа для командной строки."""
    sys.stdout.reconfigure(encoding="utf-8")  # Консоль Windows по умолчанию в cp1251 — переключаем вывод на UTF-8.
    parser = argparse.ArgumentParser(description="Загрузка NYC Taxi и подготовка Parquet для бенчмарка")  # Разборщик аргументов.
    parser.add_argument("--year", type=int, default=2024, help="год поездок")  # Какой год.
    parser.add_argument("--months", type=int, nargs="+", default=list(range(1, 13)), help="номера месяцев (по умолчанию все 12)")  # Какие месяцы.
    parser.add_argument("--out", type=Path, required=True, help="папка для данных")  # Куда сохранить.
    args = parser.parse_args()  # Разбираем аргументы.

    start = time.perf_counter()  # Засекаем время.
    paths = prepare(args.year, args.months, args.out)  # Скачиваем и готовим данные.
    elapsed = time.perf_counter() - start  # Сколько это заняло.

    con = duckdb.connect()  # Отдельное соединение — чтобы посчитать строки в готовых файлах.
    for table, path in paths.items():  # Печатаем итог по каждой таблице.
        rows = con.execute(f"SELECT COUNT(*) FROM read_parquet('{path.as_posix()}')").fetchone()[0]  # Число строк (берётся из метаданных Parquet — быстро).
        print(f"{table:6s} {rows:>12,} строк {path.stat().st_size / 1024**2:8.1f} MB  {path}")  # Таблица, строки, размер, путь.
    print(f"Готово за {elapsed:.1f} с")  # Итоговое время.


if __name__ == "__main__":  # Выполняется только при запуске файла напрямую.
    main()  # Вызываем главную функцию.
