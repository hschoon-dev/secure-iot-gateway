"""
------------------------------------------------------------
 Modul:    intermediate-vor-partition/mapping_verification.py
 Projekt:  Secure IoT Gateway
------------------------------------------------------------
 Beschreibung:
    The VoR step mapping verification includes the mapping rules,
    mapping process, and mapped request storage. The mapping rules
    are defined in an XML file and loaded into the system. The mapping
    process maps incoming requests to affected endpoints based on the
    defined rules. The mapped requests are stored in a TinyDB database.

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
import json
import logging

from tinydb import TinyDB, Query
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware

# local imports
from request import Request
from feedback_system import FeedbackSystem

# TODO: should be in .env
DB_HOST="192.168.178.117"
DB_PORT=3306
DB_USER="iot_gateway"
DB_PASSWORD="your_secure_password"
DB_NAME="secure_iot_gateway"

_logger = logging.getLogger(__name__)


# Template of Mapping Rules
class Mapping_Rule:
    def __init__(
        self,
        rule_id,
        trigger_condition,
        change_description,
        endpoint_identifier,
        unit_of_change,
        mapping_verification_constraint,
    ):
        self.rule_id = rule_id
        self.trigger_condition = trigger_condition
        self.change_description = change_description
        self.endpoint_identifier = endpoint_identifier
        self.unit_of_change = unit_of_change
        self.mapping_verification_constraint = mapping_verification_constraint

    # def validate(self, request):
    #     try:
    #         return eval(self.condition, {"request": request})
    #     except Exception:
    #         return False


# load rules from xml
class Mapping_RuleSets:
    def __init__(self, xml_file):
        self.rulesets = {}
        self.load_rules_from_xml(xml_file)

    def load_rules_from_xml(self, xml_file):
        tree = ET.parse(xml_file)
        root = tree.getroot()
        for ruleset in root.findall("MappingRuleSet"):
            # load all RuleSet names for impact mapping, key = 'name', value = list of objects
            self.rulesets[ruleset.get("name")] = []

            # Iterate through each Rule element
            for rule in ruleset.findall("Rule"):
                rule_id = rule.get("id")
                trigger_condition = rule.find("TriggerCondition").text
                change_description = rule.find("ChangeDescription").text
                endpoint_identifier = rule.find("EndpointIdentifier").text
                unit_of_change = rule.find("UnitOfChange").text
                mapping_verification_constraint = rule.find(
                    "MappingVerificationConstraint"
                ).text
                self.rulesets[ruleset.get("name")].append(
                    Mapping_Rule(
                        rule_id,
                        trigger_condition,
                        change_description,
                        endpoint_identifier,
                        unit_of_change,
                        mapping_verification_constraint,
                    )
                )
        _logger.debug(f"Loaded Mapping Rule Sets: {self.rulesets}")


# Template of Mapped Requests, Save Mapped Requests directly to a TinyDB database (JSON file)
class MappedRequest:
    """
    TinyDB storage schema (one document per mapped request):
        {
            "request_id": str,
            "generation_timestamp": <json-serializable>,
            "description": <str|dict|list|...>,
            "impact": str,
            "priority": int,
            "tags": <any>,
            "affected_endpoint_list": <list>
        }
    """

    def __init__(
        self,
        request_id,
        generation_timestamp,
        description,
        impact,
        priority,
        tags,
        affected_endpoint_list,
        db_name,
    ):
        self.request_id = request_id
        self.generation_timestamp = generation_timestamp
        self.description = description
        self.impact = impact
        self.priority = priority
        self.tags = tags
        self.affected_endpoint_list = affected_endpoint_list
        self.db_name = db_name

        self._db = None
        self._table = None
        self._init_database()  # Initialize the DB handle when creating a MappedRequest instance

    def _init_database(self):
        """
        Initialize TinyDB (JSON file). Uses caching middleware to reduce I/O.
        """
        try:
            # CachingMiddleware keeps data in memory and flushes on close()
            self._db = TinyDB(self.db_name, storage=CachingMiddleware(JSONStorage))
            self._table = self._db.table("mapped_requests")
            _logger.debug(f"TinyDB initialized: {self.db_name}")
        except Exception as e:
            _logger.error(f"TinyDB Error during database initialization: {e}")
            self._db = None
            self._table = None

    @staticmethod
    def _to_jsonable(value):
        """
        Best-effort conversion to something JSON-serializable for TinyDB/JSON storage.
        - If value is already JSON-serializable: keep it.
        - Otherwise convert to string.
        """
        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)

    def save_to_db(self):
        """
        Upsert by request_id (equivalent to INSERT OR REPLACE).
        """
        if self._db is None or self._table is None:
            _logger.error("TinyDB is not initialized; cannot save mapped request.")
            return False

        # Ensure JSON-serializability (important for TinyDB JSONStorage)
        doc = {
            "request_id": self._to_jsonable(self.request_id),
            "generation_timestamp": self._to_jsonable(self.generation_timestamp),
            "description": self._to_jsonable(self.description),
            "impact": self._to_jsonable(self.impact),
            "priority": self._to_jsonable(self.priority),
            "tags": self._to_jsonable(self.tags),
            "affected_endpoint_list": self._to_jsonable(self.affected_endpoint_list),
        }

        try:
            R = Query()
            # upsert: update if exists, insert if not
            self._table.upsert(doc, R.request_id == self.request_id)

            # Make sure changes are persisted
            self._db.close()
            self._db = None
            self._table = None
            return True
        except Exception as e:
            _logger.error(f"TinyDB Error: {e}")
            try:
                if self._db is not None:
                    self._db.close()
            except Exception:
                pass
            finally:
                self._db = None
                self._table = None
            return False


class RequestMapper:
    def __init__(self, mapping_rule_sets, feedback_system, db_name):
        # dictonary, key = MappingRuleSet.'name', value = list of Mapping_Rule objects
        self.mapping_rule_sets = mapping_rule_sets
        self.feedback_system: FeedbackSystem = feedback_system
        self.db_name = db_name

    def map_requests(self, request: Request):
        affected_endpoint_list = []
        mapping_feedback = {  # TODO: Determine how much feedback information is useful, needed and secure
            "Mapping Result": None,
            "request_id": request.id,
        }

        mapping_rule_set = None
        if self.mapping_rule_sets is not None:
            # In the mapping rule set (.xml), find the corresponding mapping rule set based on the impact
            for key in self.mapping_rule_sets:
                if key == request.impact:
                    # After finding the corresponding rule_set, store it in the local variable mapping_rule_set
                    mapping_rule_set = self.mapping_rule_sets[key]
                    break
                else:
                    # Print Mapping Failure when the corresponding rule set is not found in the mapping ruleset
                    _logger.warning(
                        f"No matching Mapping Rule Set found for impact: {request.impact}"
                    )
                    mapping_feedback[
                        "Mapping Result"
                    ] = "Mapping failed: no matching mapping rule set for this request"
                    self.feedback_system.submit_feedback(mapping_feedback)
                    continue

            if mapping_rule_set is not None:
                # Map the list of affected endpoints according to the rule set
                for mapping_rule in mapping_rule_set:
                    #endpoint_id = mapping_rule.endpoint_identifier + "_" + request.parameters
                    endpoint_id = request.parameters # in the request it is already the real endpoint name

                    # Endpoint change description: relative/absolute (determined based on request.modification)
                    if request.modification.endswith("%"):
                        change_type = "relative, " + request.modification
                    else:
                        change_type = "absolute, " + request.modification

                    unit_of_change = mapping_rule.unit_of_change
                    mapping_verification_constraint = mapping_rule.mapping_verification_constraint

                    # Contains endpoint identifiers, endpoint change descriptions, unit of change, mapping verification constraints
                    affected_endpoint = (
                        endpoint_id,
                        change_type,
                        unit_of_change,
                        mapping_verification_constraint,
                    )
                    affected_endpoint_list.append(affected_endpoint)
            else:
                _logger.warning(f"Mapping Rule Set not found for impact: {request.impact}")
                return

            _logger.info(f"Mapped Request: {affected_endpoint_list}")
        else:
            _logger.error("Mapping Rule Sets not found")
            return

        mapped_request = MappedRequest(
            request.id,
            request.timestamp,
            request.description,
            request.impact,
            request.priority,
            None,
            affected_endpoint_list,
            self.db_name,
        )

        if mapped_request.save_to_db():
            mapping_feedback["Mapping Result"] = "Mapping completed"
            _logger.info(f"Mapping completed for request ID: {request.id}")
            self.feedback_system.submit_feedback(mapping_feedback)
            _logger.info(f"Mapped Request saved to DB: {mapped_request.request_id}")
        else:
            _logger.error(f"Failed to save Mapped Request to DB: {mapped_request.request_id}")
