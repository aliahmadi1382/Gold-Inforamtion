from test_real_shadow import add

from gold_intelligence.delayed_research import compare_signal_profiles
from gold_intelligence.real_paper import evaluate_real_paper


def test_delayed_signal_research_does_not_relax_execution_or_invent_samples(tmp_path):
    add(tmp_path, 0, 2000, age=313)
    add(tmp_path, 1, 2010, age=313)
    r = compare_signal_profiles(tmp_path)
    strict = r["fixed_profiles"]["strict_execution_screen"]
    delayed = r["fixed_profiles"]["delayed_observation_research"]
    assert strict["blocked_count"] == 2 and strict["warming_up_count"] == 0
    assert delayed["warming_up_count"] == 2 and delayed["candidate_count"] == 0
    assert not r["execution_policy_changed"] and not r["orders_enabled"]
    assert not r["prospective_validation"]
    assert evaluate_real_paper(tmp_path)["fills"] == []
    assert delayed["report"]["settings"]["lookback"] == 20
