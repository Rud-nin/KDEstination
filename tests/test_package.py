import notification_service


def test_package_imports() -> None:
    assert notification_service.__version__ == "0.1.0"
