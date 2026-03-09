"""Few-shot examples for scene reconstruction agent prompts.

This module contains curated example witness statements with expected extractions
for use in prompts. Examples are stored in a reusable format that allows:
- Easy addition of new examples over time
- Selection of relevant examples based on incident type
- Consistent JSON output formatting
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class IncidentType(str, Enum):
    """Supported incident types for few-shot examples."""
    TRAFFIC_ACCIDENT = "traffic_accident"
    ARMED_ROBBERY = "armed_robbery"
    ASSAULT = "assault"
    HIT_AND_RUN = "hit_and_run"
    THEFT = "theft"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    GENERAL = "general"


@dataclass
class FewShotExample:
    """A single few-shot example with witness statement and expected extraction."""
    id: str
    incident_type: IncidentType
    witness_statement: str
    expected_extraction: Dict[str, Any]
    tags: List[str] = field(default_factory=list)
    description: str = ""


# ============================================================================
# CURATED FEW-SHOT EXAMPLES
# ============================================================================

EXAMPLES: List[FewShotExample] = [
    # --------------------------------------------------------------------
    # TRAFFIC ACCIDENT EXAMPLES
    # --------------------------------------------------------------------
    FewShotExample(
        id="traffic_001",
        incident_type=IncidentType.TRAFFIC_ACCIDENT,
        description="Two-vehicle collision at intersection with clear visibility",
        witness_statement="""I was walking my dog on the corner of Oak Street and Main Avenue around 3pm yesterday. 
