from locust import HttpUser, between, task


class WorldCupUser(HttpUser):
    wait_time = between(0.1, 0.3)

    @task(3)
    def compare_brazil_france(self):
        self.client.post(
            "/agent",
            json={"team_a": "巴西", "team_b": "法国", "query": "谁更可能赢"},
            headers={"X-Trace-Id": "locust-wc"},
        )

    @task(2)
    def compare_argentina_germany(self):
        self.client.post(
            "/agent",
            json={"team_a": "阿根廷", "team_b": "德国"},
            headers={"X-Trace-Id": "locust-wc"},
        )

    @task(1)
    def health_check(self):
        self.client.get("/health")
