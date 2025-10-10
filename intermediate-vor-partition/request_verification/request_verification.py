"""
------------------------------------------------------------
 Modul:    interface-partition/request_verification.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    The Rule and RuleSet classes provide a framework for defining
    and managing verification rules for requests in the VoR
    partition of the Secure IoT Gateway. These classes allow
    for the creation of individual rules, grouping them into
    rule sets, and evaluating requests against these rules to
    determine their validity. The implementation includes
    methods for adding, removing, and evaluating rules, as well
    as handling rule priorities and conditions.

 Autor(en):
    - Yuanchen Zhao (developer for the VoR framework)
    - Heiko Schoon (edited monolithic code into this module)

 Maintainer:
    - tbd

 Hinweis:
    Ongoing development.
------------------------------------------------------------
"""

from defusedxml import ElementTree as ET
from datetime import datetime
import logging

# local imports
from request import Request
from feedback_system import FeedbackSystem

import logging, re
from typing import Any

# 1) What fields are allowed to be referenced from rules?
ALLOWED_FIELDS = {
    "id",
    "issuer_id",
    "issuer_characteristics",
    "request_id",
    "timestamp",
    "description",
    "impact",
    "parameters",
    "modification",
    "priority",
    "Request_verified_status",
}

# 2) Regexes for safety checks
# allow: identifiers, numbers, strings, True/False/None, (), whitespace,
# and these operators/keywords: and or not == != < <= > >= in not in
_ALLOWED_TOKEN_STREAM = re.compile(
    r"""^
        (?:
            \s+ |
            \( | \) |
            (?:and|or|not|in|True|False|None)\b |
            (?:==|!=|<=|>=|<|>) |
            (?:[A-Za-z_][A-Za-z0-9_]*) |
            (?:\d+(?:\.\d+)?) |
            (?:'[^'\\]*(?:\\.[^'\\]*)*' | "[^"\\]*(?:\\.[^"\\]*)*")
        )+$
    """,
    re.VERBOSE,
)

# function-call detector: only 'bool(' is permitted
_FUNC_CALL = re.compile(r'(?<!\w)([A-Za-z_][A-Za-z0-9_]*)\s*\(')

# any obviously-dangerous characters: dot, braces, brackets, dunders, colon, backtick, semicolon
_BAD_CHARS = re.compile(r'[.\[\]{}\\:`;]')

_REQUEST_FIELD = re.compile(r'\brequest\.(\w+)\b')

_logger = logging.getLogger(__name__)

