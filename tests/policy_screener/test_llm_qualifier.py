from unittest.mock import MagicMock, patch

from tradingagents.policy_screener.models import Candidate
from tradingagents.policy_screener.llm_qualifier import qualify, parse_llm_score


def _cand():
    return Candidate(ticker="600584.SS", name="长电科技", theme="新质生产力", is_fund=False, sector="半导体")


def test_parse_llm_score_valid_json():
    score, reason = parse_llm_score('{"score": 82, "reason": "机构调研增加但仓位低"}')
    assert score == 82
    assert "仓位低" in reason


def test_parse_llm_score_clamps():
    score, _ = parse_llm_score('{"score": 150, "reason": "x"}')
    assert score == 100
    score, _ = parse_llm_score('{"score": -10, "reason": "x"}')
    assert score == 0


def test_parse_llm_score_bad_json_returns_neutral():
    score, reason = parse_llm_score("这不是JSON")
    assert score == 50
    assert reason != ""


def test_qualify_calls_llm_and_returns_score():
    mock_llm = MagicMock()
    # llm.invoke 返回带 content 属性的对象（langchain AIMessage 风格）
    mock_llm.invoke.return_value = MagicMock(content='{"score": 75, "reason": "政策催化待落地"}')
    score, reason = qualify(_cand(), mock_llm)
    assert score == 75
    assert "催化" in reason
    mock_llm.invoke.assert_called_once()


def test_qualify_degrades_when_llm_none():
    """LLM 客户端为 None（不可用）时降级为中性分，不抛异常。"""
    score, reason = qualify(_cand(), None)
    assert score == 50
    assert reason != ""


def test_qualify_degrades_when_llm_raises():
    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = RuntimeError("API error")
    score, reason = qualify(_cand(), mock_llm)
    assert score == 50
    assert reason != ""