import logging
import json
import asyncio
from typing import Optional, List, Dict, Any
from datetime import datetime
from google import genai

from app.config import settings
from app.models.schemas import Case, ReconstructionSession
from app.services.firestore import firestore_service
from app.services.model_selector import model_selector

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
        """Use Gemini to find if this report matches any existing case."""
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

If this report matches an existing case, respond with ONLY the case_id.
If it does NOT match any case, respond with ONLY the word "NEW".
Do not explain your reasoning."""

            chat_model = await model_selector.get_best_model_for_chat()
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=chat_model,
                contents=prompt,
                config={"temperature": 0.1}
            )

            result = response.text.strip()

            for case in cases:
                if case.id in result:
                    logger.info(f"Report {report.id} matched to case {case.case_number}")
                    return case.id

            logger.info(f"Report {report.id} did not match any existing case")
            return None

        except Exception as e:
            logger.error(f"Error matching report to case: {e}")
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

        asyncio.create_task(self.generate_case_summary(case.id))

        return case.id

    async def generate_case_summary(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Generate a comprehensive case summary using Gemini."""
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

Respond with a JSON object:
{{
    "summary": "A comprehensive 2-3 paragraph summary of the incident based on all witness accounts",
    "title": "A clear, descriptive title for this case",
    "location": "The specific location if mentioned",
    "timeframe": {{
        "start": "Estimated start time/date of the incident",
        "end": "Estimated end time/date if applicable",
        "description": "A human-readable timeframe description"
    }},
    "key_elements": ["list", "of", "key", "elements"],
    "scene_description": "A detailed description for generating a scene image combining all witness perspectives"
}}"""

                try:
                    chat_model = await model_selector.get_best_model_for_chat()
                    response = await asyncio.to_thread(
                        self.client.models.generate_content,
                        model=chat_model,
                        contents=prompt,
                        config={"temperature": 0.3}
                    )

                    text = response.text
                    if "```json" in text:
                        text = text.split("```json")[1].split("```")[0]
                    elif "```" in text:
                        text = text.split("```")[1].split("```")[0]

                    result = json.loads(text.strip())

                    case.summary = result.get("summary", case.summary)
                    case.title = result.get("title", case.title)
                    case.location = result.get("location", case.location)
                    case.timeframe = result.get("timeframe", case.timeframe)
                    case.metadata["key_elements"] = result.get("key_elements", [])
                    case.metadata["scene_description"] = result.get("scene_description", "")
                    case.updated_at = datetime.utcnow()
                    await firestore_service.update_case(case)

                    logger.info(f"Generated summary for case {case.case_number}")
                    return result

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


# Global instance
case_manager = CaseManager()
