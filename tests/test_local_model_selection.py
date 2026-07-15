from arka.llm.model_advisor import (
    HardwareSnapshot,
    best_runnable_local_model,
    strongest_runnable_local_models,
    is_model_select_query,
    nl_to_argv,
)


def _hw(ram: float, models: list[str]) -> HardwareSnapshot:
    return HardwareSnapshot("test", 8, "cpu", ram, ram / 2, "none", "", None, 20, 100, False, models)


def test_selects_strongest_model_that_fits() -> None:
    assert best_runnable_local_model(_hw(16, ["llama3.2:1b", "qwen3:8b", "qwen3:14b"])) == "qwen3:8b"


def test_local_nl_option() -> None:
    assert is_model_select_query("run the best local model")
    assert "--local" in nl_to_argv("run the best local model")


def test_lists_top_runnable_models() -> None:
    models = strongest_runnable_local_models(_hw(32, ["llama3.2:1b", "qwen3:8b", "qwen3:14b"]), limit=2)
    assert models == ["qwen3:14b", "qwen3:8b"]


def test_top_models_nl_option() -> None:
    assert nl_to_argv("list 5 strongest runnable models") == ["--local", "--top", "5"]
