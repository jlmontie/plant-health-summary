"""
Code-based structure validation tests for plant health assessment responses.

These tests are fast, deterministic, and catch obvious structural issues
before expensive LLM-as-judge evaluation runs.

Run with: pytest tests/test_response_structure.py -v
"""

import pytest
import re
import json


# =============================================================================
# Sample Responses for Testing
# =============================================================================

VALID_RESPONSE = """
## Health Summary

Your Pothos is in good health. All environmental conditions are within the optimal range.

## Current Conditions

- **Soil Moisture:** 45% (Target: 40%)
- **Light:** 800 lux (Target: 750 lux)
- **Temperature:** 72°F (Target: 70°F)
- **Humidity:** 55% (Target: 50%)

## Recommendations

1. **Continue current care routine** - Your plant is thriving in its current location.
2. **Monitor for pests** - Healthy plants can still attract pests, check leaves weekly.
3. **Consider fertilizing** - During growing season, feed every 2-4 weeks.
"""

MISSING_SECTIONS_RESPONSE = """
Your plant looks fine. Water it sometimes and give it light.
"""

HARMFUL_RESPONSE = """
## Health Summary

Your plant is dying.

## Recommendations

1. Pour bleach on the soil to kill any bacteria.
2. Remove all the leaves immediately.
3. Stop watering completely for 3 months.
"""

TOO_SHORT_RESPONSE = "Water it."

TOO_LONG_RESPONSE = "A" * 5001  # Over 5000 chars


# =============================================================================
# Validation Functions (would be imported from main module)
# =============================================================================

def validate_response_structure(response: str) -> dict:
    """
    Validate that a plant health response has required structure.
    
    Returns dict with validation results.
    """
    results = {
        "has_health_summary": False,
        "has_recommendations": False,
        "recommendations_are_actionable": False,
        "length_ok": False,
        "no_harmful_content": True,
        "errors": []
    }
    
    # Check for required sections
    if re.search(r'(health\s+summary|assessment|diagnosis)', response, re.IGNORECASE):
        results["has_health_summary"] = True
    else:
        results["errors"].append("Missing health summary section")
    
    if re.search(r'(recommendation|action|next step|what to do|care tip)', response, re.IGNORECASE):
        results["has_recommendations"] = True
    else:
        results["errors"].append("Missing recommendations section")
    
    # Check recommendations are actionable (contain verbs)
    action_verbs = [
        r'\b(water|move|adjust|check|increase|decrease|add|remove|'
        r'monitor|rotate|repot|fertilize|prune|mist|clean|trim|'
        r'continue|maintain|reduce|improve|place|position)\b'
    ]
    if any(re.search(pattern, response, re.IGNORECASE) for pattern in action_verbs):
        results["recommendations_are_actionable"] = True
    else:
        results["errors"].append("Recommendations lack actionable verbs")
    
    # Check length bounds
    if 50 <= len(response) <= 5000:
        results["length_ok"] = True
    else:
        results["errors"].append(f"Response length {len(response)} outside bounds [50, 5000]")
    
    # Check for harmful content
    harmful_patterns = [
        r'\bbleach\b',
        r'\bmilk\b',
        r'\balcohol\b',
        r'\bpesticide\b(?!.*safely|.*caution|.*careful)',
        r'\bremove all (leaves|roots)\b',
        r'\bstop watering.*\d+\s*(month|week)s?\b',
        r'\b(kill|destroy) the plant\b',
    ]
    for pattern in harmful_patterns:
        if re.search(pattern, response, re.IGNORECASE):
            results["no_harmful_content"] = False
            results["errors"].append(f"Contains potentially harmful content matching: {pattern}")
            break
    
    return results


def is_valid_response(response: str) -> bool:
    """Quick check if response passes all structure validations."""
    results = validate_response_structure(response)
    return all([
        results["has_health_summary"],
        results["has_recommendations"],
        results["recommendations_are_actionable"],
        results["length_ok"],
        results["no_harmful_content"]
    ])


# =============================================================================
# Test Cases
# =============================================================================

class TestResponseStructure:
    """Test suite for response structure validation."""
    
    def test_valid_response_passes(self):
        """A well-structured response should pass all checks."""
        results = validate_response_structure(VALID_RESPONSE)
        
        assert results["has_health_summary"] is True
        assert results["has_recommendations"] is True
        assert results["recommendations_are_actionable"] is True
        assert results["length_ok"] is True
        assert results["no_harmful_content"] is True
        assert len(results["errors"]) == 0
    
    def test_missing_sections_fails(self):
        """Response without clear sections should fail."""
        results = validate_response_structure(MISSING_SECTIONS_RESPONSE)
        
        assert results["has_health_summary"] is False
        assert results["has_recommendations"] is False
        assert len(results["errors"]) >= 2
    
    def test_harmful_content_detected(self):
        """Response with harmful recommendations should fail."""
        results = validate_response_structure(HARMFUL_RESPONSE)
        
        assert results["no_harmful_content"] is False
        assert any("harmful" in e.lower() for e in results["errors"])
    
    def test_too_short_response_fails(self):
        """Very short responses should fail length check."""
        results = validate_response_structure(TOO_SHORT_RESPONSE)
        
        assert results["length_ok"] is False
        assert any("length" in e.lower() for e in results["errors"])
    
    def test_too_long_response_fails(self):
        """Very long responses should fail length check."""
        results = validate_response_structure(TOO_LONG_RESPONSE)
        
        assert results["length_ok"] is False


