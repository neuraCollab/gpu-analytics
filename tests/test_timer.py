"""Тесты протокола замеров (timer.py). Работают без GPU и без данных."""

import pytest  # Фреймворк тестов.

from gpu_analytics.bench.timer import measure, summarize  # Тестируемые функции.


def test_summarize_odd_count():
    """Медиана и квартили для простого ряда 1..5 считаются правильно."""
    timing = summarize([1.0, 2.0, 3.0, 4.0, 5.0])  # Пять значений.
    assert timing.median == 3.0  # Медиана — среднее по порядку значение.
    assert timing.q1 == 2.0  # Первый квартиль (метод inclusive).
    assert timing.q3 == 4.0  # Третий квартиль.
    assert timing.iqr == 2.0  # Размах: 4 − 2.


def test_summarize_single_value():
    """Один замер: все статистики равны этому значению, размах ноль."""
    timing = summarize([0.5])  # Один замер.
    assert timing.median == timing.q1 == timing.q3 == 0.5  # Всё равно 0.5.
    assert timing.iqr == 0.0  # Разброса нет.


def test_measure_counts_calls():
    """measure вызывает функцию warmup + repeats раз и учитывает только repeats."""
    calls = []  # Список, куда функция будет записывать факт вызова.
    timing, result = measure(lambda: calls.append(1) or len(calls), warmup=2, repeats=3)  # Функция возвращает номер вызова.
    assert len(calls) == 5  # 2 прогрева + 3 учтённых.
    assert len(timing.times) == 3  # Учтены только 3.
    assert result == 5  # Возвращён результат последнего вызова.


def test_measure_rejects_zero_repeats():
    """repeats=0 — ошибка в параметрах, а не тихий пустой результат."""
    with pytest.raises(ValueError):  # Ожидаем исключение ValueError.
        measure(lambda: None, repeats=0)