I saw a red Toyota sedan coming down Main Avenue pretty fast, maybe 40mph. The light turned yellow but they 
didn't slow down. A white pickup truck was making a left turn from Oak Street when the Toyota ran the red 
and slammed into the driver's side of the truck. The truck spun around and hit a fire hydrant. 
The Toyota driver was a young man, maybe early 20s, wearing a blue hoodie. He got out and seemed okay 
but the truck driver, an older woman with gray hair, was holding her neck and couldn't move.""",
        expected_extraction={
            "scene_description": "A busy intersection at Oak Street and Main Avenue during a sunny afternoon. A red Toyota sedan traveling at high speed collides with a white pickup truck making a left turn, causing the truck to spin into a fire hydrant. The aftermath shows both vehicles with significant damage, one driver mobile and another injured.",
            "incident_type": "accident",
            "incident_subtype": "traffic_collision",
            "elements": [
                {
                    "type": "vehicle",
                    "description": "Red Toyota sedan",
                    "position": "traveling southbound on Main Avenue, then stopped after impact",
                    "color": "red",
                    "size": "standard sedan",
                    "movement": "traveling at approximately 40mph, ran red light",
                    "confidence": 0.9,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "vehicle",
                    "description": "White pickup truck",
                    "position": "making left turn from Oak Street, spun to fire hydrant after impact",
                    "color": "white",
                    "size": "standard pickup",
                    "movement": "making left turn when struck",
                    "confidence": 0.9,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "person",
                    "description": "Young male driver of Toyota, early 20s, wearing blue hoodie",
                    "position": "exited vehicle after impact",
                    "color": "blue hoodie",
                    "size": "not specified",
                    "movement": "got out of car, appeared uninjured",
                    "confidence": 0.8,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "person",
                    "description": "Older female driver of pickup truck, gray hair, possible neck injury",
                    "position": "remained in vehicle",
                    "color": "gray hair",
                    "size": "not specified",
                    "movement": "holding neck, unable to move",
                    "confidence": 0.8,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "location_feature",
                    "description": "Fire hydrant struck by spinning pickup truck",
                    "position": "corner of intersection",
                    "color": "not specified",
                    "size": "standard fire hydrant",
                    "movement": "stationary, struck by truck",
                    "confidence": 0.9,
                    "mentioned_by": "witness direct observation"
                }
            ],
            "timeline": [
                {"sequence": 1, "time": "approximately 3:00 PM", "description": "Toyota sedan approaching intersection on Main Avenue at high speed", "elements_involved": ["Red Toyota sedan"]},
                {"sequence": 2, "time": "seconds later", "description": "Traffic light turns yellow then red", "elements_involved": []},
                {"sequence": 3, "time": "immediately after", "description": "Toyota runs red light, collides with pickup truck making left turn", "elements_involved": ["Red Toyota sedan", "White pickup truck"]},
                {"sequence": 4, "time": "immediately after impact", "description": "Pickup truck spins and strikes fire hydrant", "elements_involved": ["White pickup truck", "Fire hydrant"]},
                {"sequence": 5, "time": "after collision", "description": "Toyota driver exits vehicle, truck driver remains inside with injury", "elements_involved": ["Young male driver", "Older female driver"]}
            ],
            "location": {
                "description": "Intersection of Oak Street and Main Avenue",
                "type": "intersection",
                "landmarks": ["fire hydrant on corner"]
            },
            "environmental": {
                "weather": "not mentioned, implied clear",
                "lighting": "daylight",
                "time_of_day": "afternoon",
                "visibility": "good"
            },
            "contradictions": [],
            "confidence_assessment": "high",
            "ambiguities": ["exact speed of Toyota estimated", "extent of truck driver injuries unclear"],
            "next_question": "Did you see anyone call 911 or provide assistance to the injured driver?"
        },
        tags=["vehicle_collision", "injury", "red_light_violation", "intersection"]
    ),
    
    # --------------------------------------------------------------------
    # ARMED ROBBERY EXAMPLES
    # --------------------------------------------------------------------
    FewShotExample(
        id="robbery_001",
        incident_type=IncidentType.ARMED_ROBBERY,
        description="Convenience store robbery with weapon and vehicle escape",
        witness_statement="""I was buying coffee at the QuickStop on 5th Street around 11pm. This guy came in wearing 
a black ski mask and a gray jacket. He was maybe 6 feet tall, kind of skinny. He pulled out a gun, 
looked like a black handgun, and pointed it at the cashier. He was yelling "Give me the money!" 
The cashier, a young Asian guy, opened the register and the robber grabbed all the cash. 
Then he ran out and got into a dark blue Honda Civic that was parked right outside with someone 
else driving. They took off heading north on 5th Street. The whole thing took maybe 2 minutes.""",
        expected_extraction={
            "scene_description": "A late-night armed robbery at QuickStop convenience store on 5th Street. A masked suspect in gray jacket threatens the cashier with a black handgun, demands cash from the register, then escapes in a dark blue Honda Civic driven by an accomplice, heading north on 5th Street.",
            "incident_type": "crime",
            "incident_subtype": "armed_robbery",
            "elements": [
                {
                    "type": "person",
                    "description": "Robbery suspect: approximately 6 feet tall, skinny build, wearing black ski mask and gray jacket",
                    "position": "entered store, stood at counter, fled to vehicle",
                    "color": "black ski mask, gray jacket",
                    "size": "approximately 6 feet tall, skinny",
                    "movement": "entered, threatened cashier, grabbed cash, ran to vehicle",
                    "confidence": 0.85,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "person",
                    "description": "Cashier/victim: young Asian male",
                    "position": "behind counter at register",
                    "color": "not specified",
                    "size": "not specified",
                    "movement": "opened register when threatened",
                    "confidence": 0.8,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "person",
                    "description": "Getaway driver: unidentified, inside vehicle",
                    "position": "driver seat of Honda Civic",
                    "color": "not specified",
                    "size": "not specified",
                    "movement": "drove vehicle north on 5th Street",
                    "confidence": 0.5,
                    "mentioned_by": "witness indirect observation"
                },
                {
                    "type": "object",
                    "description": "Black handgun",
                    "position": "held by suspect, pointed at cashier",
                    "color": "black",
                    "size": "handgun size",
                    "movement": "drawn and pointed",
                    "confidence": 0.7,
                    "mentioned_by": "witness observation - type uncertain"
                },
                {
                    "type": "vehicle",
                    "description": "Dark blue Honda Civic - getaway vehicle",
                    "position": "parked directly outside QuickStop, fled north on 5th Street",
                    "color": "dark blue",
                    "size": "compact sedan",
                    "movement": "fled north on 5th Street",
                    "confidence": 0.8,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "location_feature",
                    "description": "QuickStop convenience store",
                    "position": "on 5th Street",
                    "color": "not specified",
                    "size": "standard convenience store",
                    "movement": "stationary",
                    "confidence": 0.95,
                    "mentioned_by": "witness at location"
                }
            ],
            "timeline": [
                {"sequence": 1, "time": "approximately 11:00 PM", "description": "Witness in store buying coffee", "elements_involved": ["QuickStop store"]},
                {"sequence": 2, "time": "11:00 PM", "description": "Masked suspect enters store", "elements_involved": ["Robbery suspect"]},
                {"sequence": 3, "time": "immediately after", "description": "Suspect draws handgun and points at cashier", "elements_involved": ["Robbery suspect", "Black handgun", "Cashier"]},
                {"sequence": 4, "time": "during robbery", "description": "Suspect demands money, cashier opens register", "elements_involved": ["Robbery suspect", "Cashier"]},
                {"sequence": 5, "time": "during robbery", "description": "Suspect grabs cash from register", "elements_involved": ["Robbery suspect"]},
                {"sequence": 6, "time": "end of robbery", "description": "Suspect flees store and enters getaway vehicle", "elements_involved": ["Robbery suspect", "Dark blue Honda Civic", "Getaway driver"]},
                {"sequence": 7, "time": "immediately after", "description": "Vehicle flees north on 5th Street", "elements_involved": ["Dark blue Honda Civic", "Getaway driver"]}
            ],
            "location": {
                "description": "QuickStop convenience store on 5th Street",
                "type": "building",
                "landmarks": ["5th Street"]
            },
            "environmental": {
                "weather": "not mentioned",
                "lighting": "nighttime, store interior lit",
                "time_of_day": "night",
                "visibility": "good inside store"
            },
            "contradictions": [],
            "confidence_assessment": "high",
            "ambiguities": ["exact weapon type uncertain", "getaway driver not described", "exact amount of cash stolen unknown"],
            "next_question": "Did you notice any distinguishing features on the suspect - tattoos, scars, or any visible skin? Also, did you see the license plate on the Honda?"
        },
        tags=["weapon", "getaway_vehicle", "masked_suspect", "convenience_store"]
    ),
    
    # --------------------------------------------------------------------
    # HIT AND RUN EXAMPLE
    # --------------------------------------------------------------------
    FewShotExample(
        id="hitrun_001",
        incident_type=IncidentType.HIT_AND_RUN,
        description="Pedestrian struck by vehicle that fled the scene",
        witness_statement="""I was waiting for the bus on Maple Drive around 7:30 this morning. 
There was a woman crossing the street in the crosswalk, she had a green coat and was carrying a purse. 
This black SUV, I think it was a Ford Explorer or something similar, came around the corner way too fast 
and hit her. She flew onto the hood and then fell onto the street. The SUV didn't even stop, 
it just kept going down Maple Drive toward the highway. I couldn't see the driver clearly but I think 
it might have been a man. The license plate started with 7-something, I couldn't get the rest. 
I ran over to help the woman, she was conscious but her leg looked really bad.""",
        expected_extraction={
            "scene_description": "An early morning hit-and-run on Maple Drive near a bus stop. A black SUV strikes a pedestrian woman wearing a green coat in the crosswalk, causing her to land on the hood then fall to the street. The vehicle flees toward the highway without stopping, leaving the injured victim on the pavement.",
            "incident_type": "crime",
            "incident_subtype": "hit_and_run",
            "elements": [
                {
                    "type": "person",
                    "description": "Female pedestrian victim, wearing green coat, carrying purse, injured leg",
                    "position": "crossing in crosswalk, then on ground after impact",
                    "color": "green coat",
                    "size": "not specified",
                    "movement": "crossing street, struck, flew onto hood then fell to street",
                    "confidence": 0.9,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "vehicle",
                    "description": "Black SUV, possibly Ford Explorer",
                    "position": "came around corner, struck pedestrian, fled toward highway",
                    "color": "black",
                    "size": "SUV",
                    "movement": "traveling too fast around corner, struck pedestrian, fled without stopping",
                    "confidence": 0.75,
                    "mentioned_by": "witness observation - make uncertain"
                },
                {
                    "type": "person",
                    "description": "Driver of SUV, possibly male",
                    "position": "inside SUV",
                    "color": "not visible",
                    "size": "not specified",
                    "movement": "fled scene without stopping",
                    "confidence": 0.4,
                    "mentioned_by": "witness - limited visibility"
                },
                {
                    "type": "location_feature",
                    "description": "Bus stop on Maple Drive",
                    "position": "Maple Drive, near crosswalk",
                    "color": "not specified",
                    "size": "standard bus stop",
                    "movement": "stationary",
                    "confidence": 0.95,
                    "mentioned_by": "witness location"
                },
                {
                    "type": "location_feature",
                    "description": "Crosswalk where pedestrian was struck",
                    "position": "on Maple Drive near bus stop",
                    "color": "not specified",
                    "size": "standard crosswalk",
                    "movement": "stationary",
                    "confidence": 0.9,
                    "mentioned_by": "witness direct observation"
                }
            ],
            "timeline": [
                {"sequence": 1, "time": "approximately 7:30 AM", "description": "Witness waiting at bus stop", "elements_involved": ["Bus stop"]},
                {"sequence": 2, "time": "7:30 AM", "description": "Woman crossing street in crosswalk", "elements_involved": ["Female pedestrian"]},
                {"sequence": 3, "time": "immediately after", "description": "Black SUV comes around corner at high speed", "elements_involved": ["Black SUV"]},
                {"sequence": 4, "time": "impact", "description": "SUV strikes pedestrian, she lands on hood then falls to street", "elements_involved": ["Black SUV", "Female pedestrian"]},
                {"sequence": 5, "time": "immediately after impact", "description": "SUV flees toward highway without stopping", "elements_involved": ["Black SUV", "Driver"]},
                {"sequence": 6, "time": "after incident", "description": "Witness assists injured victim", "elements_involved": ["Female pedestrian"]}
            ],
            "location": {
                "description": "Maple Drive near bus stop and crosswalk, leads toward highway",
                "type": "road",
                "landmarks": ["bus stop", "crosswalk", "highway direction"]
            },
            "environmental": {
                "weather": "not mentioned",
                "lighting": "morning daylight",
                "time_of_day": "morning",
                "visibility": "good"
            },
            "contradictions": [],
            "confidence_assessment": "medium",
            "ambiguities": ["exact vehicle make uncertain (possibly Ford Explorer)", "driver description very limited", "partial license plate only - starts with 7"],
            "next_question": "You mentioned the plate started with 7 - was it a state plate? Did you notice any damage to the SUV after impact, or any other features like roof racks or stickers?"
        },
        tags=["pedestrian", "injury", "fleeing_vehicle", "partial_plate"]
    ),
    
    # --------------------------------------------------------------------
    # ASSAULT EXAMPLE
    # --------------------------------------------------------------------
    FewShotExample(
        id="assault_001",
        incident_type=IncidentType.ASSAULT,
        description="Street assault with multiple suspects",
        witness_statement="""I was coming out of the gym on Center Street around 9pm last night. 
I saw three guys surrounding this one guy near the alley. Two of them were punching him while the third 
one was going through his pockets. The victim was a white guy in his 30s maybe, wearing gym clothes. 
One attacker was tall, bald, wearing a red tank top. Another was shorter with a beard and a black t-shirt. 
The third one had a baseball cap on, couldn't see his face well. They took his wallet and phone 
and then ran down the alley toward King Street. The victim was on the ground bleeding from his face.""",
        expected_extraction={
            "scene_description": "A nighttime assault near an alley on Center Street outside a gym. Three attackers surround a lone victim in gym clothes, two assaulting him while the third searches his pockets. The victim ends up on the ground with facial injuries as the suspects flee through the alley.",
            "incident_type": "crime",
            "incident_subtype": "assault_robbery",
            "elements": [
                {
                    "type": "person",
                    "description": "Victim: white male, approximately 30s, wearing gym clothes, facial bleeding",
                    "position": "near alley, then on ground",
                    "color": "gym clothes (unspecified color)",
                    "size": "not specified",
                    "movement": "being assaulted, fell to ground",
                    "confidence": 0.85,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "person",
                    "description": "Attacker 1: tall, bald, wearing red tank top",
                    "position": "surrounding victim, then fled down alley",
                    "color": "red tank top",
                    "size": "tall",
                    "movement": "punching victim, then fled toward King Street",
                    "confidence": 0.8,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "person",
                    "description": "Attacker 2: shorter, beard, wearing black t-shirt",
                    "position": "surrounding victim, then fled down alley",
                    "color": "black t-shirt",
                    "size": "shorter",
                    "movement": "punching victim, then fled toward King Street",
                    "confidence": 0.8,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "person",
                    "description": "Attacker 3: wearing baseball cap, face not clearly visible",
                    "position": "surrounding victim, then fled down alley",
                    "color": "baseball cap (color unspecified)",
                    "size": "not specified",
                    "movement": "searching victim's pockets, then fled toward King Street",
                    "confidence": 0.6,
                    "mentioned_by": "witness partial observation"
                },
                {
                    "type": "object",
                    "description": "Victim's wallet - stolen",
                    "position": "taken from victim's pocket",
                    "color": "not specified",
                    "size": "standard wallet",
                    "movement": "stolen by attackers",
                    "confidence": 0.9,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "object",
                    "description": "Victim's phone - stolen",
                    "position": "taken from victim's pocket",
                    "color": "not specified",
                    "size": "standard phone",
                    "movement": "stolen by attackers",
                    "confidence": 0.9,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "location_feature",
                    "description": "Alley near gym on Center Street",
                    "position": "leads toward King Street",
                    "color": "not specified",
                    "size": "standard alley",
                    "movement": "stationary - escape route",
                    "confidence": 0.9,
                    "mentioned_by": "witness direct observation"
                }
            ],
            "timeline": [
                {"sequence": 1, "time": "approximately 9:00 PM", "description": "Witness exits gym on Center Street", "elements_involved": []},
                {"sequence": 2, "time": "9:00 PM", "description": "Three attackers surrounding victim near alley", "elements_involved": ["Victim", "Attacker 1", "Attacker 2", "Attacker 3"]},
                {"sequence": 3, "time": "during assault", "description": "Two attackers punching victim while third searches pockets", "elements_involved": ["Victim", "Attacker 1", "Attacker 2", "Attacker 3"]},
                {"sequence": 4, "time": "during assault", "description": "Attackers steal wallet and phone", "elements_involved": ["Attacker 3", "Wallet", "Phone"]},
                {"sequence": 5, "time": "after robbery", "description": "All three attackers flee down alley toward King Street", "elements_involved": ["Attacker 1", "Attacker 2", "Attacker 3", "Alley"]},
                {"sequence": 6, "time": "after assault", "description": "Victim on ground with facial bleeding", "elements_involved": ["Victim"]}
            ],
            "location": {
                "description": "Center Street near gym, adjacent to alley leading to King Street",
                "type": "road",
                "landmarks": ["gym", "alley to King Street"]
            },
            "environmental": {
                "weather": "not mentioned",
                "lighting": "nighttime",
                "time_of_day": "night",
                "visibility": "limited - nighttime"
            },
            "contradictions": [],
            "confidence_assessment": "medium",
            "ambiguities": ["third attacker poorly described", "exact gym clothes description missing", "no age estimates for attackers"],
            "next_question": "Did you notice any tattoos or other identifying marks on any of the attackers? Also, what color was the baseball cap?"
        },
        tags=["multiple_suspects", "theft", "injury", "physical_assault"]
    ),
    
    # --------------------------------------------------------------------
    # THEFT/SUSPICIOUS ACTIVITY EXAMPLE  
    # --------------------------------------------------------------------
    FewShotExample(
        id="theft_001",
        incident_type=IncidentType.THEFT,
        description="Package theft from residential porch",
        witness_statement="""I was working from home and looked out my window around 2pm. 
I saw a silver minivan, maybe a Toyota Sienna, pull up to my neighbor's house at 445 Elm Street. 
A woman got out - she was wearing scrubs like a nurse, dark hair in a ponytail. She walked right up 
to the porch, grabbed two boxes that were sitting there, and walked back to the van like it was 
totally normal. Then she drove off going east. I didn't think anything of it at first but then 
my neighbor came home and said she was expecting packages. The whole thing took maybe 30 seconds.""",
        expected_extraction={
            "scene_description": "A daytime residential package theft on Elm Street. A woman in nurse's scrubs exits a silver minivan, casually walks to a porch at 445 Elm Street, takes two delivered packages, and drives away eastbound. The calculated, calm demeanor suggests a practiced operation.",
            "incident_type": "crime",
            "incident_subtype": "theft",
            "elements": [
                {
                    "type": "person",
                    "description": "Female suspect: dark hair in ponytail, wearing scrubs (nurse-style)",
                    "position": "exited vehicle, walked to porch, returned to vehicle",
                    "color": "scrubs (color unspecified), dark hair",
                    "size": "not specified",
                    "movement": "walked casually to porch, grabbed boxes, returned to van, drove away",
                    "confidence": 0.85,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "vehicle",
                    "description": "Silver minivan, possibly Toyota Sienna",
                    "position": "pulled up to 445 Elm Street, then drove east",
                    "color": "silver",
                    "size": "minivan",
                    "movement": "arrived, stopped, departed eastbound",
                    "confidence": 0.75,
                    "mentioned_by": "witness observation - make uncertain"
                },
                {
                    "type": "object",
                    "description": "Two packages/boxes stolen from porch",
                    "position": "on porch of 445 Elm Street",
                    "color": "not specified",
                    "size": "boxes - size unspecified",
                    "movement": "taken by suspect",
                    "confidence": 0.9,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "location_feature",
                    "description": "Residential house at 445 Elm Street",
                    "position": "Elm Street",
                    "color": "not specified",
                    "size": "residential house",
                    "movement": "stationary",
                    "confidence": 0.95,
                    "mentioned_by": "witness direct observation"
                },
                {
                    "type": "location_feature",
                    "description": "Front porch of 445 Elm Street",
                    "position": "front of house",
                    "color": "not specified",
                    "size": "standard porch",
                    "movement": "stationary",
                    "confidence": 0.9,
                    "mentioned_by": "witness direct observation"
                }
            ],
            "timeline": [
                {"sequence": 1, "time": "approximately 2:00 PM", "description": "Silver minivan pulls up to 445 Elm Street", "elements_involved": ["Silver minivan"]},
                {"sequence": 2, "time": "immediately after", "description": "Female suspect exits vehicle", "elements_involved": ["Female suspect", "Silver minivan"]},
                {"sequence": 3, "time": "seconds later", "description": "Suspect walks to porch and takes two packages", "elements_involved": ["Female suspect", "Packages", "Porch"]},
                {"sequence": 4, "time": "immediately after", "description": "Suspect returns to vehicle", "elements_involved": ["Female suspect", "Silver minivan"]},
                {"sequence": 5, "time": "approximately 30 seconds total", "description": "Vehicle departs eastbound", "elements_involved": ["Silver minivan"]}
            ],
            "location": {
                "description": "445 Elm Street, residential neighborhood",
                "type": "building",
                "landmarks": ["neighbor's house visible from witness window"]
            },
            "environmental": {
                "weather": "not mentioned, implied clear",
                "lighting": "daylight",
                "time_of_day": "afternoon",
                "visibility": "good"
            },
            "contradictions": [],
            "confidence_assessment": "high",
            "ambiguities": ["exact vehicle make uncertain", "scrubs color not specified", "suspect age and build not described"],
            "next_question": "Did you notice any writing or logos on the scrubs, or any other features of the suspect like height or build? Also, did you see a license plate?"
        },
        tags=["package_theft", "residential", "vehicle_involved", "daytime"]
    ),
]


