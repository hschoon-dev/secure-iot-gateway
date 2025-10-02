"""
------------------------------------------------------------
 Modul:    interface-partition/feedback_system.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    The feedback system module provides a simple feedback
    mechanism for the VoR partition to submit feedback
    to the interface partition. This is a placeholder...

 Autor(en):
    - Yuanchen Zhao (developer for the VoR framework)
    - Heiko Schoon (created the module skeleton)

 Maintainer:
    - tbd

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

import logging

_logger = logging.getLogger(__name__)

class Feedback:
    # TODO: Add more attributes to feedback
    def __init__(self, text):
        self.text = text

class FeedbackSystem:
    # BUG: Finalize the feedback system
    def __init__(self):
        self.feedback_log = []

    def submit_feedback(self, feedback):
        self.feedback_log.append(feedback)
        _logger.warning(f"Feedback: {feedback}")
        #raise NotImplementedError("Feedback system is not yet implemented.") # TODO: implement feedback system