class Rule:
    def __init__(self, rule_id, description, condition):
        self.rule_id = rule_id
        self.description = description
        self.condition = condition  # Boolean expression as a string

    def validate(self, request):
        try:
            _logger.debug(f"Evaluating rule {self.rule_id} for request {request.id}: {self.condition}")
            #return eval(self.condition, {"request": request})
            return self.validate_rule(self.condition, request)
        except Exception:
            _logger.error(f"Error evaluating rule {self.rule_id} for request {request.id}")
            return False
        
    def _primitive(self, value: Any) -> Any:
        """Project request attributes to harmless primitives."""
        # Keep strings/bools/ints/floats; lists/tuples/sets become tuples; dicts become frozenset of items
        # You can tailor this for your fields.
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        if isinstance(value, (list, tuple, set)):
            return tuple(value)
        if isinstance(value, dict):
            return tuple(sorted(value.items()))
        # Fallback: string representation (prevents objects leaking through)
        return str(value)

    def _rewrite_and_validate(self, expr: str) -> tuple[str, dict]:
        """
        - Validate that only allowed request.* fields are referenced.
        - Replace request.<field> with a safe local identifier <field>.
        - Enforce token whitelist and only allow bool() calls.
        Returns: (rewritten_expr, locals_dict)
        """
        locals_map: dict[str, Any] = {}

        # 1) Replace request.<field> with <field> (and collect used fields)
        def repl(m: re.Match) -> str:
            fld = m.group(1)
            if fld not in ALLOWED_FIELDS or fld.startswith("_"):
                raise ValueError(f"Disallowed field: {fld}")
            return fld

        rewritten = _REQUEST_FIELD.sub(repl, expr)

        # 2) Hard rejects: no dots/brackets/braces/dunders/colon/backtick/semicolon remain
        if _BAD_CHARS.search(rewritten) or "__" in rewritten:
            raise ValueError("Disallowed characters/tokens present")

        # 3) Only allow bool(...) as a function call
        for fname in _FUNC_CALL.findall(rewritten):
            if fname != "bool":
                raise ValueError(f"Only bool(...) calls are allowed, found: {fname}")

        # 4) Token stream whitelist
        if not _ALLOWED_TOKEN_STREAM.match(rewritten):
            raise ValueError("Expression contains disallowed tokens")

        # 5) Ensure all bare identifiers are either allowed field names or allowed keywords/bool
        keywords = {"and", "or", "not", "in", "True", "False", "None", "bool"}
        ids = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", rewritten))
        unknown = ids - (ALLOWED_FIELDS | keywords)
        if unknown:
            raise ValueError(f"Unknown identifiers: {', '.join(sorted(unknown))}")

        return rewritten, locals_map

    def validate_rule(self, condition: str, request_obj) -> bool:
        try:
            # Build locals for only the fields that appear (after rewrite we know names)
            rewritten, _ = self._rewrite_and_validate(condition)

            # Collect field values from request, projected to primitives
            # (We scan rewritten to decide which fields are used)
            used_fields = set(re.findall(r"\b(" + "|".join(map(re.escape, ALLOWED_FIELDS)) + r")\b", rewritten))
            locals_dict = {name: self._primitive(getattr(request_obj, name, None)) for name in used_fields}

            # Safe eval: no builtins; expose only our locals and a safe bool
            safe_globals = {"__builtins__": {}}
            safe_locals = {"bool": bool, **locals_dict}

            return bool(eval(rewritten, safe_globals, safe_locals))
        except Exception as e:
            _logger.warning("Rejected/failed condition %r: %s", condition, e)
            return False

# Template of Request Verification Rule Sets
class RuleSet:
    def __init__(self, xml_file):
        self.rules: list[Rule] = []
        self.load_rules_from_xml(xml_file)

    def load_rules_from_xml(self, xml_file):
        tree = ET.parse(xml_file)
        root = tree.getroot()
        for rule in root.findall('rule'):
            rule_id = rule.get('id')
            description = rule.find('description').text
            condition = rule.find('condition').text
            self.rules.append(Rule(rule_id, description, condition))

    def validate_request(self, request: Request):
        failed_rules = []
        for rule in self.rules:
            if not rule.validate(request):
                failed_rules.append(rule.rule_id)
        return failed_rules

# VoR2 Request Verification      
class RequestVerifier:
    def __init__(self, rule_set, feedback_system):
        self.rule_set: RuleSet = rule_set
        self.queue = []  # Priority queue for requests
        self.verified_request_queue = []
        self.feedback_system: FeedbackSystem = feedback_system
        #self.issuer_registry = issuer_registry

    def process_requests(self, request: Request):
        """Process each request in the priority queue and validate it."""
        # Pop the request with the highest priority
        #request = heapq.heappop(self.queue)
        failed_rules = self.rule_set.validate_request(request)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

        # Prepare feedback data
        feedback = {
            "Description": request.description,
            "Priority": request.priority,
            "Verification Result": None,
            "issuer_id": request.issuer_id,
            "request_id": request.id,
            "timestamp": timestamp,
            "step_specific_info": None
        }

        if failed_rules:
            feedback["Verification Result"] = "Rule-based verification failure"
            feedback["step_specific_info"] = f"A specific rule has disapproved the request based on its contents. Failed Rules: {str(failed_rules)}"
            request.Request_verified_status = False
        else:
            request.Request_verified_status = True
            feedback["Verification Result"] = "Verified"
            feedback["step_specific_info"] = "The request is plausible and will be forwarded to the mapping step."
            # ToDo: Dependency-based verification failure
            # Add verified requests to the verified_request_queue
            self.verified_request = request

        # Submit feedback to the feedback system
        _logger.info(f"Request ID {request.id} verification result: {feedback['Verification Result']}")
        self.feedback_system.submit_feedback(feedback)

        # Return the list of verified requests
        return self.verified_request
