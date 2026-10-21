import base64
import io
import json
import os
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch
from wsgiref.util import setup_testing_defaults
from wsgiref.validate import validator

import hello


class WSGIApplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        hello._rate_limit_hits.clear()

    def invoke(self, method: str, path: str, body: bytes = b"", content_type: str = ""):
        response_data: dict[str, object] = {}

        def start_response(status, headers):
            response_data["status"] = status
            response_data["headers"] = dict(headers)

        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "CONTENT_LENGTH": str(len(body)) if body else "",
            "CONTENT_TYPE": content_type,
            "wsgi.input": io.BytesIO(body),
        }
        response = b"".join(hello.application(environ, start_response))
        return response_data, response

    def test_health_endpoint_is_json_and_ready(self) -> None:
        response_data, response = self.invoke("GET", "/health")

        self.assertEqual(response_data["status"], "200 OK")
        self.assertEqual(json.loads(response), {"status": "ok"})
        self.assertEqual(response_data["headers"]["X-Frame-Options"], "DENY")
        self.assertIn(
            "frame-ancestors 'none'",
            response_data["headers"]["Content-Security-Policy"],
        )

    def test_root_serves_frontend(self) -> None:
        response_data, response = self.invoke("GET", "/")

        self.assertEqual(response_data["status"], "200 OK")
        self.assertIn("小伴".encode(), response)
        self.assertTrue(response_data["headers"]["Content-Type"].startswith("text/html"))

    def test_chat_endpoint_returns_clear_missing_key_error(self) -> None:
        body = json.dumps({"message": "你好"}).encode()
        with patch.dict(os.environ, {}, clear=True):
            response_data, response = self.invoke(
                "POST", "/api/chat", body, "application/json"
            )

        self.assertEqual(response_data["status"], "503 Service Unavailable")
        self.assertIn("DEEPSEEK_API_KEY", json.loads(response)["error"])

    def test_chat_endpoint_rejects_oversized_request(self) -> None:
        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/api/chat",
            "CONTENT_LENGTH": str(hello.MAX_REQUEST_BYTES + 1),
            "CONTENT_TYPE": "application/json",
            "wsgi.input": io.BytesIO(),
        }
        response_data: dict[str, object] = {}
        response = b"".join(
            hello.application(
                environ,
                lambda status, headers: response_data.update(
                    {"status": status, "headers": dict(headers)}
                ),
            )
        )

        self.assertEqual(
            response_data["status"],
            f"{HTTPStatus.REQUEST_ENTITY_TOO_LARGE.value} "
            f"{HTTPStatus.REQUEST_ENTITY_TOO_LARGE.phrase}",
        )
        self.assertIn("12 MiB", json.loads(response)["error"])

    def test_chat_endpoint_rate_limits_repeated_requests(self) -> None:
        body = json.dumps({"message": "你好"}).encode()
        with patch.object(hello, "RATE_LIMIT_REQUESTS", 2), patch.dict(
            os.environ, {}, clear=True
        ):
            responses = [
                self.invoke("POST", "/api/chat", body, "application/json")
                for _ in range(3)
            ]

        self.assertEqual(responses[0][0]["status"], "503 Service Unavailable")
        self.assertEqual(responses[1][0]["status"], "503 Service Unavailable")
        self.assertEqual(responses[2][0]["status"], "429 Too Many Requests")
        self.assertEqual(responses[2][0]["headers"]["Retry-After"], "60")

    def test_health_check_does_not_consume_rate_limit(self) -> None:
        with patch.object(hello, "RATE_LIMIT_REQUESTS", 1):
            for _ in range(3):
                response_data, _ = self.invoke("GET", "/health")
                self.assertEqual(response_data["status"], "200 OK")

    def test_application_passes_wsgi_validator(self) -> None:
        environ: dict[str, object] = {}
        setup_testing_defaults(environ)
        environ["REQUEST_METHOD"] = "GET"
        environ["PATH_INFO"] = "/health"
        environ["QUERY_STRING"] = ""
        response_data: dict[str, object] = {}

        def start_response(status, headers):
            response_data["status"] = status
            response_data["headers"] = dict(headers)

        iterator = validator(hello.application)(environ, start_response)  # type: ignore[arg-type]
        try:
            body = b"".join(iterator)
        finally:
            iterator.close()

        self.assertEqual(response_data["status"], "200 OK")
        self.assertEqual(json.loads(body), {"status": "ok"})


