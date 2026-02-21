def build_update_memory_prompt_with_schema(attribute_schema: dict) -> str:

    single_attrs = [k for k, v in attribute_schema.items() if v.get("cardinality") == "one"]

    multi_attrs = [k for k, v in attribute_schema.items() if v.get("cardinality") == "many"]

    return f"""
You curate a user's profile memory. Keep it consistent, avoid duplicates, and NEVER overwrite set-like attributes.

OPERATIONS (per entry):
- ADD: new fact  | UPDATE: change single-valued attr  | DELETE: contradiction/removal  | NONE: already exists/irrelevant

RULES:
1) Owner-only facts. Ignore others.
2) No PII (email/phone/address).
3) Single-valued attrs → UPDATE replaces old value (reuse id). Multi-valued → ADD new items (never UPDATE).
4) Prefer descriptive phrases with action/context when the user provides them. If the user only gives a single word, keep it exactly (do NOT add verbs or details).

ATTRIBUTES (from schema):
• Single: {', '.join(single_attrs)}
• Multi (SETS): {', '.join(multi_attrs)}

⚠️ MULTI-VALUED = SETS (additive):
- {'/'.join(multi_attrs[:3])}/etc. → each item = separate entry with unique id
- "I like X" → Use the user's wording; if they give context keep it, if it's a single word keep it as-is.
- "I also like Y" → ADD another item (never UPDATE an existing one)
- DELETE only on explicit negation: "don't like X anymore" → DELETE that specific interest/skill

ID HANDLING:
- UPDATE/DELETE: reuse EXACT id from Old memory
- ADD: generate new id (e.g., "new_1")

OUTPUT: Return JSON object with format {{"memory": [...]}}

EXAMPLES:
1) Age update:
Old: [{{"id":"10","text":"age: 30"}}]
Facts: ["age: 32"]
→ {{"memory":[{{"id":"10","text":"age: 32","event":"UPDATE","old_memory":"age: 30"}}]}}

2) Multi-valued (CORRECT):
Old: [{{"id":"h1","text":"interest: فوتبال"}}]
Facts: ["interest: شنا"]
→ {{"memory":[{{"id":"h1","text":"interest: فوتبال","event":"NONE"}},{{"id":"new_1","text":"interest: شنا","event":"ADD"}}]}}

3) Multi-valued (WRONG ❌):
Old: [{{"id":"h1","text":"interest: فوتبال"}}]
Facts: ["interest: شنا"]
→ {{"memory":[{{"id":"h1","text":"interest: شنا","event":"UPDATE","old_memory":"interest: فوتبال"}}]}}
⛔ NEVER do this! It deletes "فوتبال".

4) Negative:
Old: [{{"id":"s1","text":"skill: guitar"}}]
Facts: ["NOT musician"]
→ {{"memory":[{{"id":"s1","text":"skill: guitar","event":"DELETE"}}]}}

5) Descriptive interests/skills (GOOD):
Old: []
Facts: ["interest: تمرین فوتبال با دوستان", "interest: تماشای بازی‌های رئال مادرید"]
→ {{"memory":[{{"id":"new_1","text":"interest: تمرین فوتبال با دوستان","event":"ADD"}},{{"id":"new_2","text":"interest: تماشای بازی‌های رئال مادرید","event":"ADD"}}]}}
"""


CUSTOM_UPDATE_MEMORY_PROMPT = build_update_memory_prompt_with_schema({})


def build_fact_extraction_prompt_with_schema(attribute_schema: dict) -> str:

    single_attrs = [k for k, v in attribute_schema.items() if v.get("cardinality") == "one"]

    multi_attrs = [k for k, v in attribute_schema.items() if v.get("cardinality") == "many"]

    alias_examples = []
    for attr_key, attr_info in list(attribute_schema.items())[:5]:
        aliases = attr_info.get("aliases", [])
        if aliases and len(aliases) > 2:
            alias_examples.append(f"- {'/'.join(aliases[:3])} → {attr_key}")

    return f"""
Extract owner-only profile facts as `attr: descriptive value`. No PII (email/phone/address). Ignore chit-chat. Prefer short phrases with context/action if the user provided them; if the user only wrote a single word, keep it as-is (no fabricated context).

ATTRIBUTES (use EXACT keys from schema):
• Single-valued: {', '.join(single_attrs)}
• Multi-valued: {', '.join(multi_attrs)}

KEY MAPPINGS (examples):
{chr(10).join(alias_examples)}
- like/love/دوست دارم/علاقه → interest (preferences)
- can/بلدم/مهارت → skill (abilities)
- Food/dishes → interest or crave (e.g., قرمه‌سبزی → interest: قرمه‌سبزی)

AGE:
- Absolute: `age: 30` | Relative: `age: +2 (relative)` or `age: -3 (relative)`

MULTI-VALUED:
- One line per item; if phrase provided, keep it; if only a word, keep the word:
  - `interest: تمرین فوتبال با دوستان`
  - `interest: تماشای بازی‌های رئال مادرید`
  - `skill: توسعه وب با جنگو`
  - `language: فارسی`
- Negation: `NOT musician` or `REMOVE skill: X`

OUTPUT: Return JSON object with format {{"facts": ["attr: value", ...]}}

EXAMPLES:
Input: "I'm 30, live in Tehran, love football and can code Python."
→ {{"facts": ["age: 30", "current_location: Tehran", "interest: بازی فوتبال", "interest: تماشای فوتبال", "skill: برنامه نویسی پایتون"]}}

Input: "من نوازنده نیستم، خوانندگی می‌کنم. عاشق قرمه‌سبزی‌ام."
→ {{"facts": ["NOT musician", "skill: singing", "interest: قرمه‌سبزی"]}}

Input: "The weather is nice."
→ {{"facts": []}}
"""


CUSTOM_FACT_EXTRACTION_PROMPT = build_fact_extraction_prompt_with_schema({})
