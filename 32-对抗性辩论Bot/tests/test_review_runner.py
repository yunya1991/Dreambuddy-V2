"""review_runner 测试：结构化评审输出、裁判、降级。"""
from core.review_runner import run_review_sync


class FakeLLM:
    provider = "fake"
    model = "fake-model"

    async def chat(self, system_prompt, user_prompt, max_tokens=None):
        if "裁判" in system_prompt:
            return (
                '{"summary":"双方有分歧","winner":"bear",'
                '"key_insights":["证据不足"],"topic_angle":"先补底座"}'
            )
        if "提出 2-3 个针对性质询问题" in user_prompt:
            return '{"questions":["数据来源是什么？"]}'
        if "对方质询问题" in user_prompt:
            return '{"answers":["来源是 CoinGecko"]}'
        if "反方" in system_prompt:
            return (
                '{"thesis":"反方论点","arguments":["a2","b2"],'
                '"quote":"q2","confidence":0.7}'
            )
        return '{"thesis":"正方论点","arguments":["a1","b1"],"quote":"q1","confidence":0.8}'


class FakeAdjudication:
    def to_dict(self):
        return {"winner": "bull", "bull_total": 24, "bear_total": 20,
                "rfd": "正方论据更充分"}


class FakeAdjudicator:
    def adjudicate(self, topic, transcript, verdict):
        return FakeAdjudication()


class InvalidLLM:
    provider = "invalid"
    model = "invalid-model"

    async def chat(self, system_prompt, user_prompt, max_tokens=None):
        return "not json"


def test_run_review_structured_output():
    result = run_review_sync(
        "测试命题", background="背景", rounds=2,
        debater_llm=FakeLLM(), judge_llm=FakeLLM(),
    )
    payload = result.to_dict()
    assert payload["status"] == "completed"
    assert len(payload["transcript"]) == 4
    assert payload["verdict"]["winner"] == "bear"
    assert payload["verdict"]["key_insights"] == ["证据不足"]
    assert payload["meta"]["provider"] == "fake"


def test_run_review_judge_disabled():
    result = run_review_sync(
        "测试命题", rounds=1, judge=False,
        debater_llm=FakeLLM(), judge_llm=FakeLLM(),
    )
    payload = result.to_dict()
    assert payload["verdict"] is None
    assert len(payload["transcript"]) == 2


def test_run_review_adjudication():
    result = run_review_sync(
        "测试命题", rounds=1,
        debater_llm=FakeLLM(), judge_llm=FakeLLM(),
        adjudicator=FakeAdjudicator(),
    )
    payload = result.to_dict()
    assert payload["adjudication"]["winner"] == "bull"
    assert payload["meta"]["adjudication"] is True


def test_run_review_cross_examination():
    result = run_review_sync(
        "测试命题", rounds=2, cross_examination=True,
        debater_llm=FakeLLM(), judge_llm=FakeLLM(),
        adjudication=False,
    )
    payload = result.to_dict()
    exams = [t for t in payload["transcript"]
             if "questioner" in t["content"]]
    assert len(exams) == 2
    assert exams[0]["content"]["questioner"] == "bear"
    assert exams[1]["content"]["questioner"] == "bull"


def test_run_review_degraded_on_invalid_json():
    result = run_review_sync(
        "测试命题", rounds=1,
        debater_llm=InvalidLLM(), judge_llm=InvalidLLM(),
    )
    payload = result.to_dict()
    assert payload["status"] == "completed"
    assert payload["meta"]["degraded"] is True
    assert payload["meta"]["degraded_turns"]
    assert payload["verdict"]["winner"] is None