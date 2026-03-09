"""
Case Linking Service for WitnessReplay.
Handles case relationships, similarity detection, and auto-suggestions.
"""
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple

from app.models.schemas import (
    Case,
    CaseRelationship,
    CaseRelationshipCreate,
    CaseRelationshipResponse,
    CaseSimilarityResult,
)
from app.services.firestore import firestore_service
from app.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


class CaseLinkingService:
    """Service for managing case relationships and finding similar cases."""

    # Thresholds for similarity detection
    SEMANTIC_THRESHOLD = 0.70
    TIME_PROXIMITY_HOURS = 48
    LOCATION_KEYWORDS = ["street", "avenue", "road", "park", "intersection", "highway", "block"]

    async def create_relationship(
        self,
        case_a_id: str,
        case_b_id: str,
        relationship_type: str = "related",
        link_reason: str = "manual",
        notes: Optional[str] = None,
        confidence: float = 0.5,
        created_by: str = "manual",
    ) -> Optional[CaseRelationship]:
        """Create a relationship between two cases."""
        if case_a_id == case_b_id:
            logger.warning("Cannot link a case to itself")
            return None

        # Check if relationship already exists
        existing = await firestore_service.check_relationship_exists(case_a_id, case_b_id)
        if existing:
            logger.info(f"Relationship already exists between {case_a_id} and {case_b_id}")
            return CaseRelationship(**existing)

        # Verify both cases exist
        case_a = await firestore_service.get_case(case_a_id)
        case_b = await firestore_service.get_case(case_b_id)
        if not case_a or not case_b:
            logger.warning("One or both cases not found")
            return None

        rel = CaseRelationship(
            id=str(uuid.uuid4()),
            case_a_id=case_a_id,
            case_b_id=case_b_id,
            relationship_type=relationship_type,
            link_reason=link_reason,
            confidence=confidence,
            notes=notes,
            created_by=created_by,
            created_at=datetime.utcnow(),
        )

        success = await firestore_service.save_case_relationship(rel.model_dump(mode="json"))
        if success:
            logger.info(f"Created relationship {rel.id} between {case_a_id} and {case_b_id}")
            return rel
        return None

    async def delete_relationship(self, rel_id: str) -> bool:
        """Delete a case relationship."""
        return await firestore_service.delete_case_relationship(rel_id)

    async def get_related_cases(self, case_id: str) -> List[CaseRelationshipResponse]:
        """Get all cases related to the given case with full details."""
        relationships = await firestore_service.get_case_relationships(case_id)
        result = []

        for rel in relationships:
            # Determine which case is the "other" case
            other_case_id = rel["case_b_id"] if rel["case_a_id"] == case_id else rel["case_a_id"]
            other_case = await firestore_service.get_case(other_case_id)

            if other_case:
                result.append(CaseRelationshipResponse(
                    id=rel["id"],
                    related_case_id=other_case.id,
                    related_case_number=other_case.case_number,
                    related_case_title=other_case.title,
                    relationship_type=rel["relationship_type"],
                    link_reason=rel["link_reason"],
                    confidence=rel.get("confidence", 0.5),
                    notes=rel.get("notes"),
                    created_by=rel.get("created_by", "system"),
                    created_at=datetime.fromisoformat(rel["created_at"]) if isinstance(rel["created_at"], str) else rel["created_at"],
                ))

        return result

    async def find_similar_cases(
        self,
        case_id: str,
        limit: int = 5,
        exclude_linked: bool = True,
    ) -> List[CaseSimilarityResult]:
        """Find cases similar to the given case using multiple factors."""
        case = await firestore_service.get_case(case_id)
        if not case:
            return []

        all_cases = await firestore_service.list_cases(limit=100)
        
        # Get already linked case IDs to exclude
        excluded_ids = {case_id}
        if exclude_linked:
            linked = await firestore_service.get_case_relationships(case_id)
            for rel in linked:
                excluded_ids.add(rel["case_a_id"])
                excluded_ids.add(rel["case_b_id"])

        candidates = [c for c in all_cases if c.id not in excluded_ids]
        if not candidates:
            return []

        results = []
        case_text = f"{case.title}. {case.summary or ''}. Location: {case.location or ''}"

        for candidate in candidates:
            matching_factors = []
            scores = []

            # 1. Semantic similarity via embeddings
            candidate_text = f"{candidate.title}. {candidate.summary or ''}. Location: {candidate.location or ''}"
            semantic_score = await self._compute_semantic_similarity(case_text, candidate_text)
            if semantic_score >= self.SEMANTIC_THRESHOLD:
                matching_factors.append("semantic")
                scores.append(semantic_score)

            # 2. Location similarity
            location_score = self._compute_location_similarity(case.location, candidate.location)
            if location_score > 0.3:
                matching_factors.append("location")
                scores.append(location_score)

            # 3. Time proximity
            time_score = self._compute_time_proximity(case.created_at, candidate.created_at)
            if time_score > 0.3:
                matching_factors.append("time_proximity")
                scores.append(time_score)

            # 4. MO/Incident type matching
            mo_score = self._compute_mo_similarity(case.metadata, candidate.metadata)
            if mo_score > 0.5:
                matching_factors.append("mo")
                scores.append(mo_score)

            # Compute overall similarity
            if matching_factors:
                overall_score = sum(scores) / len(scores)
                results.append(CaseSimilarityResult(
                    case_id=candidate.id,
                    case_number=candidate.case_number,
                    title=candidate.title,
                    similarity_score=round(overall_score, 3),
                    matching_factors=matching_factors,
                ))

        # Sort by similarity score descending
        results.sort(key=lambda x: x.similarity_score, reverse=True)
        return results[:limit]

    async def auto_link_similar_cases(
        self,
        case_id: str,
        threshold: float = 0.75,
    ) -> List[CaseRelationship]:
        """Automatically link cases that exceed the similarity threshold."""
        similar_cases = await self.find_similar_cases(case_id, limit=10, exclude_linked=True)
        created_links = []

        for result in similar_cases:
            if result.similarity_score >= threshold:
                # Determine relationship type based on score
                if result.similarity_score >= 0.9:
                    rel_type = "same_incident"
                elif "mo" in result.matching_factors and result.similarity_score >= 0.8:
                    rel_type = "serial"
                else:
                    rel_type = "related"

                # Determine primary link reason
                if "semantic" in result.matching_factors:
                    link_reason = "semantic"
                elif "location" in result.matching_factors:
                    link_reason = "location"
                elif "mo" in result.matching_factors:
                    link_reason = "mo"
                elif "time_proximity" in result.matching_factors:
                    link_reason = "time_proximity"
                else:
                    link_reason = "semantic"

                rel = await self.create_relationship(
                    case_a_id=case_id,
                    case_b_id=result.case_id,
                    relationship_type=rel_type,
                    link_reason=link_reason,
                    confidence=result.similarity_score,
                    notes=f"Auto-linked based on: {', '.join(result.matching_factors)}",
                    created_by="system",
                )
                if rel:
                    created_links.append(rel)

        return created_links

    async def _compute_semantic_similarity(self, text_a: str, text_b: str) -> float:
        """Compute semantic similarity using embeddings."""
        try:
            emb_a, _ = await embedding_service.embed_text(text_a)
            emb_b, _ = await embedding_service.embed_text(text_b)
            if emb_a and emb_b:
                return embedding_service.cosine_similarity(emb_a, emb_b)
        except Exception as e:
            logger.warning(f"Semantic similarity computation failed: {e}")
        return 0.0

    def _compute_location_similarity(self, loc_a: Optional[str], loc_b: Optional[str]) -> float:
        """Compute location similarity based on text overlap."""
        if not loc_a or not loc_b:
            return 0.0

        loc_a_lower = loc_a.lower()
        loc_b_lower = loc_b.lower()

        # Exact match
        if loc_a_lower == loc_b_lower:
            return 1.0

        # Substring match
        if loc_a_lower in loc_b_lower or loc_b_lower in loc_a_lower:
            return 0.8

        # Word overlap
        words_a = set(loc_a_lower.split())
        words_b = set(loc_b_lower.split())
        # Remove common words
        stopwords = {"the", "a", "an", "and", "or", "of", "in", "on", "at", "to"}
        words_a -= stopwords
        words_b -= stopwords

        if not words_a or not words_b:
            return 0.0

        overlap = len(words_a & words_b)
        total = len(words_a | words_b)
        return overlap / total if total > 0 else 0.0

    def _compute_time_proximity(self, time_a: datetime, time_b: datetime) -> float:
        """Compute time proximity score (1.0 = same time, 0.0 = > 48 hours apart)."""
        if not time_a or not time_b:
            return 0.0

        # Handle string timestamps
        if isinstance(time_a, str):
            time_a = datetime.fromisoformat(time_a.replace("Z", "+00:00"))
        if isinstance(time_b, str):
            time_b = datetime.fromisoformat(time_b.replace("Z", "+00:00"))

        delta = abs((time_a - time_b).total_seconds())
        max_delta = self.TIME_PROXIMITY_HOURS * 3600

        if delta >= max_delta:
            return 0.0

        return 1.0 - (delta / max_delta)

    def _compute_mo_similarity(self, meta_a: Dict, meta_b: Dict) -> float:
        """Compute MO (modus operandi) similarity based on incident type metadata."""
        if not meta_a or not meta_b:
            return 0.0

        score = 0.0
        factors = 0

        # Compare incident type
        type_a = meta_a.get("incident_type", "")
        type_b = meta_b.get("incident_type", "")
        if type_a and type_b:
            factors += 1
            if type_a == type_b:
                score += 1.0

        # Compare incident subtype
        subtype_a = meta_a.get("incident_subtype", "")
        subtype_b = meta_b.get("incident_subtype", "")
        if subtype_a and subtype_b:
            factors += 1
            if subtype_a == subtype_b:
                score += 1.0

        # Compare severity
        sev_a = meta_a.get("severity", "")
        sev_b = meta_b.get("severity", "")
        if sev_a and sev_b:
            factors += 1
            if sev_a == sev_b:
                score += 0.5

        return score / factors if factors > 0 else 0.0


# Global instance
case_linking_service = CaseLinkingService()
