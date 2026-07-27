"""Built-in daily reading tracks."""

from __future__ import annotations

HEALTH_TRACK = {
    "title": "Health, diet, and exercise",
    "topic": "health, diet, and exercise",
    "audience": "general adults interested in practical wellness",
    "disclaimer": "Not medical advice. Consult a clinician for personal health decisions.",
    "pillars": ["nutrition", "exercise", "health"],
    "concepts": {
        "nutrition": [
            {"id": "nutrition.protein.basics", "title": "Protein needs, quality, and distribution"},
            {"id": "nutrition.carbs.fiber", "title": "Carbohydrates, fiber, and glycemic load"},
            {"id": "nutrition.fats.essential", "title": "Dietary fats: essential vs discretionary"},
            {"id": "nutrition.hydration.electrolytes", "title": "Hydration and electrolyte balance"},
            {"id": "nutrition.micronutrients.magnesium", "title": "Magnesium: food sources and signs of low intake"},
            {"id": "nutrition.micronutrients.iron", "title": "Iron status, absorption, and plant vs animal sources"},
            {"id": "nutrition.micronutrients.vitamin_d", "title": "Vitamin D, sunlight, and supplementation basics"},
            {"id": "nutrition.meal_timing", "title": "Meal timing, snacking, and appetite cues"},
            {"id": "nutrition.ultra_processed", "title": "Ultra-processed foods and label reading"},
            {"id": "nutrition.protein.leucine", "title": "Leucine threshold and muscle protein synthesis"},
            {"id": "nutrition.prebiotic_fiber", "title": "Prebiotic fiber and gut-friendly eating patterns"},
            {"id": "nutrition.alcohol.metabolism", "title": "Alcohol, sleep, and recovery interactions"},
            {"id": "nutrition.sodium_potassium", "title": "Sodium, potassium, and blood pressure nutrition"},
            {"id": "nutrition.caffeine", "title": "Caffeine timing, tolerance, and performance"},
            {"id": "nutrition.plate_method", "title": "Plate method and portion sizing without counting"},
        ],
        "exercise": [
            {"id": "exercise.aerobic.zones", "title": "Aerobic training zones and weekly volume"},
            {"id": "exercise.strength.progressive_overload", "title": "Progressive overload and rep ranges"},
            {"id": "exercise.strength.compound_lifts", "title": "Compound movement patterns for beginners"},
            {"id": "exercise.mobility.daily", "title": "Daily mobility vs flexibility work"},
            {"id": "exercise.recovery.deload", "title": "Deload weeks and autoregulation"},
            {"id": "exercise.warmup.ramp_sets", "title": "Warm-ups, ramp sets, and injury risk"},
            {"id": "exercise.cardio.liss_hiit", "title": "LISS vs HIIT: when each helps"},
            {"id": "exercise.neat.steps", "title": "NEAT, step counts, and non-gym activity"},
            {"id": "exercise.core.bracing", "title": "Core bracing vs hollow holds"},
            {"id": "exercise.balance.falls", "title": "Balance training and fall prevention"},
            {"id": "exercise.resistance.bands", "title": "Bands, machines, and free weights tradeoffs"},
            {"id": "exercise.endurance.periodization", "title": "Simple endurance periodization for amateurs"},
            {"id": "exercise.form.eccentrics", "title": "Tempo, eccentrics, and control"},
            {"id": "exercise.consistency.habit", "title": "Building a sustainable training habit"},
            {"id": "exercise.recovery.domains", "title": "Active recovery: walking, swimming, easy cycling"},
        ],
        "health": [
            {"id": "health.sleep.architecture", "title": "Sleep stages, duration, and consistency"},
            {"id": "health.sleep.hygiene", "title": "Sleep hygiene and light exposure"},
            {"id": "health.stress.cortisol", "title": "Stress, cortisol, and recovery capacity"},
            {"id": "health.stress.breathwork", "title": "Breathwork and downshifting the nervous system"},
            {"id": "health.habits.stacking", "title": "Habit stacking for health behaviors"},
            {"id": "health.body_composition", "title": "Body composition vs scale weight"},
            {"id": "health.inflammation.lifestyle", "title": "Lifestyle levers for chronic inflammation"},
            {"id": "health.screen.time", "title": "Screen time, posture, and movement breaks"},
            {"id": "health.sunlight.circadian", "title": "Morning light and circadian alignment"},
            {"id": "health.social.connection", "title": "Social connection and health outcomes"},
            {"id": "health.checkups.basics", "title": "Preventive checkups: what adults commonly track"},
            {"id": "health.heat_cold", "title": "Heat and cold exposure: benefits and safety"},
            {"id": "health.mindful_eating", "title": "Mindful eating and hunger/fullness cues"},
            {"id": "health.walking.longevity", "title": "Walking dose and longevity associations"},
            {"id": "health.recovery.metrics", "title": "Resting heart rate, HRV, and subjective readiness"},
        ],
    },
}

BUILTIN_TRACKS: dict[str, dict] = {
    "health": HEALTH_TRACK,
}
