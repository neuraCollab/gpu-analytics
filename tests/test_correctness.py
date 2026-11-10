"""Тесты сверки результатов (correctness.py). Работают без GPU и без данных."""

import polars as pl  # Создаём маленькие таблицы прямо в тесте.

from gpu_analytics.bench.correctness import compare  # Тестируемая функция.


def test_same_data_different_order_and_types():
    """Одинаковые данные в разном порядке и с разными типами чисел считаются совпадающими."""
    ref = pl.DataFrame({"k": ["a", "b"], "v": [1.0, 2.0], "n": [10, 20]})  # Эталон.
    cand = pl.DataFrame({"K": ["b", "a"], "V": [2.0, 1.0], "N": pl.Series([20, 10], dtype=pl.UInt32)})  # Другой порядок, регистр, тип.
    assert compare(ref, cand, sort_by=["k"]) == []  # Расхождений нет.


def test_small_float_difference_is_tolerated():
    """Разница в последних знаках (порядок суммирования) — в пределах допуска."""
    ref = pl.DataFrame({"v": [1_000_000.0]})  # Эталон.
    cand = pl.DataFrame({"v": [1_000_000.0000001]})  # Почти то же число.
    assert compare(ref, cand, sort_by=[]) == []  # Считается совпадением.


def test_real_difference_is_reported():
    """Настоящее расхождение обнаруживается."""
    ref = pl.DataFrame({"v": [1.0, 2.0]})  # Эталон.
    cand = pl.DataFrame({"v": [1.0, 2.5]})  # Второе значение заметно отличается.
    problems = compare(ref, cand, sort_by=["v"])  # Сверяем.
    assert len(problems) == 1 and "вне допуска" in problems[0]  # Одна проблема — значение вне допуска.


def test_different_row_count_is_reported():
    """Разное число строк — сразу ошибка."""
    problems = compare(pl.DataFrame({"v": [1.0]}), pl.DataFrame({"v": [1.0, 2.0]}), sort_by=[])  # Одна строка против двух.
    assert problems and "число строк" in problems[0]  # Проблема про число строк.


def test_nulls_in_different_places_are_reported():
    """Пропуск (null) у одного движка и число у другого — расхождение."""
    ref = pl.DataFrame({"v": [1.0, None]})  # У эталона пропуск во второй строке.
    cand = pl.DataFrame({"v": [None, 1.0]})  # У кандидата — в первой (сортировку не делаем).
    problems = compare(ref, cand, sort_by=[])  # Сверяем без сортировки.
    assert any("пропуски" in p for p in problems)  # Среди проблем есть про пропуски.
