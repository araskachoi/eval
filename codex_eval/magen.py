"""Provider-independent, fail-closed adapter. Never forwards a proposal itself."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

POLICY = b'eval-agent-proposal-v1:block-any-detection;no-network;no-rewrite'


class MagenGate:
    def __init__(self, detector=None, policy_digest=None):
        self.detector = detector
        self.policy_digest = policy_digest or hashlib.sha256(POLICY).hexdigest()

    @classmethod
    def isolated_local(cls):
        # The runner stages exactly these reviewed MAGEN files, without mounting its repository.
        if not Path('/run/.containerenv').is_file():
            raise ValueError('Local MAGEN engine may only load inside the isolated test container')
        from gateway.detectors import DetectionEngine
        root = Path('/work/gateway')
        identity = POLICY + (root / 'detectors.py').read_bytes() + (root / 'types.py').read_bytes()
        return cls(DetectionEngine(), hashlib.sha256(identity).hexdigest())

    def inspect(self, text, origin):
        started = time.monotonic()
        reasons = []
        if origin == 'user':
            action = 'allow'
        elif origin not in {'agent','unknown'}:
            action, reasons = 'block', ['unapproved_origin']
        elif not self.detector or not isinstance(text,str) or len(text.encode()) > 32768:
            action, reasons = 'block', ['inspection_error']
        else:
            try:
                detections = self.detector.scan_runtime({'user_input':text})
                for detection in detections:
                    category = detection.category
                    reasons.append('prompt_injection' if 'injection' in category else 'sensitive_data')
                action = 'block' if reasons else 'allow'
            except Exception:
                action, reasons = 'block', ['inspection_error']
        return {'action':action, 'reasons':sorted(set(reasons)), 'policy_digest':self.policy_digest,
                'duration_ms':round((time.monotonic()-started)*1000)}
