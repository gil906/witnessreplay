"""
Case Priority Scoring Service

Calculates priority scores for cases based on:
- Severity (violent crimes higher)
- Age (older cases may need attention)
- Solvability factors (evidence quality, witness reliability)
- Witness count (more witnesses = more priority)
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import logging

from app.models.schemas import Case, CasePriorityScore

logger = logging.getLogger(__name__)

# Severity weights for incident types/subtypes
SEVERITY_WEIGHTS = {
    # Violent crimes (highest priority)
    "homicide": 40,
    "murder": 40,
    "manslaughter": 38,
    "armed_robbery": 35,
    "robbery": 32,
    "assault": 30,
    "aggravated_assault": 35,
    "sexual_assault": 38,
    "kidnapping": 38,
    "domestic_violence": 32,
    
    # Property crimes
    "burglary": 22,
    "theft": 18,
    "vandalism": 12,
    "arson": 28,
    
    # Traffic incidents
    "hit_and_run": 25,
    "fatal_accident": 35,
    "traffic_collision": 20,
    "dui": 22,
    
    # General categories
    "crime": 25,
    "violent_crime": 35,
    "accident": 20,
    "incident": 15,
    "other": 10,
    
    # Severity labels
    "critical": 40,
    "high": 30,
    "medium": 20,
    "low": 10,
}


class PriorityScoringService:
    """Service for calculating case priority scores."""
    
    def calculate_priority(self, case: Case, report_count: int = 0) -> CasePriorityScore:
        """
        Calculate priority score for a case.
        
        Args:
            case: The case to score
            report_count: Number of witness reports in the case
            
        Returns:
            CasePriorityScore with breakdown
        """
        factors = []
        
        # 1. Severity score (max 40 points)
        severity_score = self._calculate_severity_score(case, factors)
        
        # 2. Age score (max 20 points)
        age_score = self._calculate_age_score(case, factors)
        
        # 3. Solvability score (max 25 points)
        solvability_score = self._calculate_solvability_score(case, report_count, factors)
        
        # 4. Witness score (max 15 points)
        witness_score = self._calculate_witness_score(report_count, factors)
        
        # Calculate total
        total_score = min(100, severity_score + age_score + solvability_score + witness_score)
        
        # Determine priority label
        priority_label = self._get_priority_label(total_score)
        
        return CasePriorityScore(
            total_score=round(total_score, 1),
            severity_score=round(severity_score, 1),
            age_score=round(age_score, 1),
            solvability_score=round(solvability_score, 1),
            witness_score=round(witness_score, 1),
            priority_label=priority_label,
            factors=factors,
            calculated_at=datetime.utcnow()
        )
    
    def _calculate_severity_score(self, case: Case, factors: List[str]) -> float:
        """Calculate severity score based on incident type (max 40)."""
        score = 10.0  # Base score
        
        # Check metadata for incident type info
        metadata = case.metadata or {}
        incident_type = metadata.get("incident_type", "").lower()
        incident_subtype = metadata.get("incident_subtype", "").lower()
        severity = metadata.get("severity", "").lower()
        
        # Also check title/summary for keywords
        text_to_check = f"{case.title} {case.summary}".lower()
        
        # Check for explicit severity in metadata
        if severity in SEVERITY_WEIGHTS:
            score = SEVERITY_WEIGHTS[severity]
            factors.append(f"Severity: {severity}")
        
        # Check subtype first (more specific)
        elif incident_subtype in SEVERITY_WEIGHTS:
            score = SEVERITY_WEIGHTS[incident_subtype]
            factors.append(f"Incident subtype: {incident_subtype}")
        
        # Then check incident type
        elif incident_type in SEVERITY_WEIGHTS:
            score = SEVERITY_WEIGHTS[incident_type]
            factors.append(f"Incident type: {incident_type}")
        
        # Check for keywords in text
        else:
            for keyword, weight in sorted(SEVERITY_WEIGHTS.items(), key=lambda x: -x[1]):
                if keyword in text_to_check:
                    score = max(score, weight * 0.8)  # 80% of weight for text matches
                    factors.append(f"Keyword detected: {keyword}")
                    break
        
        return min(40, score)
    
    def _calculate_age_score(self, case: Case, factors: List[str]) -> float:
        """
        Calculate age score (max 20).
        Older open cases get higher scores to ensure they get attention.
        """
        if case.status == "closed":
            return 0.0
        
        now = datetime.utcnow()
        case_age = now - case.created_at
        
        # Score increases with age for open cases
        if case_age > timedelta(days=90):
            factors.append("Case open > 90 days")
            return 20.0
        elif case_age > timedelta(days=60):
            factors.append("Case open > 60 days")
            return 16.0
        elif case_age > timedelta(days=30):
            factors.append("Case open > 30 days")
            return 12.0
        elif case_age > timedelta(days=14):
            factors.append("Case open > 14 days")
            return 8.0
        elif case_age > timedelta(days=7):
            factors.append("Case open > 7 days")
            return 5.0
        elif case_age > timedelta(days=1):
            # Recent cases also get priority
            factors.append("Recent case (< 7 days)")
            return 3.0
        else:
            factors.append("Very recent case (< 24 hours)")
            return 2.0
    
    def _calculate_solvability_score(self, case: Case, report_count: int, factors: List[str]) -> float:
        """
        Calculate solvability score (max 25).
        Based on evidence quality indicators.
        """
        score = 0.0
        
        # Has scene reconstruction
        if case.scene_image_url:
            score += 5
            factors.append("Scene reconstruction available")
        
        # Has summary (analyzed)
        if case.summary and len(case.summary) > 100:
            score += 5
            factors.append("Detailed case summary")
        
        # Has location info
        if case.location and len(case.location) > 5:
            score += 4
            factors.append("Location identified")
        
        # Has timeframe info
        if case.timeframe and case.timeframe.get("description"):
            score += 3
            factors.append("Timeframe established")
        
        # Multiple reports indicate corroboration potential
        if report_count >= 3:
            score += 4
            factors.append("Multiple witness corroboration possible")
        elif report_count >= 2:
            score += 2
            factors.append("Dual witness accounts")
        
        # Check metadata for additional evidence
        metadata = case.metadata or {}
        if metadata.get("has_physical_evidence"):
            score += 4
            factors.append("Physical evidence noted")
        
        if metadata.get("suspect_identified"):
            score += 4
            factors.append("Suspect identified")
        
        return min(25, score)
    
    def _calculate_witness_score(self, report_count: int, factors: List[str]) -> float:
        """
        Calculate witness score (max 15).
        More witnesses = higher priority (more coordination needed).
        """
        if report_count >= 5:
            factors.append(f"{report_count} witnesses")
            return 15.0
        elif report_count >= 4:
            factors.append(f"{report_count} witnesses")
            return 12.0
        elif report_count >= 3:
            factors.append(f"{report_count} witnesses")
            return 10.0
        elif report_count >= 2:
            factors.append(f"{report_count} witnesses")
            return 7.0
        elif report_count == 1:
            factors.append("Single witness")
            return 4.0
        else:
            factors.append("No witness reports")
            return 0.0
    
    def _get_priority_label(self, total_score: float) -> str:
        """Get priority label from total score."""
        if total_score >= 80:
            return "critical"
        elif total_score >= 60:
            return "high"
        elif total_score >= 40:
            return "medium"
        elif total_score >= 20:
            return "normal"
        else:
            return "low"
    
    def sort_cases_by_priority(
        self,
        cases: List[Dict[str, Any]],
        descending: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Sort a list of case dicts by their priority score.
        
        Args:
            cases: List of case dictionaries with priority info
            descending: If True, highest priority first
            
        Returns:
            Sorted list of cases
        """
        return sorted(
            cases,
            key=lambda c: c.get("priority_score", 0) or 0,
            reverse=descending
        )


# Singleton instance
priority_scoring_service = PriorityScoringService()