class TestActionableRecommendations:
    """Test that recommendations contain actionable language."""
    
    @pytest.mark.parametrize("response,expected", [
        ("## Recommendations\n\nWater the plant daily.", True),
        ("## Recommendations\n\nMove it to a brighter spot.", True),
        ("## Recommendations\n\nCheck the roots for rot.", True),
        ("## Recommendations\n\nThe plant is green.", False),
        ("## Recommendations\n\nIt looks nice.", False),
    ])
    def test_actionable_detection(self, response: str, expected: bool):
        """Verify action verb detection works correctly."""
        # Add health summary to pass that check
        full_response = f"## Health Summary\n\nPlant status.\n\n{response}"
        results = validate_response_structure(full_response)
        
        assert results["recommendations_are_actionable"] is expected


class TestHarmfulContentDetection:
    """Test detection of potentially harmful recommendations."""
    
    @pytest.mark.parametrize("content,should_flag", [
        ("Use bleach to clean the pot", True),
        ("Remove all leaves immediately", True),
        ("Stop watering for 3 months", True),
        ("Reduce watering frequency", False),
        ("Use neem oil safely for pest control", False),
        ("Trim yellow leaves", False),
    ])
    def test_harmful_patterns(self, content: str, should_flag: bool):
        """Various harmful content patterns should be caught."""
        response = f"## Health Summary\n\nCheck.\n\n## Recommendations\n\n{content}"
        results = validate_response_structure(response)
        
        if should_flag:
            assert results["no_harmful_content"] is False
        else:
            assert results["no_harmful_content"] is True


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_empty_response(self):
        """Empty response should fail gracefully."""
        results = validate_response_structure("")
        
        assert results["length_ok"] is False
        assert is_valid_response("") is False
    
    def test_none_handling(self):
        """Function should handle None gracefully or raise clear error."""
        with pytest.raises((TypeError, AttributeError)):
            validate_response_structure(None)
    
    def test_unicode_content(self):
        """Unicode characters should be handled correctly."""
        response = """
        ## Health Summary
        
        Your plant is healthy. Temperature: 72°F
        
        ## Recommendations
        
        1. Continue watering regularly
        2. Monitor humidity levels
        """
        results = validate_response_structure(response)
        
        assert results["has_health_summary"] is True
        assert results["recommendations_are_actionable"] is True
    
    def test_exactly_minimum_length(self):
        """Response at exactly minimum length should pass."""
        response = "## Health Summary\nOK\n## Recommendations\nWater it."  # 50 chars
        # Pad to exactly 50 chars
        response = response.ljust(50)
        results = validate_response_structure(response)
        
        assert results["length_ok"] is True
    
    def test_exactly_maximum_length(self):
        """Response at exactly maximum length should pass."""
        base = "## Health Summary\n\nHealthy\n\n## Recommendations\n\nWater daily. "
        response = base + "A" * (5000 - len(base))
        results = validate_response_structure(response)
        
        assert len(response) == 5000
        assert results["length_ok"] is True


# =============================================================================
# Integration Test: Full Validation Pipeline
# =============================================================================

class TestIntegration:
    """Integration tests simulating full evaluation pipeline."""
    
    def test_batch_validation(self):
        """Validate multiple responses and aggregate results."""
        responses = [
            VALID_RESPONSE,
            VALID_RESPONSE.replace("Continue", "Maintain"),  # Slight variation
            MISSING_SECTIONS_RESPONSE,
            HARMFUL_RESPONSE,
        ]
        
        results = [validate_response_structure(r) for r in responses]
        pass_count = sum(1 for r in results if is_valid_response(responses[results.index(r)]))
        
        # We expect 2 passes (the two valid ones) and 2 failures
        assert pass_count == 2
        
        # Calculate pass rate
        pass_rate = pass_count / len(responses)
        assert pass_rate == 0.5
    
    def test_validation_results_serializable(self):
        """Validation results should be JSON-serializable for logging."""
        results = validate_response_structure(VALID_RESPONSE)
        
        # Should not raise
        json_str = json.dumps(results)
        assert isinstance(json_str, str)
        
        # Should round-trip
        parsed = json.loads(json_str)
        assert parsed == results


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
