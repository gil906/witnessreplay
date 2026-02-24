import logging
import json
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from google import genai
from google.genai import types

from app.config import settings
from app.models.schemas import (
    Case,
    ReconstructionSession,
    IncidentClassificationResponse,
    CaseSummaryResponse,
    CaseMatchResponse,
)
from app.services.firestore import firestore_service
from app.services.model_selector import model_selector
from app.services.response_cache import response_cache

logger = logging.getLogger(__name__)


class CaseManager:
    """Manages case grouping using Gemini AI to match reports to cases."""

    def __init__(self):
        self.client = None
        self._initialize()

    def _initialize(self):
        try:
            if settings.google_api_key:
                self.client = genai.Client(api_key=settings.google_api_key)
                logger.info("CaseManager initialized with Gemini client")
        except Exception as e:
            logger.error(f"Failed to initialize CaseManager: {e}")

    async def assign_report_to_case(self, report: ReconstructionSession) -> str:
        """
        Analyze a report and assign it to an existing case or create a new one.
        Returns the case_id.
        """
        cases = await firestore_service.list_cases(limit=100)

        if not cases or not self.client:
            return await self._create_case_for_report(report)

        match_case_id = await self._find_matching_case(report, cases)

        if match_case_id:
            case = await firestore_service.get_case(match_case_id)
            if case:
                if report.id not in case.report_ids:
                    case.report_ids.append(report.id)
                    case.updated_at = datetime.utcnow()
                    await firestore_service.update_case(case)
                await self.generate_case_summary(match_case_id)
                return match_case_id

        return await self._create_case_for_report(report)

    async def _find_matching_case(self, report: ReconstructionSession, cases: List[Case]) -> Optional[str]:
        """Use embeddings for fast case matching, fall back to LLM if needed."""
        from app.services.embedding_service import embedding_service

        report_text = self._get_report_text(report)
        if not report_text:
            return None

        # Build candidate list from existing cases
        candidates = []
        for case in cases:
            case_text = f"{case.title}. {case.summary or ''}. Location: {case.location or ''}. Reports: {len(case.report_ids)}"
            candidates.append((case.id, case_text))

        if not candidates:
            return None

        # Try embedding-based matching first (100 RPM vs 5 RPM!)
        match_id = await embedding_service.find_most_similar(report_text, candidates, threshold=0.72)
        if match_id:
            logger.info(f"Report {report.id} matched via embedding similarity")
            return match_id

        # Fall back to LLM-based matching only if embeddings fail
        return await self._find_matching_case_llm(report, cases)

    async def _find_matching_case_llm(self, report: ReconstructionSession, cases: List[Case]) -> Optional[str]:
        """LLM-based case matching fallback when embeddings are unavailable.
        
        Uses structured JSON output for reliable parsing of match decisions.
        """
        try:
            report_text = self._get_report_text(report)
            if not report_text:
                return None

            cases_info = []
            for case in cases:
                cases_info.append({
                    "case_id": case.id,
                    "case_number": case.case_number,
                    "title": case.title,
                    "summary": case.summary,
                    "location": case.location,
                    "timeframe": case.timeframe,
                    "report_count": len(case.report_ids)
                })

            prompt = f"""You are a case management AI. Analyze this new witness report and determine if it belongs to any existing case.

A report should match a case if:
- It describes the same incident/event (same type of event like accident, crime etc)
- Similar time period (same day or close dates)
- Similar location or area
- Describes similar key elements (vehicles, people, actions)

NEW REPORT:
Title: {report.title}
Created: {report.created_at.isoformat() if report.created_at else 'unknown'}
Statements: {report_text}

EXISTING CASES:
{json.dumps(cases_info, indent=2, default=str)}

Determine if this report matches any existing case. If it matches, provide the case_id."""

            chat_model = await model_selector.get_best_model_for_chat()
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=chat_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                    response_json_schema=CaseMatchResponse,
                ),
            )

            # Parse structured response
            result = CaseMatchResponse.model_validate_json(response.text)

            if result.matches_existing_case and result.matched_case_id:
                # Verify the case_id exists
                for case in cases:
                    if case.id == result.matched_case_id:
                        logger.info(f"Report {report.id} matched to case {case.case_number} (LLM structured output, confidence: {result.confidence})")
                        return case.id

            logger.info(f"Report {report.id} did not match any existing case")
            return None

        except Exception as e:
            logger.error(f"Error matching report to case (LLM): {e}")
            return None

    async def _create_case_for_report(self, report: ReconstructionSession) -> str:
        """Create a new case for a report."""
        import uuid
        case_number = await firestore_service.get_next_case_number()

        title = report.title if report.title != "Untitled Session" else f"Case {case_number}"

        case = Case(
            id=str(uuid.uuid4()),
            case_number=case_number,
            title=title,
            report_ids=[report.id],
            location=report.metadata.get("location", ""),
            timeframe={
                "start": report.created_at.isoformat() if report.created_at else "",
                "description": "Pending analysis"
            },
            metadata={"auto_created": True}
        )

        await firestore_service.create_case(case)
        logger.info(f"Created new case {case.case_number} for report {report.id}")

        # Try to determine incident type
        incident_type = await self._classify_incident(report)
        if incident_type:
            case.metadata["incident_type"] = incident_type.get("type", "")
            case.metadata["incident_subtype"] = incident_type.get("subtype", "")
            case.metadata["severity"] = incident_type.get("severity", "")
            case.updated_at = datetime.utcnow()
            await firestore_service.update_case(case)

        asyncio.create_task(self.generate_case_summary(case.id))

        return case.id

    async def generate_case_summary(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Generate a comprehensive case summary using Gemini with structured output.
        
        Uses response_json_schema for guaranteed valid JSON matching CaseSummaryResponse,
        eliminating parsing errors and reducing token waste from formatting instructions.
        """
        try:
            case = await firestore_service.get_case(case_id)
            if not case:
                return None

            all_reports_text = []
            for report_id in case.report_ids:
                report = await firestore_service.get_session(report_id)
                if report:
                    report_text = self._get_report_text(report)
                    source = report.source_type if hasattr(report, 'source_type') else 'chat'
                    all_reports_text.append(f"Report {getattr(report, 'report_number', report.id)} (via {source}):\n{report_text}")

            if not all_reports_text and not self.client:
                return None

            if self.client and all_reports_text:
                prompt = f"""You are a law enforcement case analyst AI. Based on ALL witness reports below, create a comprehensive case summary.

CASE: {case.case_number} - {case.title}
LOCATION: {case.location}

WITNESS REPORTS:
{chr(10).join(all_reports_text)}

Create a comprehensive summary combining all witness perspectives, identify key elements, and provide a detailed scene description suitable for image generation."""

                try:
                    # Check response cache first for similar case summaries
                    cached = await response_cache.get(prompt, context_key="case_summary", threshold=0.93)
                    if cached:
                        response_text, _ = cached
                        logger.info(f"Using cached summary for case {case.case_number}")
                    else:
                        chat_model = await model_selector.get_best_model_for_chat()
                        response = await asyncio.to_thread(
                            self.client.models.generate_content,
                            model=chat_model,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                temperature=0.3,
                                response_mime_type="application/json",
                                response_json_schema=CaseSummaryResponse,
                            ),
                        )
                        response_text = response.text
                        # Cache the summary for similar requests
                        await response_cache.set(prompt, response_text, context_key="case_summary", ttl_seconds=3600)

                    # Parse structured response - guaranteed valid JSON
                    result = CaseSummaryResponse.model_validate_json(response_text)
                    result_dict = result.model_dump()

                    case.summary = result.summary
                    case.title = result.title
                    case.location = result.location
                    case.timeframe = result.timeframe.model_dump()
                    case.metadata["key_elements"] = result.key_elements
                    case.metadata["scene_description"] = result.scene_description
                    case.updated_at = datetime.utcnow()
                    await firestore_service.update_case(case)

                    logger.info(f"Generated summary for case {case.case_number} using structured output")
                    return result_dict

                except Exception as e:
                    logger.error(f"Error generating case summary: {e}")

            return None

        except Exception as e:
            logger.error(f"Error in generate_case_summary: {e}")
            return None

    def _get_report_text(self, report: ReconstructionSession) -> str:
        """Extract readable text from a report's statements."""
        if not report.witness_statements:
            return report.title or ""
        return "\n".join(stmt.text for stmt in report.witness_statements)

    async def embed_report(self, report: ReconstructionSession):
        """Pre-compute embedding for a report for future matching."""
        from app.services.embedding_service import embedding_service
        text = self._get_report_text(report)
        if text:
            await embedding_service.embed_text(text)  # Returns tuple, we ignore it here

    async def search_cases(self, query: str, limit: int = 10) -> list:
        """Search cases by semantic similarity."""
        from app.services.embedding_service import embedding_service
        cases = await firestore_service.list_cases(limit=100)
        documents = [(c.id, f"{c.title} {c.summary or ''}") for c in cases]
        results = await embedding_service.semantic_search(query, documents, top_k=limit)
        return results

    async def search_reports(self, query: str, limit: int = 10) -> list:
        """Search reports by semantic similarity."""
        from app.services.embedding_service import embedding_service
        sessions = await firestore_service.list_sessions(limit=100)
        documents = [(s.id, self._get_report_text(s) or s.title) for s in sessions]
        results = await embedding_service.semantic_search(query, documents, top_k=limit)
        return results

    async def _classify_incident(self, report: ReconstructionSession) -> Optional[Dict]:
        """Use Gemini with structured JSON output to classify the incident type.
        
        Uses response_json_schema for guaranteed valid JSON matching the schema,
        eliminating parsing errors and reducing token waste.
        Uses response cache for similar reports to reduce redundant API calls.
        """
        if not self.client:
            return None
        try:
            report_text = self._get_report_text(report)
            if not report_text:
                return None
            
            prompt = f"""Classify this witness report into an incident category.

Report: {report_text}

Determine the type (accident, crime, incident, or other), specific subtype, and severity level."""
            
            # Check response cache first for similar classification requests
            cached = await response_cache.get(prompt, context_key="classify_incident", threshold=0.94)
            if cached:
                response_text, _ = cached
                logger.info("Using cached incident classification")
            else:
                chat_model = await model_selector.get_best_model_for_chat()
                response = await asyncio.to_thread(
                    self.client.models.generate_content,
                    model=chat_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                        response_json_schema=IncidentClassificationResponse,
                    ),
                )
                response_text = response.text
                # Cache for similar future classifications
                await response_cache.set(prompt, response_text, context_key="classify_incident", ttl_seconds=7200)
            
            # Parse structured response - guaranteed valid JSON
            result = IncidentClassificationResponse.model_validate_json(response_text)
            return result.model_dump()
        except Exception as e:
            logger.warning(f"Failed to classify incident: {e}")
            return None


# Global instance
case_manager = CaseManager()
