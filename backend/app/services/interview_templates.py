"""Interview templates for different crime/incident types.

Each template provides:
- Initial questions specific to the incident type
- Key details to extract during the interview
- Scene elements relevant to that type
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel


class InterviewTemplate(BaseModel):
    """Interview template for a specific incident type."""
    id: str
    name: str
    description: str
    icon: str
    category: str  # "crime", "accident", "incident"
    initial_questions: List[str]
    key_details: List[str]
    scene_elements: List[str]
    suggested_prompts: List[str]


# Interview templates for common crime/incident types
INTERVIEW_TEMPLATES: Dict[str, InterviewTemplate] = {
    "theft_burglary": InterviewTemplate(
        id="theft_burglary",
        name="Theft / Burglary",
        description="Property crimes including home/business break-ins, shoplifting, and theft",
        icon="🏠",
        category="crime",
        initial_questions=[
            "Can you describe what was stolen or taken?",
            "When did you first notice the theft or break-in?",
            "Were there any signs of forced entry?",
            "Did you see or hear anyone suspicious before or after?",
        ],
        key_details=[
            "Time of discovery vs. estimated time of incident",
            "Point of entry (door, window, etc.)",
            "Items stolen - descriptions, values, serial numbers",
            "State of the location (ransacked, neat theft)",
            "Suspect descriptions if seen",
            "Any witnesses nearby",
            "Security cameras or alarm systems",
        ],
        scene_elements=[
            "Entry/exit points",
            "Location of stolen items",
            "Disturbed areas",
            "Tools or evidence left behind",
            "Footprints or tire marks",
            "Lighting conditions",
        ],
        suggested_prompts=[
            "Was anything moved or out of place?",
            "Can you describe the exact items that were taken?",
            "Did you notice any unfamiliar vehicles in the area?",
        ],
    ),
    "assault_battery": InterviewTemplate(
        id="assault_battery",
        name="Assault / Battery",
        description="Physical altercations, fights, and violent encounters",
        icon="⚠️",
        category="crime",
        initial_questions=[
            "Can you describe what happened during the incident?",
            "How many people were involved?",
            "Were any weapons used or visible?",
            "Did anyone require medical attention?",
        ],
        key_details=[
            "Number of attackers and victims",
            "Physical descriptions of all parties",
            "Type of assault (punching, kicking, weapons)",
            "Sequence of events leading to assault",
            "Injuries observed",
            "Words exchanged before/during",
            "Relationship between parties if known",
            "Direction attackers fled",
        ],
        scene_elements=[
            "Location of incident",
            "Positions of people involved",
            "Any weapons or objects used",
            "Blood or evidence of struggle",
            "Witnesses present",
            "Escape route",
        ],
        suggested_prompts=[
            "What started the altercation?",
            "Can you describe the attacker's clothing?",
            "Did anyone try to intervene?",
        ],
    ),
    "traffic_accident": InterviewTemplate(
        id="traffic_accident",
        name="Traffic Accident",
        description="Vehicle collisions, hit-and-runs, and traffic incidents",
        icon="🚗",
        category="accident",
        initial_questions=[
            "How many vehicles were involved?",
            "Which direction were the vehicles traveling?",
            "What were the road and weather conditions?",
            "Did you see the moment of impact?",
        ],
        key_details=[
            "Number and types of vehicles",
            "License plates (partial or full)",
            "Vehicle colors, makes, models",
            "Direction of travel for each vehicle",
            "Speed estimates",
            "Traffic signals/signs state",
            "Road conditions",
            "Weather and visibility",
            "Injuries observed",
            "Driver descriptions",
        ],
        scene_elements=[
            "Intersection or road location",
            "Lane positions",
            "Traffic signals",
            "Skid marks",
            "Debris field",
            "Final resting positions",
            "Pedestrians or cyclists",
        ],
        suggested_prompts=[
            "Did any vehicle run a red light or stop sign?",
            "Were there any skid marks before impact?",
            "Where exactly did the vehicles end up after the collision?",
        ],
    ),
    "vandalism": InterviewTemplate(
        id="vandalism",
        name="Vandalism",
        description="Property damage, graffiti, and destruction",
        icon="🎨",
        category="crime",
        initial_questions=[
            "What property was damaged?",
            "When did you first notice the damage?",
            "Did you see or hear anyone in the area?",
            "Can you describe the extent of the damage?",
        ],
        key_details=[
            "Type of damage (graffiti, broken windows, etc.)",
            "Estimated cost of damage",
            "Time frame when damage occurred",
            "Tools or methods used",
            "Any messages or symbols left",
            "Previous incidents in the area",
            "Suspect descriptions if seen",
        ],
        scene_elements=[
            "Damaged property/surfaces",
            "Type of vandalism",
            "Tools left behind",
            "Paint or materials used",
            "Access points",
            "Lighting in the area",
        ],
        suggested_prompts=[
            "Is there any pattern or message in the damage?",
            "Has this property been vandalized before?",
            "Were there any security cameras nearby?",
        ],
    ),
    "robbery": InterviewTemplate(
        id="robbery",
        name="Robbery",
        description="Theft involving force or threat, including armed robbery and mugging",
        icon="💰",
        category="crime",
        initial_questions=[
            "Can you describe the robber(s)?",
            "Were any weapons used or displayed?",
            "What was taken from you?",
            "What did the robber(s) say?",
        ],
        key_details=[
            "Number of suspects",
            "Physical descriptions (height, build, clothing, distinguishing features)",
            "Weapons used (type, color, real or fake)",
            "Demands made",
            "Items taken (cash amount, cards, phone, jewelry)",
            "Vehicle used (make, model, color, plates)",
            "Direction of escape",
            "Voice characteristics (accent, tone)",
            "Any accomplices or lookouts",
        ],
        scene_elements=[
            "Location of robbery",
            "Entry and exit routes",
            "Position of victim(s)",
            "Position of robber(s)",
            "Weapon locations",
            "Witnesses present",
            "Getaway vehicle location",
        ],
        suggested_prompts=[
            "Did the robber have any tattoos or scars?",
            "How long did the encounter last?",
            "Did anyone else see what happened?",
        ],
    ),
    "suspicious_activity": InterviewTemplate(
        id="suspicious_activity",
        name="Suspicious Activity",
        description="Unusual behavior, loitering, or potential criminal reconnaissance",
        icon="👀",
        category="incident",
        initial_questions=[
            "What caught your attention about this activity?",
            "Can you describe the person(s) involved?",
            "How long did you observe this behavior?",
            "Where exactly did this occur?",
        ],
        key_details=[
            "Specific behaviors observed",
            "Number of individuals",
            "Physical descriptions",
            "Vehicle descriptions if any",
            "Time and duration",
            "Repeated occurrences",
            "Interaction with others",
            "Items carried",
        ],
        scene_elements=[
            "Location of activity",
            "Nearby buildings or landmarks",
            "Vehicles in the area",
            "Lighting conditions",
            "Time of day",
            "Other people present",
        ],
        suggested_prompts=[
            "Did they appear to be watching or photographing anything?",
            "Did you see them leave? In which direction?",
            "Have you seen this person before?",
        ],
    ),
    "domestic_incident": InterviewTemplate(
        id="domestic_incident",
        name="Domestic Incident",
        description="Disputes and altercations involving household members or partners",
        icon="🏘️",
        category="incident",
        initial_questions=[
            "Can you describe what you heard or saw?",
            "How many people were involved?",
            "Did you see or hear signs of physical violence?",
            "Do you know the individuals involved?",
        ],
        key_details=[
            "Nature of dispute",
            "Number of people involved",
            "Any children present",
            "Weapons seen or mentioned",
            "Physical altercation observed",
            "Previous incidents known",
            "Current state when last observed",
        ],
        scene_elements=[
            "Location (address, apartment number)",
            "Access points to location",
            "Vehicles at location",
            "Visible signs of disturbance",
            "Neighbors present",
        ],
        suggested_prompts=[
            "Could you hear what they were arguing about?",
            "Did anyone try to leave or appear to be prevented from leaving?",
            "Is this an ongoing situation you've witnessed before?",
        ],
    ),
    "general": InterviewTemplate(
        id="general",
        name="General Incident",
        description="Other incidents not covered by specific templates",
        icon="📋",
        category="incident",
        initial_questions=[
            "Can you describe what happened?",
            "When and where did this occur?",
            "Who was involved?",
            "What did you observe?",
        ],
        key_details=[
            "Type of incident",
            "Time and location",
            "People involved",
            "Sequence of events",
            "Outcome",
            "Current status",
        ],
        scene_elements=[
            "Location details",
            "People present",
            "Vehicles involved",
            "Environmental conditions",
            "Physical evidence",
        ],
        suggested_prompts=[
            "Is there anything else that stood out to you?",
            "Did anyone else witness this?",
            "Do you have any photos or videos?",
        ],
    ),
}


def get_all_templates() -> List[Dict[str, Any]]:
    """Return all templates as a list of dictionaries."""
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "icon": t.icon,
            "category": t.category,
            "initial_questions": t.initial_questions,
            "key_details": t.key_details,
            "scene_elements": t.scene_elements,
            "suggested_prompts": t.suggested_prompts,
        }
        for t in INTERVIEW_TEMPLATES.values()
    ]


def get_template(template_id: str) -> Optional[Dict[str, Any]]:
    """Get a specific template by ID."""
    template = INTERVIEW_TEMPLATES.get(template_id)
    if not template:
        return None
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "icon": template.icon,
        "category": template.category,
        "initial_questions": template.initial_questions,
        "key_details": template.key_details,
        "scene_elements": template.scene_elements,
        "suggested_prompts": template.suggested_prompts,
    }


def get_templates_by_category(category: str) -> List[Dict[str, Any]]:
    """Get templates filtered by category."""
    return [
        get_template(t.id)
        for t in INTERVIEW_TEMPLATES.values()
        if t.category == category
    ]
