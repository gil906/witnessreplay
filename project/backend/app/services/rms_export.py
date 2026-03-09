"""
RMS (Records Management System) Export Service.

Provides export formats compatible with common police RMS systems:
- Standard XML format
- CSV format for bulk import
- NIEM-compliant JSON (simplified)
"""

import csv
import io
import json
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional
from xml.dom import minidom

from app.models.schemas import Case, ReconstructionSession, Witness, WitnessStatement
from app.services.firestore import firestore_service

logger = logging.getLogger(__name__)


class RMSExportService:
    """Service for exporting case data in RMS-compatible formats."""

    def __init__(self):
        self.niem_namespace = "http://release.niem.gov/niem/niem-core/4.0/"
        self.justice_namespace = "http://release.niem.gov/niem/domains/jxdm/6.1/"

    async def get_full_case_data(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full case data including all reports."""
        case = await firestore_service.get_case(case_id)
        if not case:
            return None

        reports = []
        for report_id in case.report_ids:
            report = await firestore_service.get_session(report_id)
            if report:
                reports.append(report)

        return {
            "case": case,
            "reports": reports,
        }

    def _format_datetime(self, dt: Optional[datetime]) -> str:
        """Format datetime for RMS export (ISO 8601)."""
        if dt is None:
            return ""
        return dt.isoformat() if isinstance(dt, datetime) else str(dt)

    def _sanitize_xml_text(self, text: str) -> str:
        """Sanitize text for XML content."""
        if not text:
            return ""
        # Remove control characters except newlines and tabs
        return "".join(c if c in "\n\t" or (ord(c) >= 32) else " " for c in str(text))

    # ── XML Export ────────────────────────────────────────────────────────────

    async def export_to_xml(self, case_id: str) -> Optional[str]:
        """Export case to standard XML format for RMS import."""
        data = await self.get_full_case_data(case_id)
        if not data:
            return None

        case: Case = data["case"]
        reports: List[ReconstructionSession] = data["reports"]

        root = ET.Element("RMSCaseExport")
        root.set("xmlns", "http://witnessreplay.com/rms/1.0")
        root.set("exportTimestamp", datetime.utcnow().isoformat())
        root.set("version", "1.0")

        # Case Information
        case_elem = ET.SubElement(root, "Case")
        ET.SubElement(case_elem, "CaseID").text = case.id
        ET.SubElement(case_elem, "CaseNumber").text = case.case_number
        ET.SubElement(case_elem, "Title").text = self._sanitize_xml_text(case.title)
        ET.SubElement(case_elem, "Summary").text = self._sanitize_xml_text(case.summary)
        ET.SubElement(case_elem, "Location").text = self._sanitize_xml_text(case.location)
        ET.SubElement(case_elem, "Status").text = case.status
        ET.SubElement(case_elem, "CreatedAt").text = self._format_datetime(case.created_at)
        ET.SubElement(case_elem, "UpdatedAt").text = self._format_datetime(case.updated_at)

        # Timeframe
        timeframe_elem = ET.SubElement(case_elem, "Timeframe")
        if case.timeframe:
            ET.SubElement(timeframe_elem, "Start").text = str(case.timeframe.get("start", ""))
            ET.SubElement(timeframe_elem, "End").text = str(case.timeframe.get("end", ""))
            ET.SubElement(timeframe_elem, "Description").text = self._sanitize_xml_text(
                case.timeframe.get("description", "")
            )

        # Incident Classification (from metadata)
        if case.metadata:
            classification_elem = ET.SubElement(case_elem, "IncidentClassification")
            ET.SubElement(classification_elem, "Type").text = case.metadata.get("incident_type", "")
            ET.SubElement(classification_elem, "Subtype").text = case.metadata.get("incident_subtype", "")
            ET.SubElement(classification_elem, "Severity").text = case.metadata.get("severity", "")

        # Reports
        reports_elem = ET.SubElement(root, "Reports")
        for report in reports:
            report_elem = ET.SubElement(reports_elem, "Report")
            ET.SubElement(report_elem, "ReportID").text = report.id
            ET.SubElement(report_elem, "ReportNumber").text = report.report_number or ""
            ET.SubElement(report_elem, "Title").text = self._sanitize_xml_text(report.title)
            ET.SubElement(report_elem, "SourceType").text = report.source_type
            ET.SubElement(report_elem, "Status").text = report.status
            ET.SubElement(report_elem, "CreatedAt").text = self._format_datetime(report.created_at)

            # Witnesses in Report
            witnesses_elem = ET.SubElement(report_elem, "Witnesses")
            for witness in report.witnesses:
                witness_elem = ET.SubElement(witnesses_elem, "Witness")
                ET.SubElement(witness_elem, "WitnessID").text = witness.id
                ET.SubElement(witness_elem, "Name").text = self._sanitize_xml_text(witness.name)
                ET.SubElement(witness_elem, "Contact").text = self._sanitize_xml_text(witness.contact or "")
                ET.SubElement(witness_elem, "Location").text = self._sanitize_xml_text(witness.location or "")
                ET.SubElement(witness_elem, "SourceType").text = witness.source_type

            # Statements in Report
            statements_elem = ET.SubElement(report_elem, "WitnessStatements")
            for stmt in report.witness_statements:
                stmt_elem = ET.SubElement(statements_elem, "Statement")
                ET.SubElement(stmt_elem, "StatementID").text = stmt.id
                ET.SubElement(stmt_elem, "Text").text = self._sanitize_xml_text(stmt.text)
                ET.SubElement(stmt_elem, "Timestamp").text = self._format_datetime(stmt.timestamp)
                ET.SubElement(stmt_elem, "IsCorrection").text = str(stmt.is_correction).lower()
                ET.SubElement(stmt_elem, "WitnessID").text = stmt.witness_id or ""
                ET.SubElement(stmt_elem, "WitnessName").text = self._sanitize_xml_text(stmt.witness_name or "")

            # Scene Elements
            elements_elem = ET.SubElement(report_elem, "SceneElements")
            for element in report.current_scene_elements:
                elem = ET.SubElement(elements_elem, "Element")
                ET.SubElement(elem, "ElementID").text = element.id
                ET.SubElement(elem, "Type").text = element.type
                ET.SubElement(elem, "Description").text = self._sanitize_xml_text(element.description)
                ET.SubElement(elem, "Position").text = self._sanitize_xml_text(element.position or "")
                ET.SubElement(elem, "Color").text = element.color or ""
                ET.SubElement(elem, "Confidence").text = str(element.confidence)

            # Timeline Events
            timeline_elem = ET.SubElement(report_elem, "Timeline")
            for event in report.timeline:
                event_elem = ET.SubElement(timeline_elem, "Event")
                ET.SubElement(event_elem, "EventID").text = event.id
                ET.SubElement(event_elem, "Sequence").text = str(event.sequence)
                ET.SubElement(event_elem, "Description").text = self._sanitize_xml_text(event.description)
                ET.SubElement(event_elem, "Timestamp").text = self._format_datetime(event.timestamp)
                ET.SubElement(event_elem, "Confidence").text = str(event.confidence)

        # Pretty print XML
        xml_str = ET.tostring(root, encoding="unicode")
        parsed = minidom.parseString(xml_str)
        return parsed.toprettyxml(indent="  ")

    # ── CSV Export ────────────────────────────────────────────────────────────

    async def export_to_csv(self, case_id: str) -> Optional[Dict[str, str]]:
        """
        Export case to CSV format for bulk import.
        Returns dict with multiple CSV files for different data types.
        """
        data = await self.get_full_case_data(case_id)
        if not data:
            return None

        case: Case = data["case"]
        reports: List[ReconstructionSession] = data["reports"]

        csv_files = {}

        # Case Summary CSV
        case_buffer = io.StringIO()
        case_writer = csv.writer(case_buffer)
        case_writer.writerow([
            "case_id", "case_number", "title", "summary", "location", "status",
            "incident_type", "incident_subtype", "severity",
            "timeframe_start", "timeframe_end", "timeframe_description",
            "created_at", "updated_at", "report_count"
        ])
        case_writer.writerow([
            case.id,
            case.case_number,
            case.title,
            case.summary,
            case.location,
            case.status,
            case.metadata.get("incident_type", ""),
            case.metadata.get("incident_subtype", ""),
            case.metadata.get("severity", ""),
            case.timeframe.get("start", "") if case.timeframe else "",
            case.timeframe.get("end", "") if case.timeframe else "",
            case.timeframe.get("description", "") if case.timeframe else "",
            self._format_datetime(case.created_at),
            self._format_datetime(case.updated_at),
            len(reports)
        ])
        csv_files["case.csv"] = case_buffer.getvalue()

        # Reports CSV
        reports_buffer = io.StringIO()
        reports_writer = csv.writer(reports_buffer)
        reports_writer.writerow([
            "report_id", "case_id", "report_number", "title", "source_type", "status",
            "witness_name", "witness_contact", "witness_location",
            "created_at", "updated_at", "statement_count", "scene_element_count"
        ])
        for report in reports:
            reports_writer.writerow([
                report.id,
                case.id,
                report.report_number or "",
                report.title,
                report.source_type,
                report.status,
                report.witness_name or "",
                report.witness_contact or "",
                report.witness_location or "",
                self._format_datetime(report.created_at),
                self._format_datetime(report.updated_at),
                len(report.witness_statements),
                len(report.current_scene_elements)
            ])
        csv_files["reports.csv"] = reports_buffer.getvalue()

        # Witnesses CSV
        witnesses_buffer = io.StringIO()
        witnesses_writer = csv.writer(witnesses_buffer)
        witnesses_writer.writerow([
            "witness_id", "report_id", "case_id", "name", "contact", "location",
            "source_type", "reliability_score", "reliability_grade", "created_at"
        ])
        for report in reports:
            for witness in report.witnesses:
                reliability = witness.reliability
                witnesses_writer.writerow([
                    witness.id,
                    report.id,
                    case.id,
                    witness.name,
                    witness.contact or "",
                    witness.location or "",
                    witness.source_type,
                    reliability.overall_score if reliability else "",
                    reliability.reliability_grade if reliability else "",
                    self._format_datetime(witness.created_at)
                ])
        csv_files["witnesses.csv"] = witnesses_buffer.getvalue()

        # Statements CSV
        statements_buffer = io.StringIO()
        statements_writer = csv.writer(statements_buffer)
        statements_writer.writerow([
            "statement_id", "report_id", "case_id", "witness_id", "witness_name",
            "text", "is_correction", "timestamp", "detected_topics"
        ])
        for report in reports:
            for stmt in report.witness_statements:
                statements_writer.writerow([
                    stmt.id,
                    report.id,
                    case.id,
                    stmt.witness_id or "",
                    stmt.witness_name or "",
                    stmt.text,
                    stmt.is_correction,
                    self._format_datetime(stmt.timestamp),
                    ";".join(stmt.detected_topics) if stmt.detected_topics else ""
                ])
        csv_files["statements.csv"] = statements_buffer.getvalue()

        # Scene Elements CSV
        elements_buffer = io.StringIO()
        elements_writer = csv.writer(elements_buffer)
        elements_writer.writerow([
            "element_id", "report_id", "case_id", "type", "description",
            "position", "color", "size", "confidence", "needs_review"
        ])
        for report in reports:
            for elem in report.current_scene_elements:
                elements_writer.writerow([
                    elem.id,
                    report.id,
                    case.id,
                    elem.type,
                    elem.description,
                    elem.position or "",
                    elem.color or "",
                    elem.size or "",
                    elem.confidence,
                    elem.needs_review
                ])
        csv_files["scene_elements.csv"] = elements_buffer.getvalue()

        # Timeline Events CSV
        timeline_buffer = io.StringIO()
        timeline_writer = csv.writer(timeline_buffer)
        timeline_writer.writerow([
            "event_id", "report_id", "case_id", "sequence", "description",
            "timestamp", "confidence", "needs_review", "image_url"
        ])
        for report in reports:
            for event in report.timeline:
                timeline_writer.writerow([
                    event.id,
                    report.id,
                    case.id,
                    event.sequence,
                    event.description,
                    self._format_datetime(event.timestamp),
                    event.confidence,
                    event.needs_review,
                    event.image_url or ""
                ])
        csv_files["timeline.csv"] = timeline_buffer.getvalue()

        return csv_files

    # ── NIEM-Compliant JSON Export ────────────────────────────────────────────

    async def export_to_niem_json(self, case_id: str) -> Optional[Dict[str, Any]]:
        """
        Export case to NIEM-compliant JSON format (simplified).
        
        Based on NIEM 4.0 Justice domain for incident/case reporting.
        Simplified for common RMS integration requirements.
        """
        data = await self.get_full_case_data(case_id)
        if not data:
            return None

        case: Case = data["case"]
        reports: List[ReconstructionSession] = data["reports"]

        # Build NIEM-structured document
        niem_doc = {
            "@context": {
                "nc": self.niem_namespace,
                "j": self.justice_namespace,
                "wr": "http://witnessreplay.com/niem/1.0/"
            },
            "nc:DocumentExchangeDocument": {
                "nc:DocumentCreationDate": {
                    "nc:Date": datetime.utcnow().strftime("%Y-%m-%d")
                },
                "nc:DocumentCreationTime": {
                    "nc:Time": datetime.utcnow().strftime("%H:%M:%S")
                },
                "nc:DocumentSourceText": "WitnessReplay RMS Export",
                "nc:DocumentDescriptionText": f"Case export for {case.case_number}"
            },
            "j:Case": {
                "j:CaseNumberText": case.case_number,
                "nc:CaseTitleText": case.title,
                "nc:CaseCategoryText": case.metadata.get("incident_type", "Other"),
                "j:CaseSubCategoryText": case.metadata.get("incident_subtype", ""),
                "nc:StatusText": case.status.upper(),
                "nc:ActivityDate": {
                    "nc:Date": case.created_at.strftime("%Y-%m-%d") if case.created_at else ""
                },
                "nc:ActivityDescriptionText": case.summary,
                "j:IncidentSeverityCode": case.metadata.get("severity", "Unknown"),
                "nc:Location": {
                    "nc:LocationDescriptionText": case.location,
                    "nc:AddressFullText": case.location
                },
                "j:IncidentAugmentation": {
                    "j:IncidentReportedDate": {
                        "nc:Date": case.created_at.strftime("%Y-%m-%d") if case.created_at else ""
                    },
                    "wr:IncidentTimeframe": {
                        "nc:StartDate": {"nc:Date": str(case.timeframe.get("start", ""))} if case.timeframe else None,
                        "nc:EndDate": {"nc:Date": str(case.timeframe.get("end", ""))} if case.timeframe else None,
                        "nc:DescriptionText": case.timeframe.get("description", "") if case.timeframe else ""
                    }
                },
                "j:CaseOfficialCaseIdentification": {
                    "nc:IdentificationID": case.id
                }
            },
            "j:Incident": {
                "nc:ActivityIdentification": {
                    "nc:IdentificationID": case.id
                },
                "nc:ActivityDate": {
                    "nc:Date": case.created_at.strftime("%Y-%m-%d") if case.created_at else ""
                },
                "nc:ActivityDescriptionText": case.summary,
                "j:IncidentCategoryCode": case.metadata.get("incident_type", "Unknown")
            },
            "j:Subject": [],  # Witnesses/subjects
            "j:Witness": [],
            "j:Report": [],
            "j:Evidence": []
        }

        # Add witnesses
        witness_index = 0
        for report in reports:
            for witness in report.witnesses:
                witness_index += 1
                witness_entry = {
                    "nc:RoleOfPerson": {
                        "nc:PersonName": {
                            "nc:PersonFullName": witness.name
                        },
                        "nc:PersonIdentification": {
                            "nc:IdentificationID": witness.id
                        },
                        "j:PersonContactInformation": {
                            "nc:ContactInformationDescriptionText": witness.contact or ""
                        }
                    },
                    "j:WitnessSequenceNumberText": str(witness_index),
                    "wr:WitnessSourceType": witness.source_type,
                    "wr:WitnessLocation": witness.location or ""
                }
                
                # Add reliability if available
                if witness.reliability:
                    witness_entry["wr:WitnessReliability"] = {
                        "wr:ReliabilityScore": witness.reliability.overall_score,
                        "wr:ReliabilityGrade": witness.reliability.reliability_grade
                    }
                
                niem_doc["j:Witness"].append(witness_entry)

        # Add reports
        for report in reports:
            report_entry = {
                "nc:DocumentIdentification": {
                    "nc:IdentificationID": report.id
                },
                "nc:DocumentSequenceID": report.report_number or report.id,
                "nc:DocumentTitleText": report.title,
                "nc:DocumentCreationDate": {
                    "nc:Date": report.created_at.strftime("%Y-%m-%d") if report.created_at else ""
                },
                "nc:DocumentStatusText": report.status,
                "j:ReportSourceType": report.source_type,
                "j:Statement": []
            }

            # Add statements to report
            for stmt in report.witness_statements:
                statement_entry = {
                    "nc:ActivityIdentification": {
                        "nc:IdentificationID": stmt.id
                    },
                    "nc:ActivityDescriptionText": stmt.text,
                    "nc:ActivityDate": {
                        "nc:DateTime": self._format_datetime(stmt.timestamp)
                    },
                    "j:StatementAuthorText": stmt.witness_name or "",
                    "wr:StatementIsCorrection": stmt.is_correction
                }
                report_entry["j:Statement"].append(statement_entry)

            niem_doc["j:Report"].append(report_entry)

        # Add evidence (scene elements as evidence items)
        evidence_index = 0
        for report in reports:
            for elem in report.current_scene_elements:
                evidence_index += 1
                evidence_entry = {
                    "nc:ItemIdentification": {
                        "nc:IdentificationID": elem.id
                    },
                    "j:EvidenceSequenceID": str(evidence_index),
                    "nc:ItemCategoryText": elem.type,
                    "nc:ItemDescriptionText": elem.description,
                    "wr:EvidenceConfidence": elem.confidence,
                    "wr:EvidenceNeedsReview": elem.needs_review
                }
                if elem.position:
                    evidence_entry["nc:ItemLocationText"] = elem.position
                if elem.color:
                    evidence_entry["nc:ItemColorDescriptionText"] = elem.color
                
                niem_doc["j:Evidence"].append(evidence_entry)

        # Add timeline as incident narrative
        timeline_events = []
        for report in reports:
            for event in report.timeline:
                timeline_events.append({
                    "nc:ActivityIdentification": {"nc:IdentificationID": event.id},
                    "nc:ActivitySequenceNumericText": str(event.sequence),
                    "nc:ActivityDescriptionText": event.description,
                    "nc:ActivityDate": {"nc:DateTime": self._format_datetime(event.timestamp)},
                    "wr:EventConfidence": event.confidence
                })
        
        if timeline_events:
            niem_doc["j:Incident"]["j:IncidentNarrative"] = timeline_events

        return niem_doc

    # ── Utility: Combined Export ──────────────────────────────────────────────

    async def export_case(
        self,
        case_id: str,
        format: str = "niem_json"
    ) -> Optional[Dict[str, Any]]:
        """
        Export case in specified format.
        
        Args:
            case_id: The case ID to export
            format: Export format - 'xml', 'csv', or 'niem_json'
            
        Returns:
            Export data in requested format, or None if case not found
        """
        if format == "xml":
            xml_content = await self.export_to_xml(case_id)
            return {"format": "xml", "content": xml_content, "content_type": "application/xml"}
        elif format == "csv":
            csv_files = await self.export_to_csv(case_id)
            return {"format": "csv", "files": csv_files, "content_type": "application/zip"}
        else:  # niem_json
            niem_data = await self.export_to_niem_json(case_id)
            return {"format": "niem_json", "content": niem_data, "content_type": "application/json"}


# Global instance
rms_export_service = RMSExportService()
