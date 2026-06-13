import json
import os
import time
from collections import deque


class ProgressStore:
    def __init__(self, dataFolder):
        self.path = os.path.join(dataFolder, "progress.json")

    def load(self):
        if not os.path.isfile(self.path):
            return None
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                state = json.load(file)
        except (OSError, ValueError):
            return None
        if state.get("version") != 1:
            return None
        return state

    def save(self, state):
        state["version"] = 1
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as file:
            json.dump(state, file, indent=2)

    def clear(self):
        try:
            os.remove(self.path)
        except OSError:
            pass


class RateTracker:
    def __init__(self, windowSeconds=120):
        self.windowSeconds = windowSeconds
        self.samples = deque()
        self.total = 0

    def record(self, count):
        now = time.monotonic()
        self.samples.append((now, count))
        self.total += count
        self.trim(now)

    def trim(self, now):
        while self.samples and now - self.samples[0][0] > self.windowSeconds:
            _, old = self.samples.popleft()
            self.total -= old

    def perSecond(self):
        now = time.monotonic()
        self.trim(now)
        if not self.samples:
            return 0.0
        elapsed = now - self.samples[0][0]
        if elapsed < 1.0:
            elapsed = 1.0
        return self.total / elapsed
