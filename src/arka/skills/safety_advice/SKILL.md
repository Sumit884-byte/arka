# Safety Advice

Curated, static playbooks for sensitive situations — **gender-neutral and inclusive**, not free-form LLM legal or medical advice.

Applies regardless of gender, age, background, or relationship to the person causing harm.

## Topics

- Domestic or household violence (partner, family, roommate, caregiver)
- Sexual harassment or assault (work, school, online, private)
- Workplace or school harassment
- Stalking
- Online / image-based harassment

## CLI

```bash
arka safety_advice "my partner hit me what should I do"
arka safety_advice "sexual harassment at school" --region in
arka safety_advice "family member is abusive at home"
arka safety_advice resources --topic domestic_violence --region us
```

## Natural language

- "I'm being abused at home"
- "sexual harassment by someone at work"
- "someone is stalking me"

## Region

Set `ARKA_SAFETY_REGION=us|in|intl` (default: `intl`, or `in` when TZ suggests India).

Hotlines may have gendered names (e.g. "Women Helpline") but often serve anyone facing abuse — official names are kept for accuracy.

## MCP (`arka_safety_advice`)

```json
{ "action": "advice", "text": "someone I live with is violent" }
{ "action": "resources", "topic": "sexual_harassment", "region": "in" }
```

## Important

If you are in **immediate danger**, call local emergency services (112 / 911). This skill points to trained advocates; it does not replace them.
