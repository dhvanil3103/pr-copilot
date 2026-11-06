class FakeProducer:
    """Records messages instead of sending them to Kafka."""

    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, bytes, bytes]] = []
        self.fail = fail

    async def send_and_wait(self, topic, value=None, key=None, headers=None):
        if self.fail:
            raise ConnectionError("broker down")
        self.sent.append((topic, key, value))
