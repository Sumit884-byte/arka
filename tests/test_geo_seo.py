def test_geo_audit_scores_local_docs(tmp_path) -> None:
    from arka.agent.geo_seo import audit
    (tmp_path / "index.html").write_text("<title>Arka</title><meta name='description' content='AI'>\n<script type='application/ld+json'>{}</script>")
    result = audit(tmp_path)
    assert result["score"] >= 33
    assert "title" in result["checks"]
