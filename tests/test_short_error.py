"""Тесты функции short_error: в таблицу результатов должна попадать суть ошибки."""

from gpu_analytics.bench.run import short_error  # Проверяемая функция.


def test_python_error_keeps_first_line():
    """Обычная ошибка Python: тип + первая строка текста."""
    assert short_error(ValueError("плохое значение\nподробности")) == "ValueError: плохое значение"  # Вторая строка отброшена.


def test_java_error_keeps_deepest_cause():
    """Ошибка из Java: вместо обёртки берётся последняя строка «Caused by:»."""
    text = ("An error occurred while calling o1.getResult.\n"  # Служебная обёртка py4j.
            "  at org.apache.spark.Something(Something.scala:70)\n"  # Строка стека.
            "Caused by: org.apache.spark.SparkException: Job aborted\n"  # Промежуточная причина.
            "Caused by: java.net.ConnectException: Connection timed out")  # Настоящая причина.
    assert short_error(RuntimeError(text)) == "RuntimeError: Caused by: java.net.ConnectException: Connection timed out"


def test_long_error_is_truncated():
    """Слишком длинное сообщение обрезается до limit символов."""
    assert len(short_error(RuntimeError("x" * 1000), limit=50)) == 50  # Ровно 50 символов.
