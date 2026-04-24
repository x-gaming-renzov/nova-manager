from typing import Any, Dict, List
import hashlib
import struct


class RuleEvaluator:
    def validate_rule_config(self, rule_config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate rule configuration"""
        errors = []
        warnings = []

        if not rule_config:
            errors.append("Rule configuration cannot be empty")
            return {"valid": False, "errors": errors, "warnings": warnings}

        # Check for required fields in rule config
        if "conditions" not in rule_config:
            errors.append("Rule configuration must contain 'conditions'")

        # Validate conditions structure
        if "conditions" in rule_config:
            conditions = rule_config["conditions"]
            if not isinstance(conditions, list):
                errors.append("Conditions must be a list")
            else:
                for i, condition in enumerate(conditions):
                    if not isinstance(condition, dict):
                        errors.append(f"Condition {i} must be an object")
                        continue

                    required_fields = ["field", "operator", "value"]
                    for field in required_fields:
                        if field not in condition:
                            errors.append(
                                f"Condition {i} missing required field: {field}"
                            )

                    # Validate operator
                    valid_operators = [
                        "equals",
                        "not_equals",
                        "greater_than",
                        "less_than",
                        "greater_than_or_equal",
                        "less_than_or_equal",
                        "in",
                        "not_in",
                        "contains",
                        "starts_with",
                        "ends_with",
                    ]
                    if (
                        "operator" in condition
                        and condition["operator"] not in valid_operators
                    ):
                        warnings.append(
                            f"Condition {i} uses unknown operator: {condition['operator']}"
                        )

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    def evaluate_target_percentage(
        self, user_id: str, target_percentage: int, context_id: str = ""
    ) -> bool:
        """
        Evaluate if a user falls within the target percentage using consistent hashing.

        Uses improved distribution algorithm for better A/B testing results.

        Args:
            user_id: Unique identifier for the user
            target_percentage: Target percentage (0-100)
            context_id: Additional context for hashing (experience_id, segment_id, etc.)

        Returns:
            bool: True if user is within target percentage
        """
        if target_percentage <= 0:
            return False

        if target_percentage >= 100:
            return True

        # Create a consistent hash based on user_id and context
        hash_input = f"{user_id}:{context_id}"
        hash_digest = hashlib.sha256(hash_input.encode()).digest()

        # Convert first 8 bytes of hash to unsigned 64-bit integer for better distribution
        hash_int = struct.unpack(">Q", hash_digest[:8])[0]

        # Convert to float between 0.0 and 1.0 with high precision
        # Using the full 64-bit range for maximum distribution uniformity
        percentage_float = hash_int / (2**64 - 1)

        # Convert target percentage to float for comparison
        target_float = target_percentage / 100.0

        result = percentage_float < target_float

        return result

    def evaluate_rule_with_target_percentage(
        self,
        rule_config: Dict[str, Any],
        user_payload: Dict[str, Any],
        user_id: str,
        context_id: str,
        target_percentage: int = 100,
    ) -> bool:
        """
        Generic method to evaluate if user matches rule and falls within target percentage.

        Args:
            rule_config: Rule configuration to evaluate
            user_payload: User payload for rule evaluation
            user_id: User identifier for percentage calculation
            context_id: Context identifier for consistent hashing
            target_percentage: Target percentage for this rule

        Returns:
            bool: True if user matches rule and is within target percentage
        """
        # First check if user matches the rule
        if not self.evaluate_rule(rule_config, user_payload):
            return False

        # Then check if user falls within target percentage
        return self.evaluate_target_percentage(user_id, target_percentage, context_id)

    def bulk_evaluate_rules_with_target_percentage(
        self,
        rules_data: List[Dict[str, Any]],
        user_payload: Dict[str, Any],
        user_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Bulk evaluate multiple rules with target percentages.

        Args:
            rules_data: List of rule data with rule_config, context_id, target_percentage
            user_payload: User payload for rule evaluation
            user_id: User identifier for percentage calculation

        Returns:
            List of rule evaluation results
        """
        results = []

        for rule_data in rules_data:
            context_id = rule_data["context_id"]
            rule_config = rule_data["rule_config"]
            target_percentage = rule_data.get("target_percentage", 100)

            matches = self.evaluate_rule_with_target_percentage(
                rule_config, user_payload, user_id, context_id, target_percentage
            )

            results.append(
                {
                    "context_id": context_id,
                    "matches": matches,
                    "target_percentage": target_percentage,
                }
            )

        return results

    def evaluate_rule(
        self, rule_config: Dict[str, Any], user_payload: Dict[str, Any]
    ) -> bool:
        """
        Generic method to evaluate if user matches a rule based on rule configuration.
        This replaces the old evaluate_segment method.
        """
        return self._evaluate_rule_conditions(rule_config, user_payload)

    def _evaluate_targeting_rules(
        self, targeting_rules: List[Dict[str, Any]], payload: Dict[str, Any]
    ) -> str | None:
        """
        Evaluate targeting rules in order and return the first matching variant.
        """
        for rule in targeting_rules:
            rule_config = rule.get("rule_config")

            if rule_config and self._evaluate_rule_conditions(rule_config, payload):
                variant_name = rule_config.get("variant")
                return variant_name

        return None

    def _evaluate_rule_conditions(
        self, rule_config: Dict[str, Any], payload: Dict[str, Any]
    ) -> bool:
        """Evaluate rule conditions"""
        # Example rule format:
        # {
        #   "conditions": [
        #     {"field": "country", "operator": "equals", "value": "US", "type": "text"},
        #     {"field": "age", "operator": "greater_than", "value": 18, "type": "number"},
        #   ]
        # }

        if "conditions" not in rule_config:
            return False

        for condition in rule_config["conditions"]:
            field = condition.get("field")
            operator = condition.get("operator")
            expected_value = condition.get("value")

            actual_value = payload.get(field)

            if not self._evaluate_condition(actual_value, operator, expected_value):
                return False

        return True

    def _evaluate_condition(
        self, actual_value: Any, operator: str, expected_value: Any
    ) -> bool:
        """Evaluate a single condition"""
        if operator == "equals":
            return actual_value == expected_value
        elif operator == "not_equals":
            return actual_value != expected_value
        elif operator == "greater_than":
            return actual_value is not None and actual_value > expected_value
        elif operator == "less_than":
            return actual_value is not None and actual_value < expected_value
        elif operator == "greater_than_or_equal":
            return actual_value is not None and actual_value >= expected_value
        elif operator == "less_than_or_equal":
            return actual_value is not None and actual_value <= expected_value
        elif operator == "in":
            return actual_value in expected_value
        elif operator == "not_in":
            return actual_value not in expected_value
        elif operator == "contains":
            return actual_value is not None and expected_value in str(actual_value)
        elif operator == "starts_with":
            return actual_value is not None and str(actual_value).startswith(str(expected_value))
        elif operator == "ends_with":
            return actual_value is not None and str(actual_value).endswith(str(expected_value))
        else:
            return False

    def _evaluate_individual_rule(
        self, rule_config: Dict[str, Any], user_id: str, payload: Dict[str, Any]
    ) -> bool:
        """Evaluate individual targeting rule"""
        # Example rule format:
        # {
        #   "user_ids": ["user1", "user2"],
        #   "user_attributes": {"country": "US", "plan": "premium"}
        # }

        # Check user IDs
        if "user_ids" in rule_config:
            if user_id in rule_config["user_ids"]:
                return True

        # Check user attributes from payload
        if "user_attributes" in rule_config:
            for key, expected_value in rule_config["user_attributes"].items():
                if payload.get(key) != expected_value:
                    return False
            return True

        return False
