import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from boss_agent_cli.main import cli
from boss_agent_cli.commands.recruiter.resume_parser import parse_resume
from boss_agent_cli.commands.recruiter.inspect_page import _pick_page_ws, _load_cdp_tabs


def _ctx_mock(mock_cls):
	instance = mock_cls.return_value
	instance.__enter__ = lambda self: self
	instance.__exit__ = lambda self, *a: None
	instance.unwrap_data.side_effect = lambda response: response.get("zpData") if "zpData" in response else response.get("data")
	instance.is_success.side_effect = lambda response: response.get("code", 0) in (0, 200)
	return instance


def _invoke(*args):
	runner = CliRunner()
	return runner.invoke(cli, ["--role", "recruiter", *args])


def _assert_error_contract(parsed: dict, *, code: str, message: str, recoverable: bool, recovery_action: str | None) -> None:
	assert parsed["error"]["code"] == code
	assert parsed["error"]["message"] == message
	assert parsed["error"]["recoverable"] is recoverable
	assert parsed["error"]["recovery_action"] == recovery_action


@patch("boss_agent_cli.commands.recruiter.candidates.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.candidates.AuthManager")
def test_recruiter_candidates_supports_data_envelope(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.search_geeks.return_value = {
		"code": 200,
		"data": {"geekList": [{"name": "候选人A"}], "hasMore": False},
	}
	result = _invoke("hr", "candidates", "python")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["data"]["geekList"][0]["name"] == "候选人A"
	assert parsed["hints"]["next_actions"][0] == "boss hr resume <geek_id> --job-id <id> --security-id <id> — 查看简历"
	assert parsed["hints"]["next_actions"][1] == "boss hr chat — 查看沟通"


@patch("boss_agent_cli.commands.recruiter.candidates.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.candidates.AuthManager")
def test_recruiter_candidates_forwards_filters(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.search_geeks.return_value = {
		"code": 200,
		"data": {"geekList": [], "hasMore": False},
	}
	result = _invoke(
		"hr", "candidates", "python",
		"--city", "101010100",
		"--job-id", "job123",
		"--experience", "3,5",
		"--degree", "201,201",
		"--age", "20,30",
		"--school-level", "1101",
		"--activeness", "2",
		"--source", "5",
		"--salary", "-1,3",
		"--select",
		"--page", "3",
	)
	assert result.exit_code == 0
	mock_platform.search_geeks.assert_called_once_with(
		"python",
		city="101010100",
		page=3,
		job_id="job123",
		experience="3,5",
		degree="201,201",
		age="20,30",
		school_level="1101",
		activeness="2",
		source="5",
		select=True,
		salary="-1,3",
	)


@patch("boss_agent_cli.commands.recruiter.candidates.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.candidates.AuthManager")
def test_recruiter_candidates_reports_error_when_platform_rejects(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.search_geeks.return_value = {"code": 9, "message": "too fast"}
	mock_platform.parse_error.return_value = ("RATE_LIMITED", "too fast")
	result = _invoke("hr", "candidates", "python")
	assert result.exit_code == 1
	parsed = json.loads(result.output)
	_assert_error_contract(
		parsed,
		code="RATE_LIMITED",
		message="too fast",
		recoverable=True,
		recovery_action="等待后重试",
	)


@patch("boss_agent_cli.commands.recruiter.reply.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.reply.AuthManager")
def test_recruiter_reply_maps_invalid_request_contract(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.send_message.return_value = {"code": 121, "message": "请求不合法(121)"}
	mock_platform.is_success.return_value = False
	mock_platform.parse_error.return_value = ("INVALID_PARAM", "请求不合法(121)")
	result = _invoke("hr", "reply", "36226510", "你好")
	assert result.exit_code == 1
	parsed = json.loads(result.output)
	_assert_error_contract(
		parsed,
		code="INVALID_PARAM",
		message="请求不合法(121)",
		recoverable=False,
		recovery_action="修正参数",
	)


@patch("boss_agent_cli.commands.recruiter.chat.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.chat.AuthManager")
def test_recruiter_chat_supports_data_envelope(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.friend_list.return_value = {
		"code": 200,
		"data": {"friendList": [{"name": "候选人B"}]},
	}
	result = _invoke("hr", "chat")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["data"]["friendList"][0]["name"] == "候选人B"
	assert parsed["hints"]["next_actions"][0] == "boss hr resume <geek_id> --job-id <id> --security-id <id> — 查看候选人简历"


@patch("boss_agent_cli.commands.recruiter.chat.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.chat.AuthManager")
def test_recruiter_chat_enriches_last_message_summary(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.friend_list.return_value = {
		"code": 200,
		"data": {"friendList": [{"friendId": 12345, "name": "候选人B", "friendSource": 0}]},
	}
	mock_platform.last_messages.return_value = {
		"code": 200,
		"data": {
			"lastMessageList": [{
				"friendId": 12345,
				"unreadMsgCount": 3,
				"lastMsg": "您好，我对岗位很感兴趣",
				"lastMessageInfo": {"status": 2},
				"lastTime": "05-13 17:28",
			}],
		},
	}
	result = _invoke("hr", "chat")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	item = parsed["data"]["friendList"][0]
	assert item["unread"] == 3
	assert item["msg_status"] == "已读"
	assert item["last_msg"] == "您好，我对岗位很感兴趣"
	assert item["last_time"] == "05-13 17:28"
	mock_platform.last_messages.assert_called_once_with([12345])


@patch("boss_agent_cli.commands.recruiter.chat.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.chat.AuthManager")
def test_recruiter_chatmsg_returns_history_envelope(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.chat_history.return_value = {
		"code": 200,
		"data": {
			"messages": [{
				"msgId": 9001,
				"from": {"name": "招聘者", "type": "boss"},
				"to": {"name": "候选人", "type": "geek"},
				"content": "您好，看了您的简历想进一步沟通",
				"time": "2026-05-12 14:30:00",
				"status": "已读",
			}],
			"hasMore": False,
		},
	}
	result = _invoke("hr", "chatmsg", "12345", "--count", "10")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["command"] == "recruiter-chatmsg"
	assert parsed["data"]["messages"][0]["content"] == "您好，看了您的简历想进一步沟通"
	assert parsed["data"]["hasMore"] is False
	mock_platform.chat_history.assert_called_once_with(12345, count=10, max_msg_id=None)


@patch("boss_agent_cli.commands.recruiter.chat.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.chat.AuthManager")
def test_recruiter_last_messages_returns_batch_summary(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.friend_list.return_value = {
		"code": 200,
		"data": {"friendList": [{"friendId": 12345, "name": "候选人B"}]},
	}
	mock_platform.last_messages.return_value = {
		"code": 200,
		"data": {
			"lastMessageList": [{
				"friendId": 12345,
				"unreadMsgCount": 1,
				"lastMsg": "请问还在招聘吗",
				"lastMessageInfo": {"status": 1},
				"lastTime": "05-14 09:10",
			}],
		},
	}
	result = _invoke("hr", "last-messages")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["command"] == "recruiter-last-messages"
	assert parsed["data"]["friend_ids"] == [12345]
	assert parsed["data"]["messages"][0]["msg_status"] == "未读"
	assert parsed["data"]["messages"][0]["last_msg"] == "请问还在招聘吗"
	mock_platform.last_messages.assert_called_once_with([12345])


@patch("boss_agent_cli.commands.recruiter.chat.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.chat.AuthManager")
def test_recruiter_chat_reports_error_when_platform_rejects(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.friend_list.return_value = {"code": 37, "message": "stoken expired"}
	mock_platform.parse_error.return_value = ("TOKEN_REFRESH_FAILED", "stoken expired")
	result = _invoke("hr", "chat")
	assert result.exit_code == 1
	parsed = json.loads(result.output)
	_assert_error_contract(
		parsed,
		code="TOKEN_REFRESH_FAILED",
		message="stoken expired",
		recoverable=True,
		recovery_action="boss login",
	)


@patch("boss_agent_cli.commands.recruiter.applications.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.applications.AuthManager")
def test_recruiter_applications_supports_data_envelope(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.friend_list.return_value = {
		"code": 200,
		"data": {"friendList": [{"name": "候选人C"}]},
	}
	result = _invoke("hr", "applications")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["data"]["friendList"][0]["name"] == "候选人C"
	assert parsed["hints"]["next_actions"][0] == "boss hr resume <geek_id> --job-id <id> --security-id <id> — 查看候选人简历"
	assert parsed["hints"]["next_actions"][1] == "boss hr chat — 查看沟通列表"


@patch("boss_agent_cli.commands.recruiter.applications.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.applications.AuthManager")
def test_recruiter_applications_reports_error_when_platform_rejects(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.friend_list.return_value = {"code": 36, "message": "account risk"}
	mock_platform.parse_error.return_value = ("ACCOUNT_RISK", "account risk")
	result = _invoke("hr", "applications")
	assert result.exit_code == 1
	parsed = json.loads(result.output)
	_assert_error_contract(
		parsed,
		code="ACCOUNT_RISK",
		message="account risk",
		recoverable=True,
		recovery_action="启动 CDP Chrome 重试，或联系客服",
	)


@patch("boss_agent_cli.commands.recruiter.jobs.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.jobs.AuthManager")
def test_recruiter_jobs_list_supports_data_envelope(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.list_jobs.return_value = {
		"code": 200,
		"data": {"jobList": [{"jobName": "后端工程师"}]},
	}
	result = _invoke("hr", "jobs", "list")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["data"]["jobList"][0]["jobName"] == "后端工程师"


@patch("boss_agent_cli.commands.recruiter.jobs.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.jobs.AuthManager")
def test_recruiter_jobs_list_reports_error_when_platform_rejects(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.list_jobs.return_value = {"code": 9, "message": "too fast"}
	mock_platform.parse_error.return_value = ("RATE_LIMITED", "too fast")
	result = _invoke("hr", "jobs", "list")
	assert result.exit_code == 1
	parsed = json.loads(result.output)
	_assert_error_contract(
		parsed,
		code="RATE_LIMITED",
		message="too fast",
		recoverable=True,
		recovery_action="等待后重试",
	)


@patch("boss_agent_cli.commands.recruiter.jobs.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.jobs.AuthManager")
def test_recruiter_jobs_offline_reports_error_when_platform_rejects(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.job_offline.return_value = {"code": 37, "message": "stoken expired"}
	mock_platform.is_success.return_value = False
	mock_platform.parse_error.return_value = ("TOKEN_REFRESH_FAILED", "stoken expired")
	result = _invoke("hr", "jobs", "offline", "enc-job-1")
	assert result.exit_code == 1
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	_assert_error_contract(
		parsed,
		code="TOKEN_REFRESH_FAILED",
		message="stoken expired",
		recoverable=True,
		recovery_action="boss login",
	)


@patch("boss_agent_cli.commands.recruiter.jobs.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.jobs.AuthManager")
def test_recruiter_jobs_online_reports_error_when_platform_rejects(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.job_online.return_value = {"code": 9, "message": "too fast"}
	mock_platform.is_success.return_value = False
	mock_platform.parse_error.return_value = ("RATE_LIMITED", "too fast")
	result = _invoke("hr", "jobs", "online", "enc-job-1")
	assert result.exit_code == 1
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	_assert_error_contract(
		parsed,
		code="RATE_LIMITED",
		message="too fast",
		recoverable=True,
		recovery_action="等待后重试",
	)


@patch("boss_agent_cli.commands.recruiter.resume.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.resume.AuthManager")
def test_recruiter_resume_exchange_supports_data_envelope(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.exchange_request_by_friend.return_value = {
		"code": 200,
		"data": {"exchangeStatus": "sent"},
	}
	result = _invoke("hr", "resume", "--exchange", "--friend-id", "1")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["data"]["exchangeStatus"] == "sent"
	assert "联系方式交换请求已发送" == parsed["data"]["message"]
	assert parsed["hints"]["next_actions"][0] == "boss hr applications — 返回候选人列表"
	mock_platform.exchange_request_by_friend.assert_called_once_with(1, exchange_type=1)


@patch("boss_agent_cli.commands.recruiter.resume.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.resume.AuthManager")
def test_recruiter_resume_exchange_wechat_maps_to_type_2(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.exchange_request_by_friend.return_value = {"code": 200, "data": {"exchangeStatus": "sent"}}
	result = _invoke("hr", "resume", "--exchange", "--type", "wechat", "--friend-id", "1")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["data"]["exchangeStatus"] == "sent"
	mock_platform.exchange_request_by_friend.assert_called_once_with(1, exchange_type=2)


@patch("boss_agent_cli.commands.recruiter.resume.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.resume.AuthManager")
def test_recruiter_resume_exchange_reports_error_when_platform_rejects(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.exchange_request_by_friend.return_value = {"code": 37, "message": "stoken expired"}
	mock_platform.is_success.return_value = False
	mock_platform.parse_error.return_value = ("TOKEN_REFRESH_FAILED", "stoken expired")
	result = _invoke("hr", "resume", "--exchange", "--friend-id", "1")
	assert result.exit_code == 1
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	_assert_error_contract(
		parsed,
		code="TOKEN_REFRESH_FAILED",
		message="stoken expired",
		recoverable=True,
		recovery_action="boss login",
	)


@patch("boss_agent_cli.commands.recruiter.resume.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.resume.AuthManager")
def test_recruiter_resume_parse_supports_data_envelope(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.view_geek.return_value = {
		"code": 200,
		"data": {
			"geekDetailInfo": {
				"geekBaseInfo": {
					"name": "张三",
					"gender": 1,
					"ageDesc": "28岁",
					"degreeCategory": "本科",
					"workYearDesc": "5年",
					"activeTimeDesc": "今日活跃",
				},
				"showExpectPosition": {
					"positionName": "后端工程师",
					"salaryDesc": "30-40K",
					"locationName": "上海",
				},
			},
		},
	}
	result = _invoke("hr", "resume", "geek-1", "--job-id", "job-1", "--security-id", "sec-1")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["data"]["basic"]["name"] == "张三"
	assert parsed["data"]["expectation"]["position"] == "后端工程师"
	assert parsed["hints"]["next_actions"][0] == "boss hr applications — 返回候选人列表"


@patch("boss_agent_cli.commands.recruiter.resume.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.resume.AuthManager")
def test_recruiter_resume_parse_reports_error_when_platform_rejects(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.view_geek.return_value = {"code": 37, "message": "stoken expired"}
	mock_platform.parse_error.return_value = ("TOKEN_REFRESH_FAILED", "stoken expired")
	result = _invoke("hr", "resume", "geek-1", "--job-id", "job-1", "--security-id", "sec-1")
	assert result.exit_code == 1
	parsed = json.loads(result.output)
	_assert_error_contract(
		parsed,
		code="TOKEN_REFRESH_FAILED",
		message="stoken expired",
		recoverable=True,
		recovery_action="boss login",
	)


@patch("boss_agent_cli.commands.recruiter.reply.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.reply.AuthManager")
def test_recruiter_reply_reports_error_when_platform_rejects(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.send_message_by_friend.return_value = {"code": 9, "message": "too fast"}
	mock_platform.is_success.return_value = False
	mock_platform.parse_error.return_value = ("RATE_LIMITED", "too fast")
	result = _invoke("hr", "reply", "123", "你好")
	assert result.exit_code == 1
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	_assert_error_contract(
		parsed,
		code="RATE_LIMITED",
		message="too fast",
		recoverable=True,
		recovery_action="等待后重试",
	)


@patch("boss_agent_cli.commands.recruiter.reply.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.reply.AuthManager")
def test_recruiter_reply_success_does_not_echo_message_body(mock_auth_cls, mock_platform_cls):
	"""招聘者回复成功信封不应回显聊天正文。"""
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.send_message_by_friend.return_value = {"code": 0, "zpData": {"friendId": 123}}
	private_message = "候选人张三问薪资 30K 可否远程"

	result = _invoke("hr", "reply", "123", private_message)

	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["data"] == {"friend_id": 123, "sent": True}
	assert private_message not in result.output
	mock_platform.send_message_by_friend.assert_called_once_with(123, private_message)


@patch("boss_agent_cli.commands.recruiter.request_resume.get_recruiter_platform_instance")
@patch("boss_agent_cli.commands.recruiter.request_resume.AuthManager")
def test_recruiter_request_resume_reports_error_when_platform_rejects(mock_auth_cls, mock_platform_cls):
	mock_platform = _ctx_mock(mock_platform_cls)
	mock_platform.exchange_request_by_friend.return_value = {"code": 36, "message": "account risk"}
	mock_platform.is_success.return_value = False
	mock_platform.parse_error.return_value = ("ACCOUNT_RISK", "account risk")
	result = _invoke("hr", "request-resume", "123")
	assert result.exit_code == 1
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	_assert_error_contract(
		parsed,
		code="ACCOUNT_RISK",
		message="account risk",
		recoverable=True,
		recovery_action="启动 CDP Chrome 重试，或联系客服",
	)


def test_parse_resume_accepts_data_envelope():
	result = parse_resume(
		{
			"code": 200,
			"data": {
				"geekDetailInfo": {
					"geekBaseInfo": {"name": "李四", "gender": 1},
					"showExpectPosition": {"positionName": "Python 工程师"},
				},
			},
		}
	)
	assert result["basic"]["name"] == "李四"
	assert result["expectation"]["position"] == "Python 工程师"


def test_parse_resume_accepts_unwrapped_payload():
	result = parse_resume(
		{
			"geekDetailInfo": {
				"geekBaseInfo": {"name": "王五", "gender": 0},
				"showExpectPosition": {"positionName": "测试工程师"},
			},
		}
	)
	assert result["basic"]["name"] == "王五"
	assert result["expectation"]["position"] == "测试工程师"


def test_hr_group_rejects_unsupported_zhilian_platform():
	runner = CliRunner()
	result = runner.invoke(cli, ["--platform", "zhilian", "--json", "hr", "candidates", "python"])
	assert result.exit_code == 1
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	assert parsed["error"]["code"] == "PLATFORM_NOT_SUPPORTED"
	assert "暂不支持平台" in parsed["error"]["message"]
	assert "boss --platform zhipin hr ..." == parsed["error"]["recovery_action"]


# ---------------------------------------------------------------------------
# inspect-page 命令测试
# ---------------------------------------------------------------------------

_FAKE_INSPECT_DATA = {
	"url": "https://www.zhipin.com/web/chat/recommend",
	"title": "推荐候选人",
	"readyState": "complete",
	"bodyTextSample": "本科 3年经验 打招呼",
	"buttons": [{"text": "打招呼", "tag": "BUTTON", "className": "", "href": ""}],
	"candidateBlocks": [
		{
			"index": 1,
			"domIndex": 42,
			"tag": "DIV",
			"className": "card",
			"text": "候选人A 本科 3年经验",
			"buttons": [{"text": "打招呼", "tag": "BUTTON", "className": "", "href": ""}],
		}
	],
	"targetTab": {"id": "tab1", "title": "推荐候选人", "url": "https://www.zhipin.com/web/chat/recommend"},
}


@patch("boss_agent_cli.commands.recruiter.inspect_page.inspect_cdp_page")
def test_inspect_page_success(mock_inspect):
	"""inspect-page 成功时输出 JSON envelope。"""
	mock_inspect.return_value = _FAKE_INSPECT_DATA
	result = _invoke("--json", "hr", "inspect-page")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["data"]["candidateBlocks"][0]["text"] == "候选人A 本科 3年经验"
	assert parsed["data"]["targetTab"]["url"] == "https://www.zhipin.com/web/chat/recommend"


@patch("boss_agent_cli.commands.recruiter.inspect_page.inspect_cdp_page")
def test_inspect_page_cdp_unreachable(mock_inspect):
	"""CDP 不可达时输出 CDP_INSPECT_FAILED 错误。"""
	mock_inspect.side_effect = RuntimeError("cannot reach CDP at http://localhost:9222/json")
	result = _invoke("--json", "hr", "inspect-page")
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	assert parsed["error"]["code"] == "CDP_INSPECT_FAILED"
	assert parsed["error"]["recoverable"] is True
	assert "cannot reach CDP" in parsed["error"]["message"]


@patch("boss_agent_cli.commands.recruiter.inspect_page.inspect_cdp_page")
def test_inspect_page_url_contains_forwarded(mock_inspect):
	"""--url-contains 参数正确传入底层函数。"""
	mock_inspect.return_value = _FAKE_INSPECT_DATA
	_invoke("--json", "hr", "inspect-page", "--url-contains", "recommend")
	mock_inspect.assert_called_once()
	_, kwargs = mock_inspect.call_args
	assert kwargs["url_contains"] == "recommend"


# ---------------------------------------------------------------------------
# _pick_page_ws / _load_cdp_tabs 内部函数单元测试
# ---------------------------------------------------------------------------

_TAB_ZHIPIN = {
	"type": "page",
	"url": "https://www.zhipin.com/web/chat/recommend",
	"title": "BOSS",
	"webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/zhipin",
}
_TAB_OTHER = {
	"type": "page",
	"url": "https://www.google.com",
	"title": "Google",
	"webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/other",
}
_TAB_DEVTOOLS = {
	"type": "page",
	"url": "devtools://devtools/inspector.html",
	"title": "DevTools",
	"webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/dt",
}
_TAB_ABOUT = {
	"type": "page",
	"url": "about:blank",
	"title": "",
	"webSocketDebuggerUrl": "ws://localhost:9222/devtools/page/blank",
}


def test_pick_page_ws_prefers_zhipin():
	"""有多个 tab 时优先选 zhipin.com 页面。"""
	ws, tab = _pick_page_ws([_TAB_OTHER, _TAB_ZHIPIN], url_contains=None)
	assert ws == "ws://localhost:9222/devtools/page/zhipin"
	assert tab["url"] == "https://www.zhipin.com/web/chat/recommend"


def test_pick_page_ws_filters_devtools_and_about():
	"""devtools:// 和 about: 页面被过滤。"""
	ws, tab = _pick_page_ws([_TAB_DEVTOOLS, _TAB_ABOUT, _TAB_OTHER], url_contains=None)
	assert ws == "ws://localhost:9222/devtools/page/other"


def test_pick_page_ws_no_page_raises():
	"""无可用 tab 时抛出 RuntimeError。"""
	with pytest.raises(RuntimeError, match="no inspectable page tab found"):
		_pick_page_ws([_TAB_DEVTOOLS, _TAB_ABOUT], url_contains=None)


def test_pick_page_ws_url_contains_filter():
	"""url_contains 能进一步过滤 tab。"""
	ws, tab = _pick_page_ws([_TAB_ZHIPIN, _TAB_OTHER], url_contains="google.com")
	assert tab["url"] == "https://www.google.com"


@patch("urllib.request.urlopen")
def test_load_cdp_tabs_unreachable(mock_urlopen):
	"""CDP HTTP 不可达时抛出 RuntimeError。"""
	mock_urlopen.side_effect = ConnectionRefusedError("refused")
	with pytest.raises(RuntimeError, match="cannot reach CDP"):
		_load_cdp_tabs("http://localhost:9222")


# ---------------------------------------------------------------------------
# recommend-candidates / recommend-action 命令测试
# ---------------------------------------------------------------------------

_FAKE_RECOMMEND_DATA = {
	"page_url": "https://www.zhipin.com/web/chat/recommend",
	"iframe_url": "https://www.zhipin.com/web/frame/recommend/?jobid=null",
	"total_found": 2,
	"candidates": [
		{
			"index": 1,
			"geek_id": "abc123def456",
			"name": "候选人A",
			"base_info": "25岁 27年应届生 本科 刚刚活跃",
			"expect": "期望 北京 算法工程师",
			"edu": "清华大学 计算机 本科",
			"work": "2025.01 2025.06 美团 工程师",
			"tags": ["QS前100院校", "专业前1%"],
			"salary": "面议",
			"avatar_url": "https://img.bosszhipin.com/avatar/a.png",
			"gender": "male",
			"greet_btn": {"text": "打招呼", "disabled": False},
		},
		{
			"index": 2,
			"geek_id": "xyz789ghi012",
			"name": "候选人B",
			"base_info": "23岁 28年应届生 硕士",
			"expect": "期望 上海 后端开发",
			"edu": "北京大学 软件工程 硕士",
			"work": None,
			"tags": ["QS前500院校"],
			"salary": "15-25K",
			"avatar_url": "https://img.bosszhipin.com/avatar/b.png",
			"gender": "female",
			"greet_btn": {"text": "打招呼", "disabled": False},
		},
	],
	"targetTab": {"id": "tab1", "title": "推荐候选人", "url": "https://www.zhipin.com/web/chat/recommend"},
}


@patch("boss_agent_cli.commands.recruiter.recommend._collect_candidates")
def test_recommend_candidates_success(mock_collect):
	"""recommend-candidates 成功时输出候选人 JSON。"""
	mock_collect.return_value = _FAKE_RECOMMEND_DATA
	result = _invoke("--json", "hr", "recommend-candidates")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["data"]["total_found"] == 2
	assert len(parsed["data"]["candidates"]) == 2
	assert parsed["data"]["candidates"][0]["geek_id"] == "abc123def456"
	assert parsed["data"]["candidates"][0]["name"] == "候选人A"
	assert parsed["data"]["candidates"][0]["tags"] == ["QS前100院校", "专业前1%"]


@patch("boss_agent_cli.commands.recruiter.recommend._collect_candidates")
def test_recommend_candidates_cdp_unreachable(mock_collect):
	"""CDP 不可达时输出 CDP_RECOMMEND_FAILED。"""
	mock_collect.side_effect = RuntimeError("cannot reach CDP")
	result = _invoke("--json", "hr", "recommend-candidates")
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	assert parsed["error"]["code"] == "CDP_RECOMMEND_FAILED"
	assert parsed["error"]["recoverable"] is True


@patch("boss_agent_cli.commands.recruiter.recommend._collect_candidates")
def test_recommend_candidates_empty_page(mock_collect):
	"""页面无候选人时返回空列表。"""
	mock_collect.return_value = {
		"page_url": "https://www.zhipin.com/web/chat/recommend",
		"iframe_url": "https://www.zhipin.com/web/frame/recommend/",
		"total_found": 0,
		"candidates": [],
		"targetTab": {"id": "tab1", "title": "推荐", "url": "https://www.zhipin.com/web/chat/recommend"},
	}
	result = _invoke("--json", "hr", "recommend-candidates")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["data"]["total_found"] == 0
	assert parsed["data"]["candidates"] == []


@patch("boss_agent_cli.commands.recruiter.recommend._collect_candidates")
def test_recommend_candidates_limit_forwarded(mock_collect):
	"""--limit 参数正确传入底层函数。"""
	mock_collect.return_value = _FAKE_RECOMMEND_DATA
	_invoke("--json", "hr", "recommend-candidates", "--limit", "10")
	mock_collect.assert_called_once()
	_, kwargs = mock_collect.call_args
	assert kwargs["limit"] == 10


@patch("boss_agent_cli.commands.recruiter.recommend._execute_action")
def test_recommend_action_success(mock_action):
	"""recommend-action 成功点击时输出确认信息。"""
	mock_action.return_value = {
		"clicked": True,
		"geek_id": "abc123def456",
		"candidate_name": "候选人A",
		"button_text": "打招呼",
		"confirmation": {
			"button_changed": True,
			"old_button_text": "打招呼",
			"new_button_text": "已沟通",
			"disabled_changed": False,
			"toast_detected": None,
			"confidence": "high",
		},
		"targetTab": {"id": "tab1", "title": "推荐", "url": "https://www.zhipin.com/web/chat/recommend"},
	}
	result = _invoke("--json", "hr", "recommend-action", "abc123def456")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["data"]["clicked"] is True
	assert parsed["data"]["geek_id"] == "abc123def456"
	assert parsed["data"]["confirmation"]["confidence"] == "high"


@patch("boss_agent_cli.commands.recruiter.recommend._execute_action")
def test_recommend_action_button_not_found(mock_action):
	"""按钮文本不匹配时输出 BUTTON_NOT_FOUND。"""
	mock_action.return_value = {
		"clicked": False,
		"error": "button_not_found",
		"message": 'no button matching "不存在"',
		"available_buttons": ["打招呼"],
	}
	result = _invoke("--json", "hr", "recommend-action", "abc123def456", "--button", "不存在")
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	assert parsed["error"]["code"] == "BUTTON_NOT_FOUND"


@patch("boss_agent_cli.commands.recruiter.recommend._execute_action")
def test_recommend_action_cdp_unreachable(mock_action):
	"""CDP 不可达时输出 CDP_ACTION_FAILED。"""
	mock_action.side_effect = RuntimeError("cannot reach CDP")
	result = _invoke("--json", "hr", "recommend-action", "abc123def456")
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	assert parsed["error"]["code"] == "CDP_ACTION_FAILED"


@patch("boss_agent_cli.commands.recruiter.recommend._execute_action")
def test_recommend_action_candidate_not_found(mock_action):
	"""geek_id 在页面上找不到时输出 CANDIDATE_NOT_FOUND。"""
	mock_action.return_value = {
		"clicked": False,
		"error": "candidate_not_found",
		"message": "no card with geekid=unknown123 found; re-run recommend-candidates",
	}
	result = _invoke("--json", "hr", "recommend-action", "unknown123")
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	assert parsed["error"]["code"] == "CANDIDATE_NOT_FOUND"


@patch("boss_agent_cli.commands.recruiter.recommend._execute_action")
def test_recommend_action_confirms_button_change(mock_action):
	"""按钮文案变化时 confidence=high。"""
	mock_action.return_value = {
		"clicked": True,
		"geek_id": "abc123def456",
		"candidate_name": "候选人A",
		"button_text": "打招呼",
		"confirmation": {
			"button_changed": True,
			"old_button_text": "打招呼",
			"new_button_text": "已沟通",
			"disabled_changed": False,
			"toast_detected": None,
			"confidence": "high",
		},
		"targetTab": {"id": "t1", "title": "推荐", "url": "https://www.zhipin.com/web/chat/recommend"},
	}
	result = _invoke("--json", "hr", "recommend-action", "abc123def456")
	parsed = json.loads(result.output)
	assert parsed["data"]["confirmation"]["button_changed"] is True
	assert parsed["data"]["confirmation"]["confidence"] == "high"


@patch("boss_agent_cli.commands.recruiter.recommend._execute_action")
def test_recommend_action_no_confirmation_signal(mock_action):
	"""无变化信号时 confidence=medium。"""
	mock_action.return_value = {
		"clicked": True,
		"geek_id": "abc123def456",
		"candidate_name": "候选人A",
		"button_text": "打招呼",
		"confirmation": {
			"button_changed": False,
			"old_button_text": "打招呼",
			"new_button_text": "打招呼",
			"disabled_changed": False,
			"toast_detected": None,
			"confidence": "medium",
		},
		"targetTab": {"id": "t1", "title": "推荐", "url": "https://www.zhipin.com/web/chat/recommend"},
	}
	result = _invoke("--json", "hr", "recommend-action", "abc123def456")
	parsed = json.loads(result.output)
	assert parsed["data"]["confirmation"]["confidence"] == "medium"


# ---------------------------------------------------------------------------
# 安全性 & 健壮性测试
# ---------------------------------------------------------------------------

@patch("boss_agent_cli.commands.recruiter.recommend._execute_action")
def test_recommend_action_selector_injection_geek_id(mock_action):
	"""含引号的 geek_id 不应导致 CSS 选择器注入，应正常传递到底层。"""
	malicious_id = 'abc"][data-geekid="xyz'
	mock_action.return_value = {
		"clicked": False,
		"error": "candidate_not_found",
		"message": f"no card with geekid={malicious_id} found; re-run recommend-candidates",
	}
	result = _invoke("--json", "hr", "recommend-action", malicious_id)
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	assert parsed["error"]["code"] == "CANDIDATE_NOT_FOUND"
	# 验证 geek_id 完整传入底层函数，未被截断
	_, kwargs = mock_action.call_args
	assert kwargs["geek_id"] == malicious_id


@patch("boss_agent_cli.commands.recruiter.recommend._execute_action")
def test_recommend_action_iframe_not_ready(mock_action):
	"""iframe 未加载完成时应返回 iframe_not_ready 而非 access_denied。"""
	mock_action.return_value = {
		"clicked": False,
		"error": "iframe_not_ready",
		"message": "iframe is still loading or cross-origin; wait a moment and retry",
	}
	result = _invoke("--json", "hr", "recommend-action", "some_geek_id")
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	assert parsed["error"]["code"] == "IFRAME_NOT_READY"
	assert "retry" in parsed["error"]["message"]


@patch("boss_agent_cli.commands.recruiter.recommend._collect_candidates")
def test_recommend_candidates_iframe_not_found(mock_collect):
	"""推荐页面未打开时应返回 iframe_not_found 错误。"""
	mock_collect.side_effect = RuntimeError("iframe_not_found: recommendFrame iframe not found; ensure you are on the recommend page")
	result = _invoke("--json", "hr", "recommend-candidates")
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	assert parsed["error"]["code"] == "CDP_RECOMMEND_FAILED"
	assert "iframe" in parsed["error"]["message"]


@patch("boss_agent_cli.commands.recruiter.recommend._execute_action")
def test_recommend_action_button_disabled(mock_action):
	"""按钮已被禁用（已打过招呼）时应报告 button_disabled。"""
	mock_action.return_value = {
		"clicked": False,
		"error": "button_disabled",
		"message": 'button "打招呼" is already disabled (may have been clicked)',
	}
	result = _invoke("--json", "hr", "recommend-action", "abc123def456")
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	assert parsed["error"]["code"] == "BUTTON_DISABLED"


@patch("boss_agent_cli.commands.recruiter.recommend._execute_action")
def test_recommend_action_default_button_text(mock_action):
	"""不传 --button 时默认使用 '打招呼'。"""
	mock_action.return_value = {
		"clicked": True,
		"geek_id": "abc123",
		"candidate_name": "测试",
		"button_text": "打招呼",
		"confirmation": {
			"button_changed": False,
			"old_button_text": "打招呼",
			"new_button_text": "打招呼",
			"disabled_changed": False,
			"toast_detected": None,
			"confidence": "medium",
		},
		"targetTab": {"id": "t1", "title": "推荐", "url": "https://www.zhipin.com/web/chat/recommend"},
	}
	_invoke("--json", "hr", "recommend-action", "abc123")
	_, kwargs = mock_action.call_args
	assert kwargs["button_text"] == "打招呼"


# ---------------------------------------------------------------------------
# navigate 命令测试
# ---------------------------------------------------------------------------

@patch("boss_agent_cli.commands.recruiter.inspect_page.navigate_cdp_page")
def test_navigate_success(mock_nav):
	"""navigate 成功时输出导航结果。"""
	mock_nav.return_value = {
		"navigated_to": "https://www.zhipin.com/web/chat/index",
		"page_url": "https://www.zhipin.com/web/chat/index",
		"page_title": "BOSS直聘-沟通",
		"ready_state": "complete",
		"previous_url": "https://www.zhipin.com/web/chat/recommend",
		"targetTab": {"id": "tab1", "title": "BOSS", "url": "https://www.zhipin.com/web/chat/recommend"},
	}
	result = _invoke("--json", "hr", "navigate", "https://www.zhipin.com/web/chat/index")
	assert result.exit_code == 0
	parsed = json.loads(result.output)
	assert parsed["ok"] is True
	assert parsed["data"]["navigated_to"] == "https://www.zhipin.com/web/chat/index"
	assert parsed["data"]["previous_url"] == "https://www.zhipin.com/web/chat/recommend"


@patch("boss_agent_cli.commands.recruiter.inspect_page.navigate_cdp_page")
def test_navigate_cdp_unreachable(mock_nav):
	"""CDP 不可达时输出 CDP_NAVIGATE_FAILED。"""
	mock_nav.side_effect = RuntimeError("cannot reach CDP")
	result = _invoke("--json", "hr", "navigate", "https://www.zhipin.com/web/chat/index")
	parsed = json.loads(result.output)
	assert parsed["ok"] is False
	assert parsed["error"]["code"] == "CDP_NAVIGATE_FAILED"
	assert parsed["error"]["recoverable"] is True
