import unittest

from app.provider_client import (
    GatewayState,
    SiliconFlowChatAdapter,
    apply_provider_thinking_config,
    build_provider_payload,
)


def provider(api_format: str = "siliconflow_chat") -> dict[str, object]:
    return {
        "api_format": api_format,
        "api_url": "https://api.siliconflow.cn/v1",
        "api_key": "secret",
        "model_name": "model",
        "supports_tool_calling": True,
    }


class SiliconFlowChatAdapterTests(unittest.TestCase):
    def test_builds_siliconflow_thinking_payload(self) -> None:
        request_payload = {
            "model": "deepseek-ai/DeepSeek-V3.1",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 2000,
            "tools": [
                {
                    "name": "search",
                    "description": "Search",
                    "input_schema": {"type": "object"},
                }
            ],
        }
        apply_provider_thinking_config(provider(), request_payload, "high")

        payload = build_provider_payload(
            provider(),
            request_payload,
        )

        self.assertEqual(payload["model"], "deepseek-ai/DeepSeek-V3.1")
        self.assertEqual(payload["stream_options"], {"include_usage": True})
        self.assertEqual(payload["max_tokens"], 2000)
        self.assertIs(payload["enable_thinking"], True)
        self.assertEqual(payload["thinking_budget"], 32000)
        self.assertEqual(payload["tool_choice"], "auto")
        self.assertNotIn("output_config", payload)
        self.assertNotIn("thinking", payload)

    def test_disables_siliconflow_thinking_without_provider_config(self) -> None:
        payload = build_provider_payload(
            provider(),
            {
                "model": "model",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

        self.assertIs(payload["enable_thinking"], False)
        self.assertNotIn("thinking_budget", payload)
        self.assertNotIn("output_config", payload)
        self.assertNotIn("thinking", payload)

    def test_normalizes_legacy_siliconflow_effort_to_high(self) -> None:
        request_payload = {
            "model": "model",
            "messages": [{"role": "user", "content": "hi"}],
        }
        apply_provider_thinking_config(provider(), request_payload, "max")

        payload = build_provider_payload(provider(), request_payload)

        self.assertIs(payload["enable_thinking"], True)
        self.assertEqual(payload["thinking_budget"], 32000)

    def test_applies_siliconflow_thinking_budgets(self) -> None:
        for effort, expected_budget in (
            ("low", 8000),
            ("medium", 16000),
            ("high", 32000),
        ):
            with self.subTest(effort=effort):
                request_payload = {
                    "model": "model",
                    "messages": [{"role": "user", "content": "hi"}],
                }

                apply_provider_thinking_config(provider(), request_payload, effort)
                payload = build_provider_payload(provider(), request_payload)

                self.assertEqual(payload["thinking_budget"], expected_budget)

    def test_converts_reasoning_and_usage_stream_events(self) -> None:
        adapter = SiliconFlowChatAdapter()
        state = GatewayState()

        events = adapter.convert_gateway_event(
            {
                "usage": {
                    "completion_tokens_details": {"reasoning_tokens": 12},
                },
                "choices": [
                    {
                        "delta": {"reasoning_content": "thinking"},
                        "finish_reason": None,
                    }
                ],
            },
            state=state,
        )

        self.assertEqual(events[0]["type"], "usage")
        self.assertEqual(events[1], {"type": "reasoning_start", "index": 1})
        self.assertEqual(
            events[2],
            {"type": "reasoning_delta", "index": 1, "text": "thinking"},
        )


if __name__ == "__main__":
    unittest.main()
