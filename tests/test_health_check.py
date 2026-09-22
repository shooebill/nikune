from unittest import TestCase, mock

from nikune.health_check import HealthChecker


class RunDiagnosticReturnValueTests(TestCase):
    """run_diagnostic()が実際の診断結果（bool）を返すことを検証する回帰テスト。
    修正前はNoneを返し、呼び出し元(main.py)が常にTrue扱いしていた。"""

    def test_run_diagnostic_returns_true_when_all_components_healthy(self) -> None:
        checker = HealthChecker(dry_run=True)
        healthy_results = {
            "database": True,
            "redis": True,
            "twitter_api": True,
            "overall": True,
        }
        with mock.patch.object(checker, "check_all_components", return_value=healthy_results):
            result = checker.run_diagnostic()

        self.assertIs(result, True)

    def test_run_diagnostic_returns_false_when_database_unhealthy(self) -> None:
        checker = HealthChecker(dry_run=True)
        unhealthy_results = {
            "database": False,
            "redis": True,
            "twitter_api": True,
            "overall": False,
        }
        with mock.patch.object(checker, "check_all_components", return_value=unhealthy_results):
            result = checker.run_diagnostic()

        self.assertIs(result, False)

    def test_run_diagnostic_returns_false_when_redis_unhealthy(self) -> None:
        checker = HealthChecker(dry_run=True)
        unhealthy_results = {
            "database": True,
            "redis": False,
            "twitter_api": True,
            "overall": False,
        }
        with mock.patch.object(checker, "check_all_components", return_value=unhealthy_results):
            result = checker.run_diagnostic()

        self.assertIs(result, False)
