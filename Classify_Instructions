ou are an environmental assessment orchestration agent. Your objective is to analyze observational input from a residential environment and categorize it into the ICD® Clutter–Hoarding Scale® (Levels 1-5). INSTRUCTIONS: 1. Compare the provided environmental observations against the "Clutter_Hoarding_Scale_Criteria" JSON knowledge base. 2. An environment does not need to meet ALL criteria in a level to be categorized there. 3. ESCALATION RULE: If an environment displays symptoms across multiple levels, you must categorize the environment at the HIGHEST level observed for any single critical safety, structural, or health factor. 4. Output your final decision in JSON format matching the following schema: { "assigned_level": integer (1-5), "color_code": string, "severity": string, "primary_justifications": [list of strings detailing the observations that triggered this level], "required_ppe": [list of required protective equipment], "intervention_requirements": string }

JSON

{
  "metadata": {
    "source": "ICD® Clutter–Hoarding Scale®",
    "copyright": "© 2011- 2026 ICD®",
    "purpose": "A Residential Observational Tool"
  },
  "scale": [
    {
      "level": 1,
      "color": "Green",
      "severity": "Low",
      "intervention_context": "Household environment is considered standard with little or no clutter. Special knowledge is always required when working with individuals affected by chronic disorganization and organizing challenges.",
      "criteria": {
        "structure_and_zoning": [
          "All doors, stairways, and windows are accessible",
          "All plumbing, electrical, and HVAC systems are fully functional",
          "Fire and carbon monoxide (CO) detectors installed and functional"
        ],
        "animals_and_pests": [
          "Appropriate animal control (behavior and sanitation)",
          "Number of animals in compliance with zoning regulations",
          "No evidence of non-pet rodents or insects"
        ],
        "household_functions": [
          "No excessive clutter",
          "All rooms are used for intended purposes",
          "All household appliances are fully functional",
          "Consistent routine housekeeping and maintenance"
        ],
        "health_and_safety": [
          "Safe and maintained sanitation conditions",
          "Good air quality; no odors, animal or food waste, or natural propane/gas",
          "Medication: appropriately stored, current dates, and childproof lids as indicated"
        ]
      },
      "ppe_requirements": {
        "level": "Optional",
        "equipment": ["First aid kit", "Hand sanitizer", "Flashlight", "Insect repellent"]
      }
    },
    {
      "level": 2,
      "color": "Blue",
      "severity": "Guarded",
      "intervention_context": "Household environment with evidence of clutter. Specific knowledge is always required.",
      "criteria": {
        "structure_and_zoning": [
          "One major exit blocked",
          "One major appliance or HVAC device not working for longer than one season",
          "Some plumbing or electrical systems are not fully functional",
          "Non-existent or non-functional fire and carbon monoxide (CO) detectors"
        ],
        "animals_and_pests": [
          "Evidence of inappropriate animal control (behavior and sanitation)",
          "Visible or odorous pet waste",
          "Visible pet fur/hair/feathers",
          "Light to medium evidence of common household pests/insects"
        ],
        "household_functions": [
          "Clutter obstructing some functions of key living areas",
          "Slight congestion of exits, entrances, hallways, and stairs",
          "Some household appliances are not fully functional",
          "Inconsistent routine housekeeping and maintenance"
        ],
        "health_and_safety": [
          "Evidence of non-maintained sanitation conditions",
          "Moderate air quality, odors related to dirty dishes, food prep, laundry, toilets, sewers, or gas",
          "Mildew in the bathroom or kitchen",
          "Medication accessible to others and pets; presence of some expired medication"
        ]
      },
      "ppe_requirements": {
        "level": "Light",
        "equipment": ["Medical or industrial grade latex/nitrile gloves", "Caps/disposable bouffant caps", "Disposable shoe covers", "First aid kit", "Hand sanitizer", "Flashlight", "Insect repellent"]
      }
    },
    {
      "level": 3,
      "color": "Yellow",
      "severity": "Elevated",
      "intervention_context": "Pivot point between cluttered and hoarded. Requires advanced knowledge in chronic disorganization and network of mental health professionals.",
      "criteria": {
        "structure_and_zoning": [
          "Visible outdoor clutter, overflow of recycling/furniture/building materials",
          "HVAC devices not working for longer than one season",
          "Non-existent or non-functional fire and CO detectors",
          "Sections of the home with light structural damage (occurred in preceding six months)"
        ],
        "animals_and_pests": [
          "Animal population exceeds local legal regulations",
          "Evidence of inappropriate animal control or inadequate sanitation (fish tanks, animal waste)",
          "Audible evidence of pests; medium level of spiderwebs",
          "Light insect infestation (bedbugs, lice, fleas, roaches, ants, etc.)"
        ],
        "household_functions": [
          "Clutter obstructing functions of key living areas and around exits/entrances/stairs",
          "At least one room is not being used for its intended purpose",
          "Several appliances are not fully functional",
          "Inappropriate usage of electric appliances and extension cords",
          "Substandard housekeeping and maintenance",
          "1-2 obvious hazardous materials in small quantities (chemical spills, broken glass)"
        ],
        "health_and_safety": [
          "Evidence of non-maintained sanitation (soiled prep surfaces, dirty toilets, visible mildew)",
          "Unhealthy air quality, irritating odors, possible natural/propane gas leakage",
          "Garbage cans not in use, full, or overflowing",
          "Accumulated dust, dirt, and debris; dirty laundry scattered",
          "Medication easily accessible to others/pets; presence of expired medication"
        ]
      },
      "ppe_requirements": {
        "level": "Medium",
        "equipment": ["Surgical or particulate respirator mask", "Eyeglasses/safety goggles", "Medical/industrial gloves", "Disposable coveralls", "Bouffant caps", "Work shoes/boots", "First aid kit", "Hand sanitizer", "Flashlight", "Insect repellent"]
      }
    },
    {
      "level": 4,
      "color": "Orange",
      "severity": "High",
      "intervention_context": "Requires coordinated collaborative team (health, social workers, financial, pest control, biohazard, contractors). Advanced knowledge in hoarding behavior required.",
      "criteria": {
        "structure_and_zoning": [
          "Excessive outdoor clutter, random broken items, piled materials",
          "HVAC devices not working for longer than one year",
          "Non-existent or non-functional fire and CO detectors",
          "Structural damage existing for longer than six months",
          "Water-damaged floors/walls/foundations, broken windows/plumbing",
          "Odor or evidence of sewer backup"
        ],
        "animals_and_pests": [
          "Animal population exceeds local ordinances",
          "Poor animal sanitation; destructive behavior",
          "Excessive spiders and webs",
          "Bats, squirrels, rodents in attic or basement (audible/visible)",
          "Medium insect infestation"
        ],
        "household_functions": [
          "Diminished use of and accessibility to key living areas",
          "Several rooms cluttered preventing intended purposes",
          "Clutter inhibits access to exits, entrances, hallways, and stairs",
          "Inappropriate storage of hazardous/combustible materials (gasoline, leaking chemicals)",
          "Appliances used inappropriately (e.g., fridge for non-food)",
          "Improper use of electric space heaters, fans, or extension cords"
        ],
        "health_and_safety": [
          "Rotting food, organic contamination",
          "Expired, leaking, or buckling cans and jars",
          "Dishes and utensils unusable",
          "No linens on beds; sleeping on floor; infestation of bedding/furniture",
          "Very unhealthy air quality; obvious mold/mildew; standing water",
          "Medication inappropriately stored, scattered, expired"
        ]
      },
      "ppe_requirements": {
        "level": "Full",
        "equipment": ["Particulate respirator mask or respirator with organic filters", "Safety goggles", "Heavy duty work gloves and latex/nitrile gloves", "Disposable coveralls/caps/shoe covers", "Work boots", "First aid kit", "Hand sanitizer", "Headlamp", "Insect repellent"]
      }
    },
    {
      "level": 5,
      "color": "Red",
      "severity": "Severe",
      "intervention_context": "Requires formal written agreements, legal proceedings (eviction, condemnation), and a full team of related professionals. Most advanced knowledge required.",
      "criteria": {
        "structure_and_zoning": [
          "Extreme indoor/outdoor clutter; foliage overgrowth; abandoned machinery",
          "Inadequate or nonexistent ventilation; HVAC systems not working",
          "Non-existent or non-functional fire and CO detectors",
          "Water damaged structures; broken windows, doors, plumbing",
          "Unreliable electricity, no running water, broken sewer/septic systems",
          "Irreparable damage to exterior and interior structure"
        ],
        "animals_and_pests": [
          "Animals at risk and dangerous to people due to behavior/health/numbers",
          "Pervasive spiders, mice, rats, squirrels, raccoons, bats, snakes",
          "Heavy insect infestation"
        ],
        "household_functions": [
          "Key living spaces not usable; all rooms not used for intended purposes",
          "Exits, entrances, hallways, and stairs blocked",
          "Toilets, sinks, and tubs not functioning",
          "Hazardous conditions obscured by clutter; appliances unusable",
          "Hazardous/primitive use of kerosene, lanterns, candles as primary heat/light"
        ],
        "health_and_safety": [
          "Human urine and excrement present",
          "Rotting food; organic contamination",
          "Dishes and utensils buried or non-existent",
          "Beds inaccessible or unusable due to clutter/infestation",
          "Pervasive mold/mildew; moisture or standing water",
          "Hazardous air quality, intolerable odors",
          "Medication commingled, haphazard storage, pills not in containers"
        ]
      },
      "ppe_requirements": {
        "level": "Full Required",
        "equipment": ["Particulate respirator mask or respirator with organic filters", "Safety goggles", "Heavy duty work gloves and latex/nitrile gloves", "Disposable coveralls/caps/shoe covers", "Work boots", "First aid kit", "Hand sanitizer", "Headlamp", "Insect repellent"]
      }
    }
  ]
}
