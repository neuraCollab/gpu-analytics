# gpu-analytics

[![CI](https://github.com/neuraCollab/gpu-analytics/actions/workflows/ci.yml/badge.svg)](https://github.com/neuraCollab/gpu-analytics/actions/workflows/ci.yml)

Код ВКР «Разработка способов ГПУ-ускорения аналитической обработки больших данных».

Репозиторий содержит бенчмарк аналитических запросов (TPC-H и реальные данные NYC Taxi) на CPU- и GPU-движках и, по мере работы, инструменты, которые реализуют способы ускорения. План работ — в `../research/implementation_plan.md`.

## Что уже есть (недели 1–3 плана)

| Файл | Что делает |
|---|---|
| `src/gpu_analytics/env_check.py` | «Паспорт» окружения: CPU, RAM, GPU, версии библиотек |
| `src/gpu_analytics/data/generate_tpch.py` | Генерация TPC-H через DuckDB → Parquet (по одному файлу на таблицу) |
| `src/gpu_analytics/data/download_nyc_taxi.py` | Загрузка поездок жёлтого такси Нью-Йорка (TLC) → `trips.parquet` + справочник `zones.parquet` |
| `src/gpu_analytics/queries/base.py` | Описание запроса (`Query`) и `sql_sum` — SUM с семантикой SQL |
| `src/gpu_analytics/queries/tpch/q01.py … q22.py` | Все 22 запроса TPC-H, каждый в двух видах: SQL и Polars; в начале файла — смысл запроса и какие операции он нагружает |
| `src/gpu_analytics/queries/nyc_taxi/n1.py … n5.py` | 5 запросов к реальным данным NYC Taxi (SQL + Polars) |
| `src/gpu_analytics/bench/timer.py` | Протокол замеров: прогрев, повторы, медиана, межквартильный размах |
| `src/gpu_analytics/bench/engines.py` | Единый интерфейс движков: DuckDB, Polars CPU, Polars GPU, Spark CPU |
| `src/gpu_analytics/bench/correctness.py` | Сверка ответов движков с допуском для чисел |
| `src/gpu_analytics/bench/run.py` | Запуск бенчмарка, сохранение результатов и паспорта в `results/` |
| `tests/` | Тесты: протокол замеров, сверка, сквозной прогон всех запросов на крошечных данных (в том числе на Spark) |
| `.github/workflows/ci.yml` | CI: GitHub запускает тесты при каждом push (без GPU) |
| `experiments/method1_colab_gpu.ipynb` | Ноутбук Colab: все 22 запроса на Polars GPU, ускорение и список откатов на CPU |

## Установка

Нужен Python 3.11+. Рекомендуется [uv](https://docs.astral.sh/uv/) (быстрый менеджер пакетов и виртуальных окружений).

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"
```

Без uv то же самое делается так: `python -m venv .venv`, активировать окружение, затем `pip install -e ".[dev]"`.

**На GPU-сервере** (Linux или WSL2, драйвер с поддержкой CUDA 13: `nvidia-smi` → «CUDA Version: 13.x») дополнительно ставится GPU-движок. Используется только вариант под CUDA 13 — так не бывает конфликтов между пакетами CUDA 12 и 13:

```bash
uv pip install -e ".[gpu]"
```

В **Colab** эту группу не ставят: там RAPIDS уже предустановлен, и ноутбук сам ставит `cudf-polars` той же версии. GPU-движок поддерживает не самые свежие версии Polars, поэтому pip может поставить Polars старше, чем без GPU.

Если пакет GPU-движка не ставится, сверьтесь с разделом GPU support в документации Polars: иногда нужен дополнительный индекс пакетов NVIDIA.

**Для Spark CPU** нужны группа `[spark]` и Java 17+. Если Java нет, её можно поставить в папку пользователя без прав администратора (`~/.jdk`); движок `spark_cpu` найдёт её сам:

```bash
uv pip install -e ".[spark]"
```

```bash
uv run python -c "import jdk; jdk.install('17', path='~/.jdk')"
```

## Как пользоваться

1. Проверить окружение:

   ```bash
   uv run python -m gpu_analytics.env_check
   ```

2. Сгенерировать данные. SF1 ≈ 1 GB; для отладки хватит SF 0.1. SF10 генерируется около 2 минут и занимает 3.2 GB в Parquet.

   ```bash
   uv run python -m gpu_analytics.data.generate_tpch --sf 10 --out data/tpch_sf10
   ```

   Реальные данные NYC Taxi за 2024 год (скачивается около 660 MB, итог — 41 млн поездок, 706 MB):

   ```bash
   uv run python -m gpu_analytics.data.download_nyc_taxi --year 2024 --out data/nyc_taxi
   ```

3. Запустить бенчмарк на CPU:

   ```bash
   uv run python -m gpu_analytics.bench.run --data data/tpch_sf10 --engines duckdb polars_cpu spark_cpu
   ```

   NYC Taxi:

   ```bash
   uv run python -m gpu_analytics.bench.run --suite nyc_taxi --data data/nyc_taxi --engines duckdb polars_cpu spark_cpu
   ```

   Только некоторые запросы: `--queries q1 q6`.

4. Запустить бенчмарк с GPU (только на машине с GPU). Своей GPU нет — откройте ноутбук в Colab: [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/neuraCollab/gpu-analytics/blob/main/experiments/method1_colab_gpu.ipynb). Инструкция — в первой ячейке ноутбука.

   ```bash
   uv run python -m gpu_analytics.bench.run --data data/tpch_sf1 --engines duckdb polars_cpu polars_gpu
   ```

5. Запустить тесты. На машине без GPU (Spark-тест идёт около 30 с; без него — `-m "not gpu and not spark"`):

   ```bash
   uv run pytest -m "not gpu"
   ```

   Все тесты, включая GPU:

   ```bash
   uv run pytest
   ```

## Что получается на выходе
- `results/results_<время>.csv` — одна строка на пару «движок × запрос»: статус, медиана времени, квартили, совпал ли ответ с эталоном (DuckDB).
- `results/passport_<время>.json` — на каком железе и с какими версиями библиотек выполнялся прогон.

## Как читать код
Каждая строка прокомментирована на русском. Рекомендуемый порядок чтения:
1. `queries/tpch/q01.py`, `q06.py`, затем `q03.py` (соединения), `q04.py` (EXISTS), `q21.py` (самый сложный) — что считаем;
2. `bench/engines.py` — чем считаем;
3. `bench/timer.py` — как меряем;
4. `bench/correctness.py` — как проверяем;
5. `bench/run.py` — как всё связано.
