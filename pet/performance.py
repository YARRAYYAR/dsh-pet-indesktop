# -*- coding: utf-8 -*-
"""轻量系统负载采样与带迟滞的省资源状态判断。"""

from __future__ import annotations

import os
from dataclasses import dataclass


def system_load_ratio() -> float:
    """返回 1 分钟系统负载/逻辑 CPU 数；不支持时安全回退为 0。"""
    try:
        load_1m = float(os.getloadavg()[0])
        cores = max(1, int(os.cpu_count() or 1))
        return max(0.0, load_1m / cores)
    except (AttributeError, OSError, TypeError, ValueError):
        return 0.0


@dataclass
class LoadGovernor:
    """用连续样本和迟滞避免在普通/省资源模式之间频繁跳动。"""

    high_threshold: float = 0.75
    low_threshold: float = 0.50
    enter_samples: int = 2
    exit_samples: int = 3
    constrained: bool = False
    _high_count: int = 0
    _low_count: int = 0

    def observe(self, load_ratio: float) -> bool:
        """记录一次采样，返回 constrained 状态是否发生变化。"""
        previous = self.constrained
        if self.constrained:
            self._high_count = 0
            self._low_count = self._low_count + 1 if load_ratio <= self.low_threshold else 0
            if self._low_count >= self.exit_samples:
                self.constrained = False
                self._low_count = 0
        else:
            self._low_count = 0
            self._high_count = self._high_count + 1 if load_ratio >= self.high_threshold else 0
            if self._high_count >= self.enter_samples:
                self.constrained = True
                self._high_count = 0
        return self.constrained != previous