# ============================================================================
# EXAMPLE MANAGEMENT FUNCTIONS
# ============================================================================

def get_examples_by_type(incident_type: IncidentType, limit: int = 2) -> List[FewShotExample]:
    """Get few-shot examples filtered by incident type.
    
    Args:
        incident_type: The type of incident to filter by
        limit: Maximum number of examples to return
        
    Returns:
        List of matching FewShotExample objects
    """
    matching = [ex for ex in EXAMPLES if ex.incident_type == incident_type]
    return matching[:limit]


def get_examples_by_tags(tags: List[str], limit: int = 2) -> List[FewShotExample]:
    """Get few-shot examples that match any of the given tags.
    
    Args:
        tags: List of tags to match
        limit: Maximum number of examples to return
        
    Returns:
        List of matching FewShotExample objects, sorted by tag match count
    """
    def count_matches(example: FewShotExample) -> int:
        return sum(1 for tag in tags if tag in example.tags)
    
    matching = [ex for ex in EXAMPLES if count_matches(ex) > 0]
    matching.sort(key=count_matches, reverse=True)
    return matching[:limit]


def get_general_examples(limit: int = 2) -> List[FewShotExample]:
    """Get a diverse set of examples for general use.
    
    Returns examples covering different incident types for broad coverage.
    
    Args:
        limit: Maximum number of examples to return
        
    Returns:
        List of diverse FewShotExample objects
    """
    # Select diverse examples covering different scenarios
    diverse_ids = ["traffic_001", "robbery_001", "hitrun_001", "assault_001", "theft_001"]
    selected = [ex for ex in EXAMPLES if ex.id in diverse_ids]
    return selected[:limit]


