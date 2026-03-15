import logging
import json
import asyncio
import re
from typing import Optional, List, Dict, Any
from datetime import datetime
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
from app.services.multi_model_verifier import multi_model_verifier, VerificationResult
from app.services.api_key_manager import get_genai_client

logger = logging.getLogger(__name__)


class CaseManager:
    """Manages case grouping using Gemini AI to match reports to cases."""

    _LOCATION_STOPWORDS = {
        "the", "at", "on", "in", "near", "by", "of", "and", "block", "corner",
        "intersection", "from", "to", "north", "south", "east", "west",
    }
    _TEXT_STOPWORDS = _LOCATION_STOPWORDS | {
        "with", "that", "this", "there", "their", "they", "them", "then",
        "when", "where", "after", "before", "said", "says", "report", "witness",
        "incident", "statement", "saw", "seen", "was", "were", "have", "about",
        "just", "into", "onto", "over", "under", "around", "because", "while",
    }
    _LOCATION_TOKEN_MAP = {
        "st": "street",
        "rd": "road",
        "ave": "avenue",
        "blvd": "boulevard",
        "hwy": "highway",
        "ln": "lane",
        "dr": "drive",
        "ctr": "center",
        "ct": "court",
        "pkwy": "parkway",
    }

    def __init__(self):
        self.client = None
        self._assignment_lock = asyncio.Lock()
        self._initialize()

    def _initialize(self):
        try:
            if settings.google_api_key:
                self.client = get_genai_client()
                logger.info("CaseManager initialized with Gemini client")
        except Exception as e:
            logger.error(f"Failed to initialize CaseManager: {e}")

    def _build_report_matching_text(self, report: ReconstructionSession) -> str:
        """Build richer text for matching and classification without using report numbers."""
        metadata = dict(getattr(report, "metadata", {}) or {})
        report_text = self._get_report_text(report)
        location = self._extract_report_location(report)

        parts = []
        if report.title and report.title != "Untitled Session":
            parts.append(f"Title: {report.title}")
        if location:
            parts.append(f"Location: {location}")
        if metadata.get("incident_type"):
            parts.append(f"Incident Type: {metadata['incident_type']}")
        if metadata.get("incident_subtype"):
            parts.append(f"Incident Subtype: {metadata['incident_subtype']}")
        if metadata.get("severity"):
            parts.append(f"Severity: {metadata['severity']}")
        if metadata.get("ai_summary"):
            parts.append(f"Summary: {metadata['ai_summary']}")
        if report_text:
            parts.append(f"Statements:\n{report_text}")

        return "\n".join(part for part in parts if part).strip() or report_text or report.title or ""

    async def _build_incident_profile(self, report: ReconstructionSession) -> Dict[str, Any]:
        """Extract stable matching signals from a report."""
        metadata = dict(getattr(report, "metadata", {}) or {})
        matching_text = self._build_report_matching_text(report)

        inferred = self._infer_incident_from_text(matching_text)
        classification = None
        if self.client and matching_text and (
            inferred.get("type") in {"", "other"} or not inferred.get("subtype")
        ):
            classification = await self._classify_incident(report)

        incident_type = (
            metadata.get("incident_type")
            or (classification or {}).get("type")
            or inferred.get("type")
            or "other"
        )
        incident_subtype = (
            metadata.get("incident_subtype")
            or (classification or {}).get("subtype")
            or inferred.get("subtype")
            or ""
        )
        severity = (
            metadata.get("severity")
            or (classification or {}).get("severity")
            or inferred.get("severity")
            or ""
        )

        location = self._extract_report_location(report)
        occurred_at = self._extract_incident_datetime(metadata, getattr(report, "created_at", None))
        day_key = occurred_at.date().isoformat() if occurred_at else ""

        text_tokens = self._tokenize_text(matching_text)
        return {
            "incident_type": incident_type,
            "incident_subtype": incident_subtype,
            "severity": severity,
            "location": location,
            "location_key": self._normalize_location(location),
            "occurred_at": occurred_at,
            "day_key": day_key,
            "matching_text": matching_text,
            "text_tokens": text_tokens,
            "text_signature": " ".join(text_tokens[:6]),
        }

    def _build_case_profile(self, case: Case) -> Dict[str, Any]:
        """Extract stable matching signals from an existing case."""
        metadata = dict(case.metadata or {})
        grouping = metadata.get("grouping", {}) if isinstance(metadata.get("grouping"), dict) else {}

        location = case.location or grouping.get("location") or metadata.get("location") or ""
        incident_type = metadata.get("incident_type") or grouping.get("incident_type") or ""
        incident_subtype = metadata.get("incident_subtype") or grouping.get("incident_subtype") or ""
        severity = metadata.get("severity") or grouping.get("severity") or ""
        timeframe = case.timeframe if isinstance(case.timeframe, dict) else {}
        matching_text = "\n".join(
            part for part in [
                case.title,
                case.summary,
                metadata.get("scene_description"),
                location,
                incident_type,
                incident_subtype,
                severity,
                timeframe.get("description", ""),
            ] if part
        ).strip()
        inferred = self._infer_incident_from_text(matching_text)

        occurred_at = self._extract_incident_datetime(
            case.timeframe if isinstance(case.timeframe, dict) else {},
            getattr(case, "created_at", None),
        )
        day_key = grouping.get("reported_day") or (occurred_at.date().isoformat() if occurred_at else "")

        return {
            "incident_type": incident_type or inferred.get("type") or "",
            "incident_subtype": incident_subtype or inferred.get("subtype") or "",
            "severity": severity or inferred.get("severity") or "",
            "location": location,
            "location_key": grouping.get("location_key") or self._normalize_location(location),
            "occurred_at": occurred_at,
            "day_key": day_key,
            "matching_text": matching_text,
            "text_tokens": self._tokenize_text(matching_text),
        }

    def _extract_report_location(self, report: ReconstructionSession) -> str:
        metadata = dict(getattr(report, "metadata", {}) or {})
        active_witness_id = getattr(report, "active_witness_id", None)
        witnesses = getattr(report, "witnesses", []) or []
        active_witness = next((w for w in witnesses if getattr(w, "id", None) == active_witness_id), None)
        witness_locations = [
            getattr(witness, "location", "").strip()
            for witness in witnesses
            if getattr(witness, "location", None)
        ]
        return (
            metadata.get("location")
            or metadata.get("incident_location")
            or metadata.get("scene_location")
            or metadata.get("address")
            or metadata.get("intersection")
            or getattr(report, "witness_location", None)
            or getattr(active_witness, "location", None)
            or (witness_locations[0] if witness_locations else "")
            or ""
        ).strip()

    def _normalize_location(self, location: str) -> str:
        if not location:
            return ""

        tokens = []
        for token in re.findall(r"[a-z0-9]+", location.lower()):
            normalized = self._LOCATION_TOKEN_MAP.get(token, token)
            if normalized in self._LOCATION_STOPWORDS:
                continue
            tokens.append(normalized)
        return " ".join(tokens[:8])

    def _tokenize_text(self, text: str) -> List[str]:
        if not text:
            return []

        tokens = []
        seen = set()
        for raw_token in re.findall(r"[a-z0-9]+", text.lower()):
            token = self._LOCATION_TOKEN_MAP.get(raw_token, raw_token)
            if token in self._TEXT_STOPWORDS:
                continue
            if len(token) < 3 and not token.isdigit():
                continue
            if token not in seen:
                seen.add(token)
                tokens.append(token)
        return tokens[:18]

    def _locations_match(self, left: str, right: str) -> bool:
        if not left or not right:
            return False
        if left == right:
            return True
        if left in right or right in left:
            return True

        left_tokens = set(left.split())
        right_tokens = set(right.split())
        overlap = left_tokens & right_tokens
        if len(overlap) >= max(2, min(len(left_tokens), len(right_tokens)) - 1):
            return True

        union = left_tokens | right_tokens
        return bool(union) and (len(overlap) / len(union)) >= 0.6

    @staticmethod
    def _token_similarity(left_tokens: List[str], right_tokens: List[str]) -> float:
        left = set(left_tokens or [])
        right = set(right_tokens or [])
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    @staticmethod
    def _incident_types_compatible(report_profile: Dict[str, Any], case_profile: Dict[str, Any]) -> bool:
        report_type = (report_profile.get("incident_type") or "").strip().lower()
        case_type = (case_profile.get("incident_type") or "").strip().lower()
        if not report_type or not case_type:
            return True
        return report_type == case_type

    @staticmethod
    def _incident_subtypes_compatible(report_profile: Dict[str, Any], case_profile: Dict[str, Any]) -> bool:
        report_subtype = (report_profile.get("incident_subtype") or "").strip().lower()
        case_subtype = (case_profile.get("incident_subtype") or "").strip().lower()
        if not report_subtype or not case_subtype:
            return True
        return report_subtype == case_subtype

    def _score_case_candidate(self, report_profile: Dict[str, Any], case: Case) -> Optional[Dict[str, Any]]:
        case_profile = self._build_case_profile(case)

        if not self._incident_types_compatible(report_profile, case_profile):
            return None
        if not self._incident_subtypes_compatible(report_profile, case_profile):
            return None

        location_match = self._locations_match(
            report_profile.get("location_key", ""),
            case_profile.get("location_key", ""),
        )
        if report_profile.get("location_key") and case_profile.get("location_key") and not location_match:
            return None

        text_similarity = self._token_similarity(
            report_profile.get("text_tokens", []),
            case_profile.get("text_tokens", []),
        )
        day_match = (
            bool(report_profile.get("day_key"))
            and bool(case_profile.get("day_key"))
            and report_profile["day_key"] == case_profile["day_key"]
        )
        subtype_match = (
            bool(report_profile.get("incident_subtype"))
            and bool(case_profile.get("incident_subtype"))
            and report_profile["incident_subtype"].strip().lower() == case_profile["incident_subtype"].strip().lower()
        )

        anchored = location_match or text_similarity >= 0.45 or (subtype_match and text_similarity >= 0.25)
        if not anchored:
            return None

        score = 0.0
        if report_profile.get("incident_type") and case_profile.get("incident_type"):
            score += 0.35
        if subtype_match:
            score += 0.15
        if location_match:
            score += 0.30
        if day_match:
            score += 0.10
        if text_similarity >= 0.6:
            score += 0.25
        elif text_similarity >= 0.45:
            score += 0.20
        elif text_similarity >= 0.3:
            score += 0.12
        elif text_similarity >= 0.2:
            score += 0.06

        return {
            "case": case,
            "score": round(score, 3),
            "location_match": location_match,
            "day_match": day_match,
            "subtype_match": subtype_match,
            "text_similarity": round(text_similarity, 3),
            "case_profile": case_profile,
        }

    def _rank_case_candidates(self, report_profile: Dict[str, Any], cases: List[Case]) -> List[Dict[str, Any]]:
        ranked = []
        for case in cases:
            scored = self._score_case_candidate(report_profile, case)
            if scored:
                ranked.append(scored)
        ranked.sort(
            key=lambda item: (
                item.get("score", 0),
                item.get("location_match", False),
                item.get("text_similarity", 0),
                item["case"].updated_at,
            ),
            reverse=True,
        )
        return ranked

    @staticmethod
    def _select_direct_match(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not candidates:
            return None
        best = candidates[0]
        runner_up = candidates[1] if len(candidates) > 1 else None

        strong_location_match = (
            best.get("location_match")
            and best.get("score", 0) >= 0.7
            and (
                best.get("day_match")
                or best.get("subtype_match")
                or best.get("text_similarity", 0) >= 0.2
            )
        )
        strong_text_match = best.get("text_similarity", 0) >= 0.7 and best.get("score", 0) >= 0.75
        clear_margin = not runner_up or (best.get("score", 0) - runner_up.get("score", 0)) >= 0.12

        if clear_margin and (strong_location_match or strong_text_match):
            return best
        return None

    @staticmethod
    def _select_fallback_match(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not candidates:
            return None
        best = candidates[0]
        if (
            best.get("location_match")
            and best.get("score", 0) >= 0.65
            and (
                best.get("day_match")
                or best.get("subtype_match")
                or best.get("text_similarity", 0) >= 0.35
            )
        ):
            return best
        if best.get("text_similarity", 0) >= 0.75 and best.get("score", 0) >= 0.8:
            return best
        return None

    def _infer_incident_from_text(self, text: str) -> Dict[str, str]:
        lower_text = (text or "").lower()
        if any(term in lower_text for term in ("hit and run", "hit-and-run")):
            return {"type": "accident", "subtype": "hit_and_run", "severity": "high"}
        if any(term in lower_text for term in ("collision", "crash", "rear-ended", "rear ended", "car accident", "traffic")):
            return {"type": "accident", "subtype": "traffic_collision", "severity": "medium"}
        if any(term in lower_text for term in ("armed robbery", "robbed", "robbery", "mugged", "held up")):
            return {"type": "crime", "subtype": "robbery", "severity": "high"}
        if any(term in lower_text for term in ("burglary", "break in", "break-in", "broke into")):
            return {"type": "crime", "subtype": "burglary", "severity": "high"}
        if any(term in lower_text for term in ("shooting", "shot", "gunfire", "gun", "stabbed", "knife")):
            return {"type": "crime", "subtype": "violent_crime", "severity": "critical"}
        if any(term in lower_text for term in ("assault", "attacked", "punched", "fight")):
            return {"type": "crime", "subtype": "assault", "severity": "high"}
        if any(term in lower_text for term in ("theft", "stolen", "shoplifting", "stole")):
            return {"type": "crime", "subtype": "theft", "severity": "medium"}
        if any(term in lower_text for term in ("fire", "smoke", "burning")):
            return {"type": "incident", "subtype": "fire", "severity": "high"}
        if any(term in lower_text for term in ("collapsed", "medical", "overdose", "ambulance")):
            return {"type": "incident", "subtype": "medical", "severity": "high"}
        if any(term in lower_text for term in ("suspicious", "disturbance", "trespassing")):
            return {"type": "incident", "subtype": "suspicious_activity", "severity": "medium"}
        return {"type": "other", "subtype": "", "severity": "medium"}

    @staticmethod
    def _extract_incident_datetime(source: Dict[str, Any], fallback: Optional[datetime]) -> Optional[datetime]:
        if not isinstance(source, dict):
            source = {}

        for key in ("incident_at", "occurred_at", "event_time", "start", "incident_date", "date"):
            raw_value = source.get(key)
            if not raw_value:
                continue

            if isinstance(raw_value, datetime):
                return raw_value

            value = str(raw_value).strip()
            if not value:
                continue

            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
                    try:
                        return datetime.strptime(value, fmt)
                    except ValueError:
                        continue

        return fallback

    def _build_grouping_metadata(self, report_profile: Dict[str, Any]) -> Dict[str, Any]:
        grouping = {
            "match_version": "v2",
            "incident_type": report_profile.get("incident_type"),
            "incident_subtype": report_profile.get("incident_subtype"),
            "severity": report_profile.get("severity"),
            "location": report_profile.get("location"),
            "location_key": report_profile.get("location_key"),
            "reported_day": report_profile.get("day_key"),
            "text_signature": report_profile.get("text_signature"),
            "updated_at": datetime.utcnow().isoformat(),
        }
        return {key: value for key, value in grouping.items() if value not in (None, "", [])}

    @staticmethod
    def _case_sort_timestamp(case: Case) -> datetime:
        value = getattr(case, "updated_at", None) or getattr(case, "created_at", None)
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return datetime.min
        return datetime.min

    async def _resolve_current_case(
        self,
        report: ReconstructionSession,
        available_cases: List[Case],
    ) -> Optional[Case]:
        cases_by_id = {case.id: case for case in available_cases}

        if report.case_id:
            case = cases_by_id.get(report.case_id) or await firestore_service.get_case(report.case_id)
            if case:
                if (case.status or "").lower() == "merged":
                    metadata = dict(case.metadata or {})
                    merged_into = metadata.get("merged_into")
                    if merged_into:
                        replacement = cases_by_id.get(merged_into) or await firestore_service.get_case(merged_into)
                        if replacement and (replacement.status or "").lower() != "merged":
                            return replacement
                    return None
                return case

        linked_cases = [case for case in available_cases if report.id in (case.report_ids or [])]
        if not linked_cases:
            return None
        linked_cases.sort(
            key=lambda case: (len(case.report_ids or []), self._case_sort_timestamp(case)),
            reverse=True,
        )
        return linked_cases[0]

    async def _sync_report_case_membership(
        self,
        target_case: Case,
        report: ReconstructionSession,
        linked_cases: List[Case],
        report_profile: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Ensure a report exists on only one canonical case."""
        target_case_id = target_case.id
        cleaned_case_ids = set()

        for linked_case in linked_cases:
            if linked_case.id == target_case_id or linked_case.id in cleaned_case_ids:
                continue
            cleaned_case_ids.add(linked_case.id)
            if report.id not in (linked_case.report_ids or []):
                continue

            linked_case.report_ids = [report_id for report_id in linked_case.report_ids if report_id != report.id]
            linked_case.updated_at = datetime.utcnow()
            metadata = dict(linked_case.metadata or {})
            if not linked_case.report_ids:
                linked_case.status = "merged"
                metadata["merged_into"] = target_case_id
                metadata["merged_at"] = datetime.utcnow().isoformat()
            linked_case.metadata = metadata
            await firestore_service.update_case(linked_case)
            if linked_case.report_ids:
                asyncio.create_task(self.generate_case_summary(linked_case.id))

        assigned_case_id = await self._attach_report_to_case(
            target_case,
            report,
            report_profile=report_profile,
        )
        report.case_id = assigned_case_id
        return assigned_case_id

    async def _attach_report_to_case(
        self,
        case: Case,
        report: ReconstructionSession,
        report_profile: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Attach a report to an existing case and refresh stable metadata."""
        report_profile = report_profile or await self._build_incident_profile(report)
        metadata = dict(case.metadata or {})
        grouping = metadata.get("grouping", {}) if isinstance(metadata.get("grouping"), dict) else {}

        report_added = report.id not in case.report_ids
        if report_added:
            case.report_ids.append(report.id)

        for key, value in self._build_grouping_metadata(report_profile).items():
            if value and not grouping.get(key):
                grouping[key] = value
        grouping["updated_at"] = datetime.utcnow().isoformat()
        if grouping:
            metadata["grouping"] = grouping

        if report_profile.get("incident_type") and not metadata.get("incident_type"):
            metadata["incident_type"] = report_profile["incident_type"]
        if report_profile.get("incident_subtype") and not metadata.get("incident_subtype"):
            metadata["incident_subtype"] = report_profile["incident_subtype"]
        if report_profile.get("severity") and not metadata.get("severity"):
            metadata["severity"] = report_profile["severity"]

        case.timeframe = dict(case.timeframe or {})
        if report_profile.get("occurred_at") and not case.timeframe.get("start"):
            case.timeframe["start"] = report_profile["occurred_at"].isoformat()
        if report_profile.get("day_key") and not case.timeframe.get("description"):
            try:
                parsed_day = datetime.fromisoformat(report_profile["day_key"])
                case.timeframe["description"] = parsed_day.strftime("%B %d, %Y")
            except ValueError:
                case.timeframe["description"] = report_profile["day_key"]

        if report_profile.get("location") and not case.location:
            case.location = report_profile["location"]

        case.metadata = metadata
        case.updated_at = datetime.utcnow()

        if report_added or metadata.get("grouping"):
            await firestore_service.update_case(case)
        if report_added:
            await self.generate_case_summary(case.id)
        return case.id

    async def assign_report_to_case(self, report: ReconstructionSession) -> str:
        """
        Analyze a report and assign it to an existing case or create a new one.
        Returns the case_id.
        """
        async with self._assignment_lock:
            all_cases = await firestore_service.list_cases(limit=0)
            cases = [
                case for case in all_cases
                if (case.status or "").lower() != "merged"
            ]
            linked_cases = [case for case in all_cases if report.id in (case.report_ids or [])]
            current_case = await self._resolve_current_case(report, cases)
            report_profile = await self._build_incident_profile(report)

            if not cases:
                case_id = await self._create_case_for_report(report, report_profile=report_profile)
                report.case_id = case_id
                return case_id

            ranked_candidates = self._rank_case_candidates(report_profile, cases)
            selected_case: Optional[Case] = None

            direct_match = self._select_direct_match(ranked_candidates)
            if direct_match:
                selected_case = direct_match["case"]

            if self.client and not selected_case:
                llm_candidates = [entry["case"] for entry in ranked_candidates[:6]]
                if current_case and current_case.id not in {case.id for case in llm_candidates}:
                    llm_candidates = [current_case] + llm_candidates
                llm_candidates = llm_candidates[:6] or cases[:12]
                match_case_id = await self._find_matching_case(report, llm_candidates)

                if match_case_id:
                    selected_case = next((case for case in cases if case.id == match_case_id), None)
                    if not selected_case:
                        selected_case = await firestore_service.get_case(match_case_id)

            if not selected_case:
                fallback_match = self._select_fallback_match(ranked_candidates)
                if fallback_match:
                    selected_case = fallback_match["case"]

            if not selected_case and current_case:
                selected_case = current_case

            if not selected_case:
                case_id = await self._create_case_for_report(report, report_profile=report_profile)
                report.case_id = case_id
                return case_id

            return await self._sync_report_case_membership(
                selected_case,
                report,
                linked_cases=linked_cases,
                report_profile=report_profile,
            )

    async def _find_matching_case(self, report: ReconstructionSession, cases: List[Case]) -> Optional[str]:
        """Use Gemini LLM to intelligently match reports to existing cases.
        
        Checks: incident type, location, date/time, description similarity.
        Only groups reports that clearly describe the SAME specific incident.
        """
        report_text = self._build_report_matching_text(report)
        if not report_text:
            return None

        if not cases:
            return None

        # Always use LLM for case matching — embeddings are too loose
        return await self._find_matching_case_llm(report, cases)

    async def _find_matching_case_llm(self, report: ReconstructionSession, cases: List[Case]) -> Optional[str]:
        """Simple direct Gemini call to match reports to cases using numbered labels."""
        try:
            report_text = self._build_report_matching_text(report)
            if not report_text:
                return None

            # Build numbered case descriptions — easier for Gemini than UUIDs
            case_map = {}  # number -> case object
            case_descriptions = []
            for idx, case in enumerate(cases, 1):
                case_map[idx] = case
                case_profile = self._build_case_profile(case)
                timeframe = case.timeframe.get("description", "Unknown") if isinstance(case.timeframe, dict) else "Unknown"
                if not timeframe and case_profile.get("day_key"):
                    timeframe = case_profile["day_key"]
                case_descriptions.append(
                    f"[{idx}] {case.title}\n"
                    f"    Summary: {(case.summary or 'No summary')[:300]}\n"
                    f"    Location: {case_profile.get('location') or 'Unknown'}\n"
                    f"    Incident Type: {case_profile.get('incident_type') or 'Unknown'}\n"
                    f"    Incident Subtype: {case_profile.get('incident_subtype') or 'Unknown'}\n"
                    f"    Timeframe: {timeframe}\n"
                    f"    Reports: {len(case.report_ids)}"
                )

            cases_text = "\n".join(case_descriptions)

            prompt = f"""You are a police case classifier. Given a NEW witness report, determine if it describes the SAME specific incident as any existing case.

Match criteria — ALL must be true:
- Same TYPE of incident (car crash = car crash, robbery = robbery)
- Same LOCATION (same street or intersection)  
- Same TIME PERIOD (same day/date)
- Descriptions clearly refer to the same event

Do NOT match different types of incidents together (e.g., car accident ≠ robbery).

NEW WITNESS REPORT:
"{report.title}"
Statements: {report_text[:600]}

EXISTING CASES:
{cases_text}

If the new report matches an existing case, reply with just the number like: 1
If it does NOT match any case, reply with: 0"""

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = self.client.models.generate_content(
                        model="gemini-2.5-flash-lite",
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.0,
                            max_output_tokens=50,
                        )
                    )
                    break
                except Exception as retry_err:
                    err_str = str(retry_err).lower()
                    if "429" in err_str or "rate" in err_str or "quota" in err_str or "exhausted" in err_str:
                        wait_time = 15 * (attempt + 1)
                        logger.warning(f"Rate limited on attempt {attempt+1}, waiting {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        if attempt == max_retries - 1:
                            logger.error(f"Rate limited after {max_retries} retries for case matching")
                            return None
                    else:
                        raise

            if not response or not response.text:
                logger.warning("Empty Gemini response for case matching")
                return None

            answer = response.text.strip()
            logger.info(f"Case matching for '{report.title}': Gemini says '{answer}'")

            # Parse the number from response
            import re
            numbers = re.findall(r'\d+', answer)
            if numbers:
                match_num = int(numbers[0])
                if match_num > 0 and match_num in case_map:
                    matched_case = case_map[match_num]
                    logger.info(f"✅ Report '{report.title}' MATCHED to [{match_num}] {matched_case.case_number}: {matched_case.title}")
                    return matched_case.id
                elif match_num == 0:
                    logger.info(f"Report '{report.title}' = NO MATCH (Gemini said 0)")
                else:
                    logger.warning(f"Invalid case number {match_num} from Gemini")
            else:
                logger.warning(f"Could not parse number from Gemini response: '{answer}'")

            return None

        except Exception as e:
            logger.error(f"Error in LLM case matching: {e}")
            return None

        except Exception as e:
            logger.error(f"Error in LLM case matching: {e}")
            return None

    async def _create_case_for_report(
        self,
        report: ReconstructionSession,
        report_profile: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a new case for a report."""
        import uuid
        report_profile = report_profile or await self._build_incident_profile(report)
        async with firestore_service._sequence_lock:
            case_number = await firestore_service._next_case_number_unlocked()
            title = report.title if report.title != "Untitled Session" else f"Case {case_number}"

            # Build a summary from witness statements for matching purposes
            report_text = self._get_report_text(report)
            summary_source = report.metadata.get("ai_summary") or report_text
            summary = summary_source[:500] if summary_source else ""
            location = report_profile.get("location", "")
            timeframe_start = report_profile.get("occurred_at") or report.created_at
            timeframe_description = ""
            if timeframe_start:
                timeframe_description = timeframe_start.strftime("%B %d, %Y")

            metadata = {
                "auto_created": True,
                "grouping": self._build_grouping_metadata(report_profile),
            }
            if report_profile.get("incident_type"):
                metadata["incident_type"] = report_profile["incident_type"]
            if report_profile.get("incident_subtype"):
                metadata["incident_subtype"] = report_profile["incident_subtype"]
            if report_profile.get("severity"):
                metadata["severity"] = report_profile["severity"]

            case = Case(
                id=str(uuid.uuid4()),
                case_number=case_number,
                title=title,
                summary=summary,
                report_ids=[report.id],
                location=location,
                timeframe={
                    "start": timeframe_start.isoformat() if timeframe_start else "",
                    "description": timeframe_description or "Unknown date"
                },
                metadata=metadata,
            )

            await firestore_service.create_case(case)
        logger.info(f"Created new case {case.case_number} for report {report.id}")

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
                        chat_model = await model_selector.get_best_model_for_task("analysis")
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
        text = self._build_report_matching_text(report)
        if text:
            await embedding_service.embed_text(text)  # Returns tuple, we ignore it here

    async def search_cases(self, query: str, limit: int = 10) -> list:
        """Search cases by semantic similarity."""
        from app.services.embedding_service import embedding_service
        cases = await firestore_service.list_cases(limit=100)
        documents = [(c.id, self._build_case_profile(c)["matching_text"] or c.title) for c in cases]
        results = await embedding_service.semantic_search(query, documents, top_k=limit)
        return results

    async def search_reports(self, query: str, limit: int = 10) -> list:
        """Search reports by semantic similarity."""
        from app.services.embedding_service import embedding_service
        sessions = await firestore_service.list_sessions(limit=100)
        documents = [(s.id, self._build_report_matching_text(s) or s.title) for s in sessions]
        results = await embedding_service.semantic_search(query, documents, top_k=limit)
        return results

    async def _classify_incident(self, report: ReconstructionSession) -> Optional[Dict]:
        """Use multi-model verification to classify the incident type.
        
        This is a high-stakes decision, so we cross-verify using both Gemini
        and Gemma models to ensure accuracy. Falls back to single model if
        verification is disabled or quota is exhausted.
        """
        if not self.client:
            return None
        try:
            report_text = self._build_report_matching_text(report)
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
                result = IncidentClassificationResponse.model_validate_json(response_text)
                return result.model_dump()
            
            # Use multi-model verification for this high-stakes classification
            classification_model = await model_selector.get_best_model_for_task("classification")
            verification = await multi_model_verifier.verify_extraction(
                prompt=prompt,
                response_schema=IncidentClassificationResponse,
                primary_model=classification_model,
                temperature=0.1,
                comparison_fields=["type", "subtype", "severity"],
            )
            
            # Handle verification results
            if verification.result == VerificationResult.ERROR:
                logger.warning("Multi-model verification failed, skipping classification")
                return None
            
            if verification.result == VerificationResult.DISCREPANCY:
                # Log discrepancy but still use primary response
                logger.warning(
                    f"Classification discrepancy detected for report {report.id}: "
                    f"{verification.discrepancies}"
                )
            
            if verification.primary_response and verification.primary_response.parsed_response:
                result = verification.primary_response.parsed_response
                response_text = verification.primary_response.response_text
                
                # Cache the verified result
                await response_cache.set(
                    prompt, response_text, 
                    context_key="classify_incident", 
                    ttl_seconds=7200
                )
                
                result_dict = result.model_dump()
                # Add verification metadata
                result_dict["_verification"] = {
                    "result": verification.result.value,
                    "confidence": verification.confidence_score,
                    "discrepancies": verification.discrepancies,
                }
                return result_dict
            
            return None
        except Exception as e:
            logger.warning(f"Failed to classify incident: {e}")
            return None


# Global instance
case_manager = CaseManager()