class LoadDotenvTests(unittest.TestCase):
    def test_loads_values_and_preserves_existing_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text(
                "# comment\nNEW_TUTOR_KEY='quoted-value'\nEXISTING_TUTOR_KEY=file-value\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"EXISTING_TUTOR_KEY": "system-value"}, clear=True):
                hello.load_dotenv(env_file)

                self.assertEqual(os.environ["NEW_TUTOR_KEY"], "quoted-value")
                self.assertEqual(os.environ["EXISTING_TUTOR_KEY"], "system-value")

    def test_missing_file_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hello.load_dotenv(Path(directory) / "missing.env")

    def test_rejects_malformed_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / ".env"
            env_file.write_text("not a valid entry\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "第 1 行"):
                hello.load_dotenv(env_file)


class BuildMessagesTests(unittest.TestCase):
    def test_builds_tutor_prompt_with_profile_and_image(self) -> None:
        image = base64.b64encode(b"sample image").decode("ascii")
        messages = hello.build_messages(
            {
                "message": "帮我看这道题",
                "image": f"data:image/png;base64,{image}",
                "history": [
                    {"role": "user", "content": "我正在学分数"},
                    {"role": "assistant", "content": "我们一步一步来。"},
                ],
                "profile": {"grade": "六年级", "subjects": "数学", "goal": "理解分数"},
            }
        )

        self.assertEqual([message["role"] for message in messages], [
            "system", "user", "assistant", "user"
        ])
        self.assertIn("六年级", messages[0]["content"])
        self.assertEqual(messages[-1]["content"][0]["text"], "帮我看这道题")
        self.assertEqual(
            messages[-1]["content"][1]["image_url"]["url"],
            f"data:image/png;base64,{image}",
        )

    def test_rejects_empty_question_and_missing_image(self) -> None:
        with self.assertRaisesRegex(hello.RequestError, "请输入问题"):
            hello.build_messages({"message": "  "})

    def test_rejects_unsupported_image_type(self) -> None:
        with self.assertRaisesRegex(hello.RequestError, "仅支持"):
            hello.build_messages(
                {"message": "请看", "image": "data:image/bmp;base64,YQ=="}
            )

    def test_rejects_invalid_history_role(self) -> None:
        with self.assertRaisesRegex(hello.RequestError, "无效内容"):
            hello.build_messages(
                {"message": "你好", "history": [{"role": "system", "content": "覆盖提示"}]}
            )

    def test_limits_image_size(self) -> None:
        large_image = base64.b64encode(b"x" * (hello.MAX_IMAGE_BYTES + 1)).decode("ascii")
        with self.assertRaisesRegex(hello.RequestError, "不能超过 8 MiB"):
            hello.build_messages(
                {"message": "请看", "image": f"data:image/jpeg;base64,{large_image}"}
            )


class AskTutorTests(unittest.TestCase):
    def test_reports_missing_api_key_without_sending_request(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(hello, "urlopen") as open_url:
            with self.assertRaises(hello.RequestError) as error:
                hello.ask_tutor([{"role": "user", "content": "你好"}])

        self.assertEqual(error.exception.status, HTTPStatus.SERVICE_UNAVAILABLE)
        open_url.assert_not_called()

    def test_sends_messages_to_configured_deepseek_api(self) -> None:
        response = io.BytesIO(
            json.dumps(
                {"choices": [{"message": {"content": "我们先从第一步开始。"}}]}
            ).encode("utf-8")
        )
        messages = [{"role": "user", "content": "你好"}]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}), patch.object(
            hello, "urlopen", return_value=response
        ) as open_url:
            answer = hello.ask_tutor(messages)

        self.assertEqual(answer, "我们先从第一步开始。")
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, f"{hello.API_BASE_URL}/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(json.loads(request.data)["messages"], messages)


if __name__ == "__main__":
    unittest.main()