def format_example_for_prompt(example: FewShotExample, include_full_extraction: bool = True) -> str:
    """Format a single example for inclusion in a prompt.
    
    Args:
        example: The example to format
        include_full_extraction: Whether to include full JSON or summarized version
        
    Returns:
        Formatted string for prompt inclusion
    """
    import json
    
    output_lines = [
        f"### Example: {example.description}",
        "",
        "**Witness Statement:**",
        f'"{example.witness_statement.strip()}"',
        "",
        "**Expected Extraction:**",
    ]
    
    if include_full_extraction:
        output_lines.append("```json")
        output_lines.append(json.dumps(example.expected_extraction, indent=2))
        output_lines.append("```")
    else:
        # Summarized version for shorter prompts
        ext = example.expected_extraction
        output_lines.append(f"- Scene: {ext.get('scene_description', '')[:100]}...")
        output_lines.append(f"- Type: {ext.get('incident_type')} / {ext.get('incident_subtype')}")
        output_lines.append(f"- Elements: {len(ext.get('elements', []))} items extracted")
        output_lines.append(f"- Confidence: {ext.get('confidence_assessment')}")
    
    return "\n".join(output_lines)


def format_examples_for_extraction_prompt(
    examples: Optional[List[FewShotExample]] = None,
    incident_type: Optional[IncidentType] = None,
    tags: Optional[List[str]] = None,
    limit: int = 2,
    compact: bool = False
) -> str:
    """Generate formatted few-shot examples section for extraction prompts.
    
    Args:
        examples: Specific examples to use (overrides other selection methods)
        incident_type: Filter examples by incident type
        tags: Filter examples by tags
        limit: Maximum number of examples
        compact: Use summarized format for shorter prompts
        
    Returns:
        Formatted string containing few-shot examples section
    """
    if examples is None:
        if incident_type:
            examples = get_examples_by_type(incident_type, limit)
        elif tags:
            examples = get_examples_by_tags(tags, limit)
        else:
            examples = get_general_examples(limit)
    
    if not examples:
        return ""
    
    sections = [
        "",
        "## Few-Shot Examples",
        "Here are examples of witness statements and their expected JSON extractions:",
        "",
    ]
    
    for example in examples:
        sections.append(format_example_for_prompt(example, include_full_extraction=not compact))
        sections.append("")
    
    return "\n".join(sections)


def add_example(example: FewShotExample) -> bool:
    """Add a new example to the examples list.
    
    This allows dynamic addition of new examples at runtime.
    For persistent storage, examples should be added to this module directly.
    
    Args:
        example: The example to add
        
    Returns:
        True if added successfully, False if ID already exists
    """
    existing_ids = {ex.id for ex in EXAMPLES}
    if example.id in existing_ids:
        return False
    
    EXAMPLES.append(example)
    return True


def list_example_ids() -> List[str]:
    """Get list of all example IDs."""
    return [ex.id for ex in EXAMPLES]


def get_example_by_id(example_id: str) -> Optional[FewShotExample]:
    """Get a specific example by its ID."""
    for ex in EXAMPLES:
        if ex.id == example_id:
            return ex
    return None
