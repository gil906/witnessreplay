"""
Pattern Detection Service for WitnessReplay.
Identifies crime patterns across cases using time, location, MO, and semantic analysis.
"""
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from collections import defaultdict

from app.models.schemas import Case, CaseSimilarityResult
from app.services.firestore import firestore_service
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


class TimePattern:
    """Represents a detected time-based pattern."""
    def __init__(
        self,
        pattern_type: str,  # "day_of_week", "time_of_day", "recurring"
        description: str,
        cases: List[Dict[str, Any]],
        confidence: float,
        details: Dict[str, Any] = None
    ):
        self.pattern_type = pattern_type
        self.description = description
        self.cases = cases
        self.confidence = confidence
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_type": self.pattern_type,
            "description": self.description,
            "case_count": len(self.cases),
            "cases": self.cases,
            "confidence": round(self.confidence, 3),
            "details": self.details
        }


class LocationPattern:
    """Represents a detected location-based pattern."""
    def __init__(
        self,
        area: str,
        cases: List[Dict[str, Any]],
        confidence: float,
        radius_description: str = "",
        hotspot_type: str = "cluster"
    ):
        self.area = area
        self.cases = cases
        self.confidence = confidence
        self.radius_description = radius_description
        self.hotspot_type = hotspot_type

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_type": "location",
            "area": self.area,
            "case_count": len(self.cases),
            "cases": self.cases,
            "confidence": round(self.confidence, 3),
            "radius_description": self.radius_description,
            "hotspot_type": self.hotspot_type
        }


class MOPattern:
    """Represents a modus operandi pattern."""
    def __init__(
        self,
        mo_type: str,
        description: str,
        cases: List[Dict[str, Any]],
        confidence: float,
        shared_elements: List[str] = None
    ):
        self.mo_type = mo_type
        self.description = description
        self.cases = cases
        self.confidence = confidence
        self.shared_elements = shared_elements or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_type": "mo",
            "mo_type": self.mo_type,
            "description": self.description,
            "case_count": len(self.cases),
            "cases": self.cases,
            "confidence": round(self.confidence, 3),
            "shared_elements": self.shared_elements
        }


class PatternAnalysisResult:
    """Complete pattern analysis result for a set of cases."""
    def __init__(
        self,
        time_patterns: List[TimePattern] = None,
        location_patterns: List[LocationPattern] = None,
        mo_patterns: List[MOPattern] = None,
        semantic_clusters: List[Dict[str, Any]] = None,
        summary: str = ""
    ):
        self.time_patterns = time_patterns or []
        self.location_patterns = location_patterns or []
        self.mo_patterns = mo_patterns or []
        self.semantic_clusters = semantic_clusters or []
        self.summary = summary

    def to_dict(self) -> Dict[str, Any]:
        return {
            "time_patterns": [p.to_dict() for p in self.time_patterns],
            "location_patterns": [p.to_dict() for p in self.location_patterns],
            "mo_patterns": [p.to_dict() for p in self.mo_patterns],
            "semantic_clusters": self.semantic_clusters,
            "summary": self.summary,
            "total_patterns": (
                len(self.time_patterns) +
                len(self.location_patterns) +
                len(self.mo_patterns) +
                len(self.semantic_clusters)
            )
        }


