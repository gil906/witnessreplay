"""
Witness reliability scoring service.

Tracks witness accuracy over time by counting contradictions vs confirmations,
tracking correction frequency, and comparing with physical evidence.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass
import uuid

logger = logging.getLogger(__name__)


@dataclass
class ReliabilityFactors:
    """Individual factors contributing to the reliability score."""
    contradiction_rate: float  # 0.0-1.0, lower is better
    correction_frequency: float  # 0.0-1.0, lower is better
    consistency_score: float  # 0.0-1.0, higher is better
    evidence_alignment: float  # 0.0-1.0, higher is better
    statement_detail: float  # 0.0-1.0, higher is better
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "contradiction_rate": round(self.contradiction_rate, 3),
            "correction_frequency": round(self.correction_frequency, 3),
            "consistency_score": round(self.consistency_score, 3),
            "evidence_alignment": round(self.evidence_alignment, 3),
            "statement_detail": round(self.statement_detail, 3),
        }


@dataclass
class WitnessReliabilityScore:
    """Complete reliability assessment for a witness."""
    witness_id: str
    witness_name: str
    overall_score: float  # 0-100 scale
    reliability_grade: str  # A, B, C, D, F
    factors: ReliabilityFactors
    contradiction_count: int
    confirmation_count: int
    correction_count: int
    total_statements: int
    evidence_matches: int
    evidence_conflicts: int
    calculated_at: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "witness_id": self.witness_id,
            "witness_name": self.witness_name,
            "overall_score": round(self.overall_score, 1),
            "reliability_grade": self.reliability_grade,
            "factors": self.factors.to_dict(),
            "stats": {
                "contradiction_count": self.contradiction_count,
                "confirmation_count": self.confirmation_count,
                "correction_count": self.correction_count,
                "total_statements": self.total_statements,
                "evidence_matches": self.evidence_matches,
                "evidence_conflicts": self.evidence_conflicts,
            },
            "calculated_at": self.calculated_at.isoformat(),
        }


class WitnessReliabilityService:
    """Calculates and tracks witness reliability scores."""
    
    # Weights for calculating overall score
    WEIGHTS = {
        "contradiction_rate": 0.25,
        "correction_frequency": 0.15,
        "consistency_score": 0.25,
        "evidence_alignment": 0.20,
        "statement_detail": 0.15,
    }
    
    # Grade thresholds
    GRADE_THRESHOLDS = [
        (90, "A"),
        (80, "B"),
        (70, "C"),
        (60, "D"),
        (0, "F"),
    ]
    
    def __init__(self):
        # Cache for witness reliability data
        self._reliability_cache: Dict[str, Dict[str, WitnessReliabilityScore]] = {}
    
    def calculate_reliability(
        self,
        session_id: str,
        witness_id: str,
        witness_name: str,
        statements: List[Any],
        contradictions: List[Dict[str, Any]],
        evidence_markers: List[Any] = None,
        scene_elements: List[Any] = None,
    ) -> WitnessReliabilityScore:
        """
        Calculate reliability score for a witness.
        
        Args:
            session_id: Session identifier
            witness_id: Witness identifier
            witness_name: Display name of witness
            statements: List of WitnessStatement objects
            contradictions: List of contradiction dicts from ContradictionDetector
            evidence_markers: List of physical evidence markers
            scene_elements: List of scene elements for cross-referencing
        
        Returns:
            WitnessReliabilityScore with all factors calculated
        """
        # Filter to this witness's statements
        witness_statements = [
            s for s in statements 
            if getattr(s, 'witness_id', None) == witness_id or not getattr(s, 'witness_id', None)
        ]
        
        # If no specific witness_id filtering, use all statements
        if not any(getattr(s, 'witness_id', None) for s in statements):
            witness_statements = statements
        
        total_statements = len(witness_statements)
        if total_statements == 0:
            # No statements - neutral score
            factors = ReliabilityFactors(
                contradiction_rate=0.0,
                correction_frequency=0.0,
                consistency_score=0.5,
                evidence_alignment=0.5,
                statement_detail=0.0,
            )
            return WitnessReliabilityScore(
                witness_id=witness_id,
                witness_name=witness_name,
                overall_score=50.0,
                reliability_grade="C",
                factors=factors,
                contradiction_count=0,
                confirmation_count=0,
                correction_count=0,
                total_statements=0,
                evidence_matches=0,
                evidence_conflicts=0,
                calculated_at=datetime.utcnow(),
            )
        
        # Count corrections
        correction_count = sum(1 for s in witness_statements if getattr(s, 'is_correction', False))
        
        # Count contradictions for this witness
        contradiction_count = len([
            c for c in contradictions 
            if not c.get('resolved', False)
        ])
        
        # Estimate confirmations (statements that don't contradict and aren't corrections)
        confirmation_count = max(0, total_statements - correction_count - contradiction_count)
        
        # Calculate factors
        factors = self._calculate_factors(
            witness_statements=witness_statements,
            contradictions=contradictions,
            evidence_markers=evidence_markers or [],
            scene_elements=scene_elements or [],
            correction_count=correction_count,
            contradiction_count=contradiction_count,
        )
        
        # Calculate overall score (0-100)
        overall_score = self._calculate_overall_score(factors)
        
        # Determine grade
        reliability_grade = self._get_grade(overall_score)
        
        # Count evidence alignment
        evidence_matches, evidence_conflicts = self._count_evidence_alignment(
            witness_statements, evidence_markers or [], scene_elements or []
        )
        
        score = WitnessReliabilityScore(
            witness_id=witness_id,
            witness_name=witness_name,
            overall_score=overall_score,
            reliability_grade=reliability_grade,
            factors=factors,
            contradiction_count=contradiction_count,
            confirmation_count=confirmation_count,
            correction_count=correction_count,
            total_statements=total_statements,
            evidence_matches=evidence_matches,
            evidence_conflicts=evidence_conflicts,
            calculated_at=datetime.utcnow(),
        )
        
        # Cache the result
        if session_id not in self._reliability_cache:
            self._reliability_cache[session_id] = {}
        self._reliability_cache[session_id][witness_id] = score
        
        logger.info(
            f"Calculated reliability for witness {witness_name}: "
            f"score={overall_score:.1f}, grade={reliability_grade}"
        )
        
        return score
    
    def _calculate_factors(
        self,
        witness_statements: List[Any],
        contradictions: List[Dict[str, Any]],
        evidence_markers: List[Any],
        scene_elements: List[Any],
        correction_count: int,
        contradiction_count: int,
    ) -> ReliabilityFactors:
        """Calculate individual reliability factors."""
        total_statements = len(witness_statements)
        
        # 1. Contradiction rate (0.0 = no contradictions, 1.0 = all contradictions)
        # Lower is better for witness reliability
        contradiction_rate = min(1.0, contradiction_count / max(1, total_statements))
        
        # 2. Correction frequency (0.0 = no corrections, 1.0 = all corrections)
        # Some corrections are natural, but many indicate uncertainty
        correction_frequency = min(1.0, correction_count / max(1, total_statements))
        
        # 3. Consistency score (based on similar descriptions across statements)
        consistency_score = self._calculate_consistency(witness_statements, contradictions)
        
        # 4. Evidence alignment (how well statements match physical evidence)
        evidence_alignment = self._calculate_evidence_alignment(
            witness_statements, evidence_markers, scene_elements
        )
        
        # 5. Statement detail (more detailed statements are generally more reliable)
        statement_detail = self._calculate_detail_score(witness_statements)
        
        return ReliabilityFactors(
            contradiction_rate=contradiction_rate,
            correction_frequency=correction_frequency,
            consistency_score=consistency_score,
            evidence_alignment=evidence_alignment,
            statement_detail=statement_detail,
        )
    
    def _calculate_consistency(
        self,
        statements: List[Any],
        contradictions: List[Dict[str, Any]]
    ) -> float:
        """Calculate consistency score based on statement patterns."""
        if len(statements) < 2:
            return 0.7  # Neutral for single statements
        
        # Start with perfect consistency
        consistency = 1.0
        
        # Deduct for each unresolved contradiction
        unresolved = sum(1 for c in contradictions if not c.get('resolved', False))
        consistency -= min(0.5, unresolved * 0.1)
        
        # Deduct for high severity contradictions
        high_severity = sum(
            1 for c in contradictions 
            if c.get('severity', {}).get('level') in ['high', 'critical']
        )
        consistency -= min(0.3, high_severity * 0.15)
        
        return max(0.0, consistency)
    
    def _calculate_evidence_alignment(
        self,
        statements: List[Any],
        evidence_markers: List[Any],
        scene_elements: List[Any],
    ) -> float:
        """Calculate how well statements align with physical evidence."""
        if not evidence_markers and not scene_elements:
            return 0.5  # Neutral when no evidence to compare
        
        # Extract keywords from evidence
        evidence_keywords = set()
        for marker in evidence_markers:
            label = getattr(marker, 'label', '') or ''
            desc = getattr(marker, 'description', '') or ''
            evidence_keywords.update(label.lower().split())
            evidence_keywords.update(desc.lower().split())
        
        for elem in scene_elements:
            desc = getattr(elem, 'description', '') or ''
            evidence_keywords.update(desc.lower().split())
        
        if not evidence_keywords:
            return 0.5
        
        # Remove common words
        stop_words = {'the', 'a', 'an', 'is', 'was', 'were', 'are', 'and', 'or', 'in', 'on', 'at', 'to', 'of'}
        evidence_keywords -= stop_words
        
        if not evidence_keywords:
            return 0.5
        
        # Count how many evidence keywords appear in statements
        matches = 0
        for stmt in statements:
            text = getattr(stmt, 'text', '') or ''
            text_words = set(text.lower().split())
            matches += len(evidence_keywords.intersection(text_words))
        
        # Normalize to 0-1 scale
        max_possible = len(evidence_keywords) * len(statements)
        if max_possible == 0:
            return 0.5
        
        alignment = min(1.0, matches / (max_possible * 0.3))  # 30% match = perfect
        return max(0.3, alignment)  # Floor at 0.3
    
    def _calculate_detail_score(self, statements: List[Any]) -> float:
        """Calculate detail level of statements."""
        if not statements:
            return 0.0
        
        total_length = 0
        keyword_count = 0
        
        # Detail keywords (specific descriptors)
        detail_keywords = [
            'color', 'red', 'blue', 'green', 'black', 'white', 'yellow',
            'left', 'right', 'north', 'south', 'east', 'west',
            'feet', 'meters', 'inches', 'about', 'approximately',
            'around', 'time', 'when', 'before', 'after', 'during',
            'tall', 'short', 'large', 'small', 'wearing', 'heard', 'saw',
        ]
        
        for stmt in statements:
            text = getattr(stmt, 'text', '') or ''
            total_length += len(text)
            text_lower = text.lower()
            keyword_count += sum(1 for kw in detail_keywords if kw in text_lower)
        
        # Score based on average length and keyword density
        avg_length = total_length / len(statements)
        avg_keywords = keyword_count / len(statements)
        
        # Normalize: 100+ chars average and 3+ keywords = good detail
        length_score = min(1.0, avg_length / 100)
        keyword_score = min(1.0, avg_keywords / 3)
        
        return (length_score * 0.4 + keyword_score * 0.6)
    
    def _calculate_overall_score(self, factors: ReliabilityFactors) -> float:
        """Calculate weighted overall score (0-100)."""
        # Convert factors to scores (higher = better)
        factor_scores = {
            "contradiction_rate": 1.0 - factors.contradiction_rate,  # Invert
            "correction_frequency": 1.0 - factors.correction_frequency,  # Invert
            "consistency_score": factors.consistency_score,
            "evidence_alignment": factors.evidence_alignment,
            "statement_detail": factors.statement_detail,
        }
        
        # Weighted average
        total = sum(factor_scores[k] * self.WEIGHTS[k] for k in self.WEIGHTS)
        
        # Scale to 0-100
        return total * 100
    
    def _get_grade(self, score: float) -> str:
        """Convert numeric score to letter grade."""
        for threshold, grade in self.GRADE_THRESHOLDS:
            if score >= threshold:
                return grade
        return "F"
    
    def _count_evidence_alignment(
        self,
        statements: List[Any],
        evidence_markers: List[Any],
        scene_elements: List[Any],
    ) -> tuple:
        """Count evidence matches and conflicts."""
        # Simple heuristic: count elements mentioned in statements
        matches = 0
        conflicts = 0
        
        # Extract evidence descriptions
        evidence_texts = []
        for marker in evidence_markers:
            evidence_texts.append(getattr(marker, 'description', '') or '')
        for elem in scene_elements:
            evidence_texts.append(getattr(elem, 'description', '') or '')
        
        # Check each statement for mentions
        for stmt in statements:
            text = (getattr(stmt, 'text', '') or '').lower()
            for ev_text in evidence_texts:
                if ev_text:
                    # Simple word overlap check
                    ev_words = set(ev_text.lower().split())
                    stmt_words = set(text.split())
                    overlap = ev_words.intersection(stmt_words)
                    if len(overlap) >= 2:
                        matches += 1
        
        return matches, conflicts
    
    def get_cached_score(
        self, session_id: str, witness_id: str
    ) -> Optional[WitnessReliabilityScore]:
        """Get cached reliability score if available."""
        return self._reliability_cache.get(session_id, {}).get(witness_id)
    
    def clear_cache(self, session_id: str = None):
        """Clear reliability cache."""
        if session_id:
            self._reliability_cache.pop(session_id, None)
        else:
            self._reliability_cache.clear()


# Global singleton
witness_reliability_service = WitnessReliabilityService()
