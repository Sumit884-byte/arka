from arka.voice.edge_speak import resolve_lang


def test_voice_accepts_arbitrary_bcp47_language():
    assert resolve_lang("fr-FR") == "fr-FR"
    assert resolve_lang("pt_BR") == "pt_BR"