class PatternDetectionService:
    """Service for detecting patterns across cases."""

    # Time pattern thresholds
    DAY_OF_WEEK_THRESHOLD = 3  # Min cases on same day of week
    TIME_OF_DAY_THRESHOLD = 3  # Min cases in same time window
    TIME_WINDOW_HOURS = 3      # Window for time-of-day clustering
    RECURRING_THRESHOLD = 3    # Min cases for recurring pattern
    
    # Location pattern thresholds
    LOCATION_CLUSTER_THRESHOLD = 2  # Min cases in same location
    
    # MO pattern thresholds
    MO_MATCH_THRESHOLD = 0.6   # Min similarity for MO match
    
    # Semantic clustering
    SEMANTIC_CLUSTER_THRESHOLD = 0.75

    async def analyze_patterns(
        self,
        case_ids: Optional[List[str]] = None,
        days_back: int = 90,
        limit: int = 100
    ) -> PatternAnalysisResult:
        """
        Analyze patterns across all cases or a specific set of cases.
        
        Args:
            case_ids: Specific case IDs to analyze (if None, analyzes recent cases)
            days_back: How far back to look for cases
            limit: Maximum number of cases to analyze
        """
        # Fetch cases
        if case_ids:
            cases = []
            for cid in case_ids[:limit]:
                case = await firestore_service.get_case(cid)
                if case:
                    cases.append(case)
        else:
            cases = await firestore_service.list_cases(limit=limit)
        
        if len(cases) < 2:
            return PatternAnalysisResult(
                summary="Insufficient cases for pattern analysis (minimum 2 required)"
            )
        
        # Filter by date if needed
        if days_back and not case_ids:
            cutoff = datetime.utcnow() - timedelta(days=days_back)
            cases = [
                c for c in cases 
                if self._parse_datetime(c.created_at) >= cutoff
            ]
        
        # Run pattern detection
        time_patterns = self._detect_time_patterns(cases)
        location_patterns = self._detect_location_patterns(cases)
        mo_patterns = self._detect_mo_patterns(cases)
        semantic_clusters = await self._detect_semantic_clusters(cases)
        
        # Generate summary
        summary = self._generate_summary(
            cases, time_patterns, location_patterns, mo_patterns, semantic_clusters
        )
        
        return PatternAnalysisResult(
            time_patterns=time_patterns,
            location_patterns=location_patterns,
            mo_patterns=mo_patterns,
            semantic_clusters=semantic_clusters,
            summary=summary
        )

    def _detect_time_patterns(self, cases: List[Case]) -> List[TimePattern]:
        """Detect time-based patterns (day of week, time of day, recurring)."""
        patterns = []
        
        # Group by day of week
        day_groups = defaultdict(list)
        time_groups = defaultdict(list)
        
        for case in cases:
            dt = self._parse_datetime(case.created_at)
            if dt:
                day_name = dt.strftime("%A")
                day_groups[day_name].append(self._case_brief(case, dt))
                
                # Group by time window (3-hour blocks)
                hour_block = (dt.hour // self.TIME_WINDOW_HOURS) * self.TIME_WINDOW_HOURS
                time_key = f"{hour_block:02d}:00-{(hour_block + self.TIME_WINDOW_HOURS) % 24:02d}:00"
                time_groups[time_key].append(self._case_brief(case, dt))
        
        # Detect day-of-week patterns
        for day, day_cases in day_groups.items():
            if len(day_cases) >= self.DAY_OF_WEEK_THRESHOLD:
                confidence = min(1.0, len(day_cases) / (len(cases) / 7 * 2))
                patterns.append(TimePattern(
                    pattern_type="day_of_week",
                    description=f"{len(day_cases)} incidents on {day}s",
                    cases=day_cases,
                    confidence=confidence,
                    details={"day": day, "count": len(day_cases)}
                ))
        
        # Detect time-of-day patterns
        for time_window, time_cases in time_groups.items():
            if len(time_cases) >= self.TIME_OF_DAY_THRESHOLD:
                confidence = min(1.0, len(time_cases) / (len(cases) / 8 * 2))
                patterns.append(TimePattern(
                    pattern_type="time_of_day",
                    description=f"{len(time_cases)} incidents between {time_window}",
                    cases=time_cases,
                    confidence=confidence,
                    details={"time_window": time_window, "count": len(time_cases)}
                ))
        
        # Detect recurring patterns (same day and time)
        day_time_groups = defaultdict(list)
        for case in cases:
            dt = self._parse_datetime(case.created_at)
            if dt:
                day_name = dt.strftime("%A")
                hour_block = (dt.hour // self.TIME_WINDOW_HOURS) * self.TIME_WINDOW_HOURS
                key = f"{day_name}_{hour_block}"
                day_time_groups[key].append(self._case_brief(case, dt))
        
        for key, recurring_cases in day_time_groups.items():
            if len(recurring_cases) >= self.RECURRING_THRESHOLD:
                day, hour = key.split("_")
                hour_end = (int(hour) + self.TIME_WINDOW_HOURS) % 24
                confidence = min(1.0, len(recurring_cases) / 3)
                patterns.append(TimePattern(
                    pattern_type="recurring",
                    description=f"Recurring: {len(recurring_cases)} incidents on {day}s {hour}:00-{hour_end}:00",
                    cases=recurring_cases,
                    confidence=confidence,
                    details={"day": day, "hour_start": int(hour), "hour_end": hour_end}
                ))
        
        # Sort by confidence
        patterns.sort(key=lambda p: p.confidence, reverse=True)
        return patterns

    def _detect_location_patterns(self, cases: List[Case]) -> List[LocationPattern]:
        """Detect location-based patterns (clustering by area)."""
        patterns = []
        location_groups = defaultdict(list)
        
        for case in cases:
            if not case.location:
                continue
            
            # Normalize location for grouping
            normalized = self._normalize_location(case.location)
            if normalized:
                location_groups[normalized].append(self._case_brief(case))
        
        # Find location clusters
        for area, area_cases in location_groups.items():
            if len(area_cases) >= self.LOCATION_CLUSTER_THRESHOLD:
                confidence = min(1.0, len(area_cases) / 5)
                patterns.append(LocationPattern(
                    area=area,
                    cases=area_cases,
                    confidence=confidence,
                    radius_description=f"{len(area_cases)} incidents in this area",
                    hotspot_type="cluster"
                ))
        
        # Sort by case count
        patterns.sort(key=lambda p: len(p.cases), reverse=True)
        return patterns

    def _detect_mo_patterns(self, cases: List[Case]) -> List[MOPattern]:
        """Detect modus operandi patterns based on incident type and metadata."""
        patterns = []
        
        # Group by incident type
        type_groups = defaultdict(list)
        subtype_groups = defaultdict(list)
        
        for case in cases:
            inc_type = case.metadata.get("incident_type", "")
            inc_subtype = case.metadata.get("incident_subtype", "")
            
            if inc_type:
                type_groups[inc_type].append(self._case_brief(case))
            if inc_subtype:
                subtype_groups[inc_subtype].append(self._case_brief(case))
        
        # Create MO patterns for types with multiple cases
        for mo_type, mo_cases in type_groups.items():
            if len(mo_cases) >= 2:
                confidence = min(1.0, len(mo_cases) / len(cases))
                patterns.append(MOPattern(
                    mo_type=mo_type,
                    description=f"{len(mo_cases)} {mo_type} incidents",
                    cases=mo_cases,
                    confidence=confidence,
                    shared_elements=[mo_type]
                ))
        
        # Create more specific patterns for subtypes
        for subtype, subtype_cases in subtype_groups.items():
            if len(subtype_cases) >= 2:
                confidence = min(1.0, len(subtype_cases) / len(cases) * 1.5)
                patterns.append(MOPattern(
                    mo_type=subtype,
                    description=f"{len(subtype_cases)} {subtype.replace('_', ' ')} incidents",
                    cases=subtype_cases,
                    confidence=confidence,
                    shared_elements=[subtype]
                ))
        
        # Sort by confidence
        patterns.sort(key=lambda p: p.confidence, reverse=True)
        return patterns

    async def _detect_semantic_clusters(self, cases: List[Case]) -> List[Dict[str, Any]]:
        """Detect semantic clusters using embedding similarity."""
        if len(cases) < 2:
            return []
        
        clusters = []
        
        # Build case texts and get embeddings
        case_texts = []
        for case in cases:
            text = f"{case.title}. {case.summary or ''}. Location: {case.location or ''}"
            case_texts.append((case.id, case.case_number, case.title, text))
        
        # Get embeddings for all cases
        embeddings = {}
        for case_id, case_number, title, text in case_texts:
            emb, _ = await embedding_service.embed_text(text)
            if emb:
                embeddings[case_id] = {
                    "embedding": emb,
                    "case_number": case_number,
                    "title": title
                }
        
        if len(embeddings) < 2:
            return []
        
        # Find clusters using simple pairwise similarity
        # Cases that are mutually similar form a cluster
        used_cases = set()
        case_ids = list(embeddings.keys())
        
        for i, case_id in enumerate(case_ids):
            if case_id in used_cases:
                continue
            
            cluster_members = [{
                "case_id": case_id,
                "case_number": embeddings[case_id]["case_number"],
                "title": embeddings[case_id]["title"]
            }]
            
            for j in range(i + 1, len(case_ids)):
                other_id = case_ids[j]
                if other_id in used_cases:
                    continue
                
                similarity = embedding_service.cosine_similarity(
                    embeddings[case_id]["embedding"],
                    embeddings[other_id]["embedding"]
                )
                
                if similarity >= self.SEMANTIC_CLUSTER_THRESHOLD:
                    cluster_members.append({
                        "case_id": other_id,
                        "case_number": embeddings[other_id]["case_number"],
                        "title": embeddings[other_id]["title"],
                        "similarity": round(similarity, 3)
                    })
            
            if len(cluster_members) >= 2:
                for m in cluster_members:
                    used_cases.add(m["case_id"])
                
                clusters.append({
                    "pattern_type": "semantic",
                    "description": f"Semantically similar cluster ({len(cluster_members)} cases)",
                    "case_count": len(cluster_members),
                    "cases": cluster_members,
                    "confidence": min(1.0, len(cluster_members) / 3)
                })
        
        return clusters

    def _normalize_location(self, location: str) -> Optional[str]:
        """Normalize location string for grouping."""
        if not location:
            return None
        
        loc = location.lower().strip()
        
        # Remove common prefixes/suffixes
        for pattern in ["the ", "near ", "at ", "on "]:
            if loc.startswith(pattern):
                loc = loc[len(pattern):]
        
        # Extract key location words
        words = loc.split()
        key_words = []
        
        for word in words:
            # Skip common words
            if word in {"the", "a", "an", "of", "in", "on", "at", "to", "and", "or"}:
                continue
            # Keep street types and key location words
            if len(word) > 2:
                key_words.append(word)
        
        if not key_words:
            return None
        
        # Return normalized location (first 3 key words)
        return " ".join(key_words[:3])

    def _case_brief(self, case: Case, dt: datetime = None) -> Dict[str, Any]:
        """Create a brief case summary for pattern results."""
        brief = {
            "case_id": case.id,
            "case_number": case.case_number,
            "title": case.title,
            "location": case.location or "",
        }
        if dt:
            brief["datetime"] = dt.isoformat()
            brief["day_of_week"] = dt.strftime("%A")
            brief["time"] = dt.strftime("%H:%M")
        return brief

    def _parse_datetime(self, dt_value) -> Optional[datetime]:
        """Parse datetime from various formats."""
        if isinstance(dt_value, datetime):
            return dt_value
        if isinstance(dt_value, str):
            try:
                return datetime.fromisoformat(dt_value.replace("Z", "+00:00"))
            except:
                pass
        return None

    def _generate_summary(
        self,
        cases: List[Case],
        time_patterns: List[TimePattern],
        location_patterns: List[LocationPattern],
        mo_patterns: List[MOPattern],
        semantic_clusters: List[Dict[str, Any]]
    ) -> str:
        """Generate a human-readable summary of detected patterns."""
        parts = [f"Analysis of {len(cases)} cases:"]
        
        if time_patterns:
            top_time = time_patterns[0]
            parts.append(f"• Time: {top_time.description}")
        
        if location_patterns:
            top_loc = location_patterns[0]
            parts.append(f"• Location: {len(top_loc.cases)} incidents in '{top_loc.area}'")
        
        if mo_patterns:
            top_mo = mo_patterns[0]
            parts.append(f"• MO: {top_mo.description}")
        
        if semantic_clusters:
            parts.append(f"• Semantic: {len(semantic_clusters)} clusters of similar cases")
        
        if len(parts) == 1:
            parts.append("No significant patterns detected.")
        
        return " ".join(parts)

    async def find_related_patterns(self, case_id: str) -> Dict[str, Any]:
        """Find patterns related to a specific case."""
        case = await firestore_service.get_case(case_id)
        if not case:
            return {"error": "Case not found"}
        
        # Get all cases
        all_cases = await firestore_service.list_cases(limit=100)
        
        related_patterns = {
            "case_id": case_id,
            "case_number": case.case_number,
            "time_matches": [],
            "location_matches": [],
            "mo_matches": [],
            "semantic_matches": []
        }
        
        case_dt = self._parse_datetime(case.created_at)
        
        for other in all_cases:
            if other.id == case_id:
                continue
            
            other_dt = self._parse_datetime(other.created_at)
            
            # Time match - same day of week and similar time
            if case_dt and other_dt:
                if case_dt.strftime("%A") == other_dt.strftime("%A"):
                    hour_diff = abs(case_dt.hour - other_dt.hour)
                    if hour_diff <= self.TIME_WINDOW_HOURS:
                        related_patterns["time_matches"].append({
                            "case_id": other.id,
                            "case_number": other.case_number,
                            "title": other.title,
                            "match_reason": f"Same day ({case_dt.strftime('%A')}) and similar time"
                        })
            
            # Location match
            if case.location and other.location:
                case_loc = self._normalize_location(case.location)
                other_loc = self._normalize_location(other.location)
                if case_loc and other_loc and case_loc == other_loc:
                    related_patterns["location_matches"].append({
                        "case_id": other.id,
                        "case_number": other.case_number,
                        "title": other.title,
                        "location": other.location
                    })
            
            # MO match
            case_type = case.metadata.get("incident_type", "")
            other_type = other.metadata.get("incident_type", "")
            if case_type and case_type == other_type:
                related_patterns["mo_matches"].append({
                    "case_id": other.id,
                    "case_number": other.case_number,
                    "title": other.title,
                    "incident_type": case_type
                })
        
        # Semantic matches using embeddings
        case_text = f"{case.title}. {case.summary or ''}. Location: {case.location or ''}"
        case_emb, _ = await embedding_service.embed_text(case_text)
        
        if case_emb:
            for other in all_cases:
                if other.id == case_id:
                    continue
                
                other_text = f"{other.title}. {other.summary or ''}. Location: {other.location or ''}"
                other_emb, _ = await embedding_service.embed_text(other_text)
                
                if other_emb:
                    similarity = embedding_service.cosine_similarity(case_emb, other_emb)
                    if similarity >= self.SEMANTIC_CLUSTER_THRESHOLD:
                        related_patterns["semantic_matches"].append({
                            "case_id": other.id,
                            "case_number": other.case_number,
                            "title": other.title,
                            "similarity": round(similarity, 3)
                        })
        
        # Sort semantic matches by similarity
        related_patterns["semantic_matches"].sort(
            key=lambda x: x.get("similarity", 0),
            reverse=True
        )
        
        return related_patterns


# Global instance
pattern_detection_service = PatternDetectionService()
