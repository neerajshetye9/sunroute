"""Unit tests for Jetson measurement scripts and timing parsers."""

from scripts.benchmark_model import parse_llama_timings
from scripts.jetson_power_probe import JetsonPowerProbe, get_nvpmodel_mode


def test_parse_llama_timings():
    sample_output = (
        "llama_print_timings:        load time =     230.12 ms\n"
        "llama_print_timings: prompt eval time =     142.50 ms /    32 tokens "
        "(    4.45 ms per token,   224.56 tokens per second)\n"
        "llama_print_timings:        eval time =    4120.00 ms /   128 tokens "
        "(   32.19 ms per token,    31.07 tokens per second)\n"
        "llama_print_timings:       total time =    4300.20 ms /   160 tokens\n"
    )
    res = parse_llama_timings(sample_output)

    assert res["prompt_tokens"] == 32.0
    assert res["ttft_ms"] == 142.50
    assert res["output_tokens"] == 128.0
    assert res["eval_time_ms"] == 4120.00
    assert res["tokens_per_sec"] == 31.07


def test_power_probe_sample():
    with JetsonPowerProbe(sample_interval_s=0.1) as probe:
        sample = probe.read_sample()
        assert sample.timestamp > 0
        assert sample.ram_total_mb_measured >= 0
        assert sample.source in ("jtop", "tegrastats", "mock_host")
        assert isinstance(sample.nvpmodel_mode_measured, str)


def test_nvpmodel_mode_string():
    mode = get_nvpmodel_mode()
    assert isinstance(mode, str)
