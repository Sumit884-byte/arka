from PIL import Image

from arka.agent.symbolic_image import comparison


def test_symbolic_comparison_uses_local_assets(tmp_path):
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    Image.new("RGB", (40, 30), "blue").save(left)
    Image.new("RGB", (40, 30), "green").save(right)
    result = comparison(
        str(left),
        str(right),
        left_title="AI FIRST",
        right_title="DATA FIRST",
        output=str(tmp_path / "out.png"),
    )
    assert result["token_cost"] == "local-only"
    assert (tmp_path / "out.png").is_file()
