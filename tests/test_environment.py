from uqgems.environment import (
    COMMANDS,
    MODULES,
    collect_environment,
    missing_commands,
    missing_modules,
)


def test_environment_report_has_expected_structure() -> None:
    report = collect_environment()

    assert report["python"]["version"]
    assert report["python"]["executable"]
    assert report["platform"]["system"]
    assert set(report["packages"]) == set(MODULES)


def test_required_modules_import() -> None:
    report = collect_environment()

    assert missing_modules(report) == []


def test_required_commands_are_on_path() -> None:
    report = collect_environment()

    assert set(report["commands"]) == set(COMMANDS)
    assert missing_commands(report) == []
