"""Request models must not expose an email/user_email field (data isolation)."""
import unittest


class RequestModelTests(unittest.TestCase):
    def test_email_sections_request_has_no_email(self):
        from src.api.settings import EmailSectionsRequest
        self.assertNotIn("email", EmailSectionsRequest.model_fields)

    def test_context_requests_have_no_email(self):
        from src.api.context import AddContextRequest, AddRuleRequest
        self.assertNotIn("email", AddContextRequest.model_fields)
        self.assertNotIn("email", AddRuleRequest.model_fields)

    def test_create_task_from_block_request_has_no_email(self):
        from src.api.daily_schedule import CreateTaskFromBlockRequest
        self.assertNotIn("email", CreateTaskFromBlockRequest.model_fields)

    def test_draft_send_request_has_no_user_email(self):
        from src.api.approval import DraftSendRequest
        self.assertNotIn("user_email", DraftSendRequest.model_fields)


if __name__ == "__main__":
    unittest.main()
